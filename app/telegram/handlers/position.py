from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from app.db.models.feedback_event import FeedbackEvent
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.positions.monitor import position_pnl
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.fsm.onboarding_states import ClosePositionStates
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.main_menu import main_menu_keyboard
from app.telegram.keyboards.settings import PosCB

router = Router(name="position")


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
        position = await OpenPositionRepository(session).get_for_user(
            user.id,
            UUID(callback_data.position_id),
        )
        if position is None:
            await callback.answer("That position is unavailable.")
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
        position = await position_repo.get_for_user(user.id, UUID(position_id))
        if position is None:
            await state.clear()
            await send_text(
                message,
                "That position is unavailable.",
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
