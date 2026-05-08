from __future__ import annotations

from datetime import UTC, datetime, timedelta, time
from decimal import Decimal, InvalidOperation
from uuid import UUID
from zoneinfo import ZoneInfo

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models.feedback_event import FeedbackEvent
from app.db.models.recommendation import Recommendation
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.positions.account import apply_pnl_to_account
from app.services.positions.monitor import position_pnl
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.fsm.onboarding_states import ClosePositionStates
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.main_menu import main_menu_keyboard
from app.telegram.keyboards.settings import PosCB

router = Router(name="position")
POSITION_INACTIVE_TEXT = "That position is no longer active."


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
