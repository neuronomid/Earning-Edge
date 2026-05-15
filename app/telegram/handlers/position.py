from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models.feedback_event import FeedbackEvent
from app.db.models.position_plan_override import PositionPlanOverride
from app.db.models.recommendation import Recommendation
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.position_plan_override_repo import PositionPlanOverrideRepository
from app.db.repositories.position_revalidation_repo import PositionRevalidationRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.positions.account import apply_pnl_to_account
from app.services.positions.monitor import position_pnl
from app.services.positions.plans import active_position_plan
from app.services.positions.revalidation_service import RevalidationService
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.fsm.onboarding_states import AdjustPositionStates, ClosePositionStates
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.main_menu import main_menu_keyboard
from app.telegram.keyboards.settings import (
    PosCB,
    PositionAdjustCB,
    ValApplyCB,
    ValCB,
    position_adjust_keyboard,
    position_delete_confirm_keyboard,
    position_list_keyboard,
)
from app.telegram.templates.validation import render_validation_history

router = Router(name="position")
POSITION_INACTIVE_TEXT = "That position is no longer active."
_K_ADJUST_POSITION_ID = "adjust_position_id"
_K_ADJUST_TARGET_PRICE = "adjust_target_price"


@router.callback_query(PosCB.filter())
async def position_action(
    callback: CallbackQuery,
    callback_data: PosCB,
    state: FSMContext,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        position_repo = OpenPositionRepository(session)
        position = await position_repo.get_active_for_user(
            user.id,
            UUID(callback_data.position_id),
        )
        if position is None:
            await callback.answer(POSITION_INACTIVE_TEXT)
            return

        if callback_data.action == "delete":
            await callback.answer()
            await send_text(
                callback.message,
                (
                    "Delete this active position? It will stop alerts and will not count "
                    "toward P/L or account size."
                ),
                reply_markup=position_delete_confirm_keyboard(callback_data.position_id),
            )
            return

        if callback_data.action == "delete_cancel":
            await callback.answer("Cancelled")
            await send_text(
                callback.message,
                "Delete cancelled.",
                reply_markup=position_list_keyboard(callback_data.position_id),
            )
            return

        if callback_data.action == "delete_confirm":
            recommendation_id = position.recommendation_id
            await FeedbackEventRepository(session).delete_for_recommendation_user(
                recommendation_id,
                user.id,
            )
            await position_repo.delete(position)
            await callback.answer("Deleted")
            await send_text(
                callback.message,
                "Position deleted. It will not count toward P/L or account size.",
            )
            return

    if callback_data.action == "holding":
        await callback.answer("Noted")
        await send_text(callback.message, "Noted. I will keep tracking this position.")
        return

    if callback_data.action == "adjust":
        await callback.answer()
        await send_text(
            callback.message,
            "Choose what to adjust:",
            reply_markup=position_adjust_keyboard(callback_data.position_id),
        )
        return

    if callback_data.action == "sold":
        await callback.answer()
        await state.clear()
        await state.update_data(close_position_id=callback_data.position_id)
        await state.set_state(ClosePositionStates.close_price)
        await send_text(
            callback.message,
            "What price did you sell it for per contract?",
            reply_markup=cancel_keyboard(),
        )
        return

    if callback_data.action in ("mute_tp", "okay_tp", "mute_sl", "okay_sl"):
        await _handle_mute_okay_action(callback, callback_data, user)
        return

    await callback.answer()


@router.callback_query(PositionAdjustCB.filter())
async def position_adjust_choice(
    callback: CallbackQuery,
    callback_data: PositionAdjustCB,
    state: FSMContext,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        row = await OpenPositionRepository(session).get_for_user_with_recommendation(
            user.id,
            UUID(callback_data.position_id),
        )
        if row is None or row[0].status != "active":
            await callback.answer(POSITION_INACTIVE_TEXT)
            return

        if callback_data.action == "cancel":
            await callback.answer("Cancelled")
            await state.clear()
            await send_text(
                callback.message,
                "No changes made.",
                reply_markup=position_list_keyboard(callback_data.position_id),
            )
            return

        position, recommendation = row
        override = await PositionPlanOverrideRepository(session).latest_for_position(position.id)
        plan = active_position_plan(recommendation, override)

    await callback.answer()
    await state.clear()
    await state.update_data({_K_ADJUST_POSITION_ID: callback_data.position_id})

    if callback_data.action == "target":
        await state.set_state(AdjustPositionStates.target_price)
        current = _optional_money(plan.target_option_price)
        await send_text(
            callback.message,
            f"Send the new target option price. Current: {current}.",
            reply_markup=cancel_keyboard(),
        )
        return

    if callback_data.action == "stop":
        await state.set_state(AdjustPositionStates.stop_loss)
        current = _optional_money(plan.stop_loss_option_price)
        await send_text(
            callback.message,
            f"Send the new stop loss option price. Current: {current}.",
            reply_markup=cancel_keyboard(),
        )
        return

    await state.set_state(AdjustPositionStates.both_target_price)
    await send_text(
        callback.message,
        f"Send the new target option price. Current: {_optional_money(plan.target_option_price)}.",
        reply_markup=cancel_keyboard(),
    )


@router.callback_query(ValCB.filter())
async def position_validation_action(
    callback: CallbackQuery,
    callback_data: ValCB,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        row = await OpenPositionRepository(session).get_for_user_with_recommendation(
            user.id,
            UUID(callback_data.position_id),
        )
        if row is None:
            await callback.answer("That position is unavailable.")
            return
        position, _ = row

    if callback_data.action == "history":
        async with session_scope() as session:
            rows = await PositionRevalidationRepository(session).list_for_position(
                UUID(callback_data.position_id),
                limit=5,
            )
        await callback.answer()
        await send_text(callback.message, render_validation_history(rows))
        return

    if position.status != "active":
        await callback.answer(POSITION_INACTIVE_TEXT)
        return

    await callback.answer("Reviewing...")
    result = await RevalidationService().validate_position_manual(
        user_id=user.id,
        position_id=position.id,
    )
    await send_text(
        callback.message,
        result.message,
        reply_markup=result.reply_markup,
    )


@router.callback_query(ValApplyCB.filter())
async def position_validation_apply(
    callback: CallbackQuery,
    callback_data: ValApplyCB,
) -> None:
    if callback.message is None:
        await callback.answer()
        return
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        validation = await PositionRevalidationRepository(session).get(
            UUID(callback_data.validation_id)
        )
        if validation is None or validation.user_id != user.id:
            await callback.answer("That review is unavailable.")
            return
        row = await OpenPositionRepository(session).get_for_user_with_recommendation(
            user.id,
            validation.open_position_id,
        )
        if row is None or row[0].status != "active":
            await callback.answer(POSITION_INACTIVE_TEXT)
            return
        position, recommendation = row
        proposed = validation.proposed_adjustment_json
        if not isinstance(proposed, dict):
            await callback.answer("No adjustment to apply.")
            return

        target = _parse_positive_decimal(str(proposed.get("target_option_price") or ""))
        stop = _parse_positive_decimal(str(proposed.get("stop_loss_option_price") or ""))
        underlying_stop = _parse_positive_decimal(str(proposed.get("underlying_stop_price") or ""))
        apply_target = callback_data.action in {"apply_target", "apply_both"} and target is not None
        apply_stop = callback_data.action in {"apply_stop", "apply_both"} and (
            stop is not None or underlying_stop is not None
        )
        if not apply_target and not apply_stop:
            await callback.answer("No adjustment to apply.")
            return

        override_repo = PositionPlanOverrideRepository(session)
        current_override = await override_repo.latest_for_position(position.id)
        current_plan = active_position_plan(recommendation, current_override)
        effective_target = target if apply_target else current_plan.target_option_price
        effective_stop = (
            stop if stop is not None and apply_stop else current_plan.stop_loss_option_price
        )
        effective_underlying_stop = (
            underlying_stop
            if underlying_stop is not None and apply_stop
            else current_plan.underlying_stop_price
        )
        await override_repo.add(
            PositionPlanOverride(
                open_position_id=position.id,
                position_revalidation_id=validation.id,
                target_option_price=effective_target,
                stop_loss_option_price=effective_stop,
                underlying_stop_price=effective_underlying_stop,
                source="validation",
                reason=str(proposed.get("reason") or "LLM validation adjustment"),
            )
        )
        if apply_target:
            position.target_dismissed = False
            position.target_muted_until = None
            position.target_alert_count = 0
        if apply_stop:
            position.stop_dismissed = False
            position.stop_muted_until = None
            position.stop_alert_count = 0

    await callback.answer("Applied")
    await send_text(
        callback.message,
        (
            "Applied adjustment. "
            f"Target: {_optional_money(effective_target)} · "
            f"Stop: {_optional_money(effective_stop)}."
        ),
    )


@router.message(AdjustPositionStates.target_price, F.text == CANCEL_BTN)
@router.message(AdjustPositionStates.stop_loss, F.text == CANCEL_BTN)
@router.message(AdjustPositionStates.both_target_price, F.text == CANCEL_BTN)
@router.message(AdjustPositionStates.both_stop_loss, F.text == CANCEL_BTN)
async def cancel_adjust_position(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(AdjustPositionStates.target_price)
async def capture_adjust_target(message: Message, state: FSMContext) -> None:
    target = _parse_positive_decimal(message.text)
    if target is None:
        await send_text(
            message,
            "Send the target option price as a positive number, for example 2.10.",
        )
        return
    await _commit_adjustment(message, state, target_price=target)


@router.message(AdjustPositionStates.stop_loss)
async def capture_adjust_stop(message: Message, state: FSMContext) -> None:
    stop = _parse_positive_decimal(message.text)
    if stop is None:
        await send_text(
            message,
            "Send the stop loss option price as a positive number, for example 0.60.",
        )
        return
    await _commit_adjustment(message, state, stop_loss_price=stop)


@router.message(AdjustPositionStates.both_target_price)
async def capture_adjust_both_target(message: Message, state: FSMContext) -> None:
    target = _parse_positive_decimal(message.text)
    if target is None:
        await send_text(
            message,
            "Send the target option price as a positive number, for example 2.10.",
        )
        return
    await state.update_data({_K_ADJUST_TARGET_PRICE: str(target)})
    await state.set_state(AdjustPositionStates.both_stop_loss)
    await send_text(
        message,
        "Send the new stop loss option price.",
        reply_markup=cancel_keyboard(),
    )


@router.message(AdjustPositionStates.both_stop_loss)
async def capture_adjust_both_stop(message: Message, state: FSMContext) -> None:
    stop = _parse_positive_decimal(message.text)
    if stop is None:
        await send_text(
            message,
            "Send the stop loss option price as a positive number, for example 0.60.",
        )
        return
    data = await state.get_data()
    target = _parse_positive_decimal(str(data.get(_K_ADJUST_TARGET_PRICE, "")))
    if target is None:
        await state.clear()
        await send_text(
            message,
            "I lost track of the target price. Open Positions and try again.",
            reply_markup=main_menu_keyboard(),
        )
        return
    await _commit_adjustment(message, state, target_price=target, stop_loss_price=stop)


@router.message(ClosePositionStates.close_price, F.text == CANCEL_BTN)
async def cancel_close_position(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(ClosePositionStates.close_price)
async def capture_close_price(message: Message, state: FSMContext) -> None:
    close_price = _parse_positive_decimal(message.text)
    if close_price is None:
        await send_text(message, "Send the sell price as a positive number, for example 2.10.")
        return

    data = await state.get_data()
    position_id = str(data.get("close_position_id", ""))
    if not position_id:
        await state.clear()
        await send_text(
            message,
            "I lost track of that position. Please wait for the next alert and try again.",
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

        position_repo = OpenPositionRepository(session)
        position = await position_repo.get_active_for_user(user.id, UUID(position_id))
        if position is None:
            await state.clear()
            await send_text(
                message,
                POSITION_INACTIVE_TEXT,
                reply_markup=main_menu_keyboard(),
            )
            return
        recommendation = await RecommendationRepository(session).get(position.recommendation_id)
        if recommendation is None:
            await state.clear()
            await send_text(
                message,
                "That recommendation is unavailable.",
                reply_markup=main_menu_keyboard(),
            )
            return

        pnl = position_pnl(
            entry_price=position.entry_price,
            close_price=close_price,
            quantity=position.entry_quantity,
            position_side=recommendation.position_side,
        )
        position.status = "closed_sold"
        position.close_price = close_price
        position.close_at = datetime.now(UTC)
        apply_pnl_to_account(user, position, recommendation)
        await FeedbackEventRepository(session).add(
            FeedbackEvent(
                recommendation_id=position.recommendation_id,
                user_id=user.id,
                user_action="closed",
                exit_price=close_price,
                pnl=pnl,
            )
        )

    await state.clear()
    await send_text(
        message,
        f"Position closed. Logged P/L: ${pnl:.2f}.",
        reply_markup=main_menu_keyboard(),
    )


def _parse_positive_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


async def _commit_adjustment(
    message: Message,
    state: FSMContext,
    *,
    target_price: Decimal | None = None,
    stop_loss_price: Decimal | None = None,
) -> None:
    data = await state.get_data()
    position_id = str(data.get(_K_ADJUST_POSITION_ID, ""))
    if not position_id:
        await state.clear()
        await send_text(
            message,
            "I lost track of that position. Open Positions and try again.",
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

        row = await OpenPositionRepository(session).get_for_user_with_recommendation(
            user.id,
            UUID(position_id),
        )
        if row is None or row[0].status != "active":
            await state.clear()
            await send_text(
                message,
                POSITION_INACTIVE_TEXT,
                reply_markup=main_menu_keyboard(),
            )
            return

        position, recommendation = row
        override_repo = PositionPlanOverrideRepository(session)
        current_override = await override_repo.latest_for_position(position.id)
        current_plan = active_position_plan(recommendation, current_override)

        effective_target = (
            target_price if target_price is not None else current_plan.target_option_price
        )
        effective_stop = (
            stop_loss_price if stop_loss_price is not None else current_plan.stop_loss_option_price
        )
        target_changed = (
            target_price is not None and target_price != current_plan.target_option_price
        )
        stop_changed = (
            stop_loss_price is not None and stop_loss_price != current_plan.stop_loss_option_price
        )

        await override_repo.add(
            PositionPlanOverride(
                open_position_id=position.id,
                target_option_price=effective_target,
                stop_loss_option_price=effective_stop,
                underlying_stop_price=current_plan.underlying_stop_price,
                source="user",
                reason="manual Telegram adjustment",
            )
        )

        if target_changed:
            position.target_dismissed = False
            position.target_muted_until = None
            position.target_alert_count = 0
        if stop_changed:
            position.stop_dismissed = False
            position.stop_muted_until = None
            position.stop_alert_count = 0

    await state.clear()
    await send_text(
        message,
        (
            "Adjusted. "
            f"Target: {_optional_money(effective_target)} · "
            f"Stop: {_optional_money(effective_stop)}."
        ),
        reply_markup=main_menu_keyboard(),
    )


def _optional_money(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:.2f}"


async def _handle_mute_okay_action(
    callback: CallbackQuery,
    callback_data: PosCB,
    user,
) -> None:
    """Handle Mute and Okay buttons for TP/SL alerts."""
    if callback.message is None:
        await callback.answer()
        return

    action = callback_data.action
    is_tp = "tp" in action
    is_okay = "okay" in action

    async with session_scope() as session:
        position_repo = OpenPositionRepository(session)
        position = await position_repo.get_active_for_user(
            user.id,
            UUID(callback_data.position_id),
        )
        if position is None:
            await callback.answer(POSITION_INACTIVE_TEXT)
            return

        recommendation = await session.get(Recommendation, position.recommendation_id)
        if recommendation is None:
            await callback.answer("Recommendation unavailable")
            return

        if is_okay:
            if is_tp:
                position.target_dismissed = True
                msg = "Got it — no more TP alerts for this position."
            else:
                position.stop_dismissed = True
                msg = "Got it — no more SL alerts for this position."
        else:  # mute
            muted_until = _calculate_muted_until(user.alert_mute_duration, recommendation.expiry)
            if is_tp:
                position.target_muted_until = muted_until
            else:
                position.stop_muted_until = muted_until
            label = _mute_label(user.alert_mute_duration, recommendation.expiry)
            msg = f"Muted until {label}."

        await session.flush()

    await callback.answer(msg)


def _calculate_muted_until(duration: str, expiry_date) -> datetime:
    """Calculate when the mute period expires."""
    now = datetime.now(UTC)
    et = ZoneInfo("America/New_York")

    if duration == "2h":
        return now + timedelta(hours=2)
    elif duration == "1d":
        return now + timedelta(days=1)
    elif duration == "1d_before_expire":
        # 9:30 AM ET on (expiry - 1 day)
        target_date = expiry_date - timedelta(days=1)
        return datetime.combine(target_date, time(9, 30), tzinfo=et)
    elif duration == "3d_before_expire":
        # 9:30 AM ET on (expiry - 3 days)
        target_date = expiry_date - timedelta(days=3)
        return datetime.combine(target_date, time(9, 30), tzinfo=et)
    elif duration == "forever":
        # Past expiry = never fires
        return datetime.combine(expiry_date + timedelta(days=1), time(0, 0), tzinfo=UTC)
    else:
        # Default: 1 day
        return now + timedelta(days=1)


def _mute_label(duration: str, expiry_date) -> str:
    """Format mute duration for user display."""
    if duration == "2h":
        return "2 hours"
    elif duration == "1d":
        return "1 day"
    elif duration == "1d_before_expire":
        return f"{(expiry_date - timedelta(days=1)).strftime('%b %d')}"
    elif duration == "3d_before_expire":
        return f"{(expiry_date - timedelta(days=3)).strftime('%b %d')}"
    elif duration == "forever":
        return f"after expiry ({expiry_date.strftime('%b %d')})"
    else:
        return "1 day"
