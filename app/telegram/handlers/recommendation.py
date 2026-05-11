from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.core.logging import get_logger
from app.db.models.feedback_event import FeedbackEvent
from app.db.models.open_position import OpenPosition
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.alternative_recommendation_service import AlternativeRecommendationService
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.fsm.onboarding_states import BoughtPositionStates
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.main_menu import main_menu_keyboard
from app.telegram.keyboards.settings import AltRecCB, RecCB, recommendation_keyboard
from app.telegram.templates.main_recommendation import render_main_recommendation

router = Router(name="recommendation")
logger = get_logger(__name__)


@router.callback_query(RecCB.filter())
async def recommendation_action(
    callback: CallbackQuery,
    callback_data: RecCB,
    state: FSMContext | None = None,
) -> None:
    if callback.message is None:
        await _answer_callback(callback, action=callback_data.action)
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await _answer_callback(
                callback,
                action=callback_data.action,
                text="Finish setup first.",
            )
            return

        recommendation = await RecommendationRepository(session).get(UUID(callback_data.rec_id))
        if recommendation is None or recommendation.user_id != user.id:
            await _answer_callback(
                callback,
                action=callback_data.action,
                text="That recommendation is unavailable.",
            )
            return

        if callback_data.action == "why":
            await _answer_callback(callback, action=callback_data.action)
            await send_text(callback.message, _render_why(recommendation))
            return
        if callback_data.action == "risk":
            await _answer_callback(callback, action=callback_data.action)
            await send_text(callback.message, _render_risk(recommendation))
            return
        if callback_data.action == "alts":
            await _answer_callback(callback, action=callback_data.action)
            await _send_next_alternative(
                callback=callback,
                user=user,
                current_recommendation=recommendation,
            )
            return
        if callback_data.action == "save_note":
            await _answer_callback(callback, action=callback_data.action)
            await send_text(callback.message, _render_note(recommendation))
            return
        if callback_data.action == "bought":
            await _answer_callback(callback, action=callback_data.action)
            if state is None:
                await send_text(
                    callback.message,
                    "I could not start position tracking from this button. Try again in a moment.",
                )
                return
            existing = await OpenPositionRepository(session).get_active_for_recommendation(
                recommendation.id
            )
            if existing is not None:
                await send_text(
                    callback.message,
                    "I am already tracking this position.",
                )
                return
            await state.clear()
            await state.update_data(
                bought_recommendation_id=str(recommendation.id),
                default_quantity=max(recommendation.suggested_quantity, 1),
            )
            await state.set_state(BoughtPositionStates.entry_price)
            await send_text(
                callback.message,
                "What was your fill price per contract?",
                reply_markup=cancel_keyboard(),
            )
            return
        if callback_data.action == "skipped":
            await FeedbackEventRepository(session).add(
                FeedbackEvent(
                    recommendation_id=recommendation.id,
                    user_id=user.id,
                    user_action="skipped",
                )
            )
            await _answer_callback(callback, action=callback_data.action, text="Saved")
            await send_text(
                callback.message,
                "Feedback saved. I'll keep that attached to this recommendation.",
            )
            return

    await _answer_callback(callback, action=callback_data.action)


@router.message(BoughtPositionStates.entry_price, F.text == CANCEL_BTN)
async def cancel_bought_position(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(BoughtPositionStates.entry_price)
async def capture_entry_price(message: Message, state: FSMContext) -> None:
    entry_price = _parse_positive_decimal(message.text)
    if entry_price is None:
        await send_text(message, "Send the fill price as a positive number, for example 1.25.")
        return
    await state.update_data(entry_price=str(entry_price))
    data = await state.get_data()
    default_quantity = int(data.get("default_quantity", 1))
    await state.set_state(BoughtPositionStates.entry_quantity)
    await send_text(
        message,
        f"How many contracts? Default: {default_quantity}.",
        reply_markup=cancel_keyboard(),
    )


@router.message(BoughtPositionStates.entry_quantity, F.text == CANCEL_BTN)
async def cancel_bought_quantity(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(BoughtPositionStates.entry_quantity)
async def capture_entry_quantity(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    default_quantity = int(data.get("default_quantity", 1))
    entry_quantity = _parse_quantity(message.text, default_quantity=default_quantity)
    if entry_quantity is None:
        await send_text(message, "Send the contract count as a whole number, or send default.")
        return

    recommendation_id = str(data.get("bought_recommendation_id", ""))
    entry_price = _parse_positive_decimal(str(data.get("entry_price", "")))
    if not recommendation_id or entry_price is None:
        await state.clear()
        await send_text(
            message,
            "I lost track of that recommendation. Please open Last Recommendation and try again.",
            reply_markup=main_menu_keyboard(),
        )
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(message.chat.id))
        if user is None:
            await state.clear()
            await send_text(
                message,
                "Send /start to finish setup first.",
                reply_markup=main_menu_keyboard(),
            )
            return
        recommendation = await RecommendationRepository(session).get(UUID(recommendation_id))
        if recommendation is None or recommendation.user_id != user.id:
            await state.clear()
            await send_text(
                message,
                "That recommendation is unavailable.",
                reply_markup=main_menu_keyboard(),
            )
            return

        position_repo = OpenPositionRepository(session)
        existing = await position_repo.get_active_for_recommendation(recommendation.id)
        if existing is None:
            await FeedbackEventRepository(session).add(
                FeedbackEvent(
                    recommendation_id=recommendation.id,
                    user_id=user.id,
                    user_action="bought",
                    entry_price=entry_price,
                )
            )
            await position_repo.add(
                OpenPosition(
                    recommendation_id=recommendation.id,
                    user_id=user.id,
                    entry_price=entry_price,
                    entry_quantity=entry_quantity,
                    status="active",
                )
            )

    await state.clear()
    await send_text(
        message,
        "Tracking this position. I will alert you on target, stop, exit date, and expiry.",
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(AltRecCB.filter())
async def recommendation_alternative(callback: CallbackQuery, callback_data: AltRecCB) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return

        cursor = await RecommendationRepository(session).get(UUID(callback_data.cursor_rec_id))
        if cursor is None or cursor.user_id != user.id:
            await callback.answer("That recommendation is unavailable.")
            return

        await callback.answer("Assessing the next setup...")
        await _send_next_alternative(
            callback=callback,
            user=user,
            current_recommendation=cursor,
        )


async def _send_next_alternative(
    *,
    callback: CallbackQuery,
    user,
    current_recommendation,
) -> None:
    assert callback.message is not None
    async with session_scope() as session:
        refreshed_user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if refreshed_user is None:
            await send_text(callback.message, "Finish setup first.")
            return
        recommendation = await RecommendationRepository(session).get(current_recommendation.id)
        if recommendation is None:
            await send_text(callback.message, "That recommendation is unavailable.")
            return
        result = await AlternativeRecommendationService(session).build_next(
            user=refreshed_user,
            current_recommendation=recommendation,
        )
        if result.recommendation is None:
            await send_text(
                callback.message,
                result.message
                or "No additional qualified alternatives are available for this run.",
            )
            return
        await send_text(
            callback.message,
            render_main_recommendation(
                result.recommendation,
                rank_position=result.rank_position or 2,
                watchlist_only=result.watchlist_only,
            ),
            reply_markup=recommendation_keyboard(str(result.recommendation.id)),
        )


def _render_why(recommendation) -> str:
    evidence = _normalize_string_list(recommendation.key_evidence_json)
    concerns = _normalize_string_list(recommendation.key_concerns_json)

    lines = [
        f"<b>Why {recommendation.ticker}</b>",
        "",
        recommendation.reasoning_summary,
    ]
    if evidence:
        lines.extend(["", "<b>Key evidence</b>"])
        lines.extend(f"- {item}" for item in evidence[:4])
    if concerns:
        lines.extend(["", "<b>Main concerns</b>"])
        lines.extend(f"- {item}" for item in concerns[:3])
    return "\n".join(lines)


def _render_risk(recommendation) -> str:
    lines = [
        f"<b>Risk / Sizing for {recommendation.ticker}</b>",
        "",
        (
            "Contract: "
            f"{'Short' if recommendation.position_side == 'short' else 'Buy'} "
            f"{recommendation.option_type.capitalize()}"
        ),
        f"Strike: ${recommendation.strike}",
        f"Expiry: {recommendation.expiry.isoformat()}",
        f"Suggested quantity: {recommendation.suggested_quantity} contract(s)",
        f"Stored sizing note: {recommendation.estimated_max_loss}",
        f"Account risk: {recommendation.account_risk_percent}%",
    ]
    return "\n".join(lines)


def _render_note(recommendation) -> str:
    return (
        f"<b>Saved Note for {recommendation.ticker}</b>\n\n"
        f"{recommendation.reasoning_summary}\n\n"
        f"Confidence: {recommendation.confidence_score}/100"
    )


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [str(item) for item in items]
    return []


def _parse_positive_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_quantity(value: str | None, *, default_quantity: int) -> int | None:
    text = "" if value is None else value.strip().lower()
    if text == "default":
        return default_quantity
    try:
        parsed = int(text)
    except ValueError:
        return None
    return parsed if parsed > 0 else None


async def _answer_callback(
    callback: CallbackQuery,
    *,
    action: str,
    text: str | None = None,
) -> None:
    try:
        if text is None:
            await callback.answer()
        else:
            await callback.answer(text)
    except TelegramBadRequest as exc:
        error_text = str(exc).lower()
        if (
            "query is too old" in error_text
            or "response timeout expired" in error_text
            or "query id is invalid" in error_text
        ):
            logger.warning(
                "telegram_callback_answer_expired",
                action=action,
                user_id=str(callback.from_user.id),
                error=str(exc),
            )
            return
        raise
