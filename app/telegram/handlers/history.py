from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from uuid import UUID

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State
from aiogram.types import CallbackQuery, Message

from app.db.repositories.open_position_repo import OpenPositionRepository
from app.services.positions.account import (
    apply_pnl_to_account,
    realized_pnl,
    reverse_pnl_from_account,
)
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.fsm.onboarding_states import HistoryModifyStates
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.confirm import CANCEL_BTN, cancel_keyboard
from app.telegram.keyboards.history import (
    HistCB,
    history_card_keyboard,
    history_delete_confirm_keyboard,
    history_modify_keyboard,
)
from app.telegram.keyboards.main_menu import BTN_HISTORY, main_menu_keyboard
from app.telegram.templates.history import (
    compute_history_summary,
    render_history_card,
    render_history_summary,
)

router = Router(name="history")

POSITION_NOT_FOUND_TEXT = "That history entry is no longer available."
EMPTY_HISTORY_TEXT = "📜 No closed trades yet."

# Session-scope FSM data keys for the modify flow
_K_POSITION_ID = "history_modify_position_id"
_K_FIELD = "history_modify_field"


@router.message(F.text == BTN_HISTORY)
async def show_history(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(chat_id)
        if user is None:
            await send_text(
                message,
                "Looks like you haven't finished setup. Send /start to begin.",
                reply_markup=main_menu_keyboard(),
            )
            return

        repo = OpenPositionRepository(session)
        rows = await repo.list_closed_with_recommendations_for_user(user.id)
        summary = compute_history_summary(user, rows)

    if not rows:
        await send_text(message, EMPTY_HISTORY_TEXT, reply_markup=main_menu_keyboard())
        return

    for position, recommendation in rows:
        await send_text(
            message,
            render_history_card(position, recommendation),
            reply_markup=history_card_keyboard(str(position.id)),
        )

    await send_text(
        message,
        render_history_summary(summary),
        reply_markup=main_menu_keyboard(),
    )


@router.callback_query(HistCB.filter())
async def history_action(
    callback: CallbackQuery,
    callback_data: HistCB,
    state: FSMContext,
) -> None:
    if callback.message is None:
        await callback.answer()
        return

    action = callback_data.action
    position_id = callback_data.position_id

    if action == "del":
        await callback.answer()
        await send_text(
            callback.message,
            "Delete this trade? Its P/L will be reversed from your account size.",
            reply_markup=history_delete_confirm_keyboard(position_id),
        )
        return

    if action == "del_no":
        await callback.answer("Cancelled")
        await send_text(callback.message, "Delete cancelled.")
        return

    if action == "del_ok":
        await _confirm_delete(callback, position_id)
        return

    if action == "mod_open":
        await callback.answer()
        await send_text(
            callback.message,
            "Pick the field to modify:",
            reply_markup=history_modify_keyboard(position_id),
        )
        return

    if action == "mod_cancel":
        await state.clear()
        await callback.answer("Cancelled")
        await send_text(
            callback.message,
            "No changes made.",
            reply_markup=history_card_keyboard(position_id),
        )
        return

    if action in {"mod_entry", "mod_exit", "mod_qty", "mod_edate", "mod_xdate"}:
        await _start_modify_flow(callback, state, position_id, action)
        return

    await callback.answer()


async def _confirm_delete(callback: CallbackQuery, position_id: str) -> None:
    assert callback.message is not None
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        repo = OpenPositionRepository(session)
        row = await repo.get_for_user_with_recommendation(user.id, UUID(position_id))
        if row is None:
            await callback.answer(POSITION_NOT_FOUND_TEXT)
            return
        position, recommendation = row
        if position.status == "active":
            await callback.answer("That trade is still open.")
            return
        reverse_pnl_from_account(user, position, recommendation)
        await session.delete(position)

    await callback.answer("Deleted")
    await send_text(callback.message, "Trade removed from history.")


async def _start_modify_flow(
    callback: CallbackQuery,
    state: FSMContext,
    position_id: str,
    action: str,
) -> None:
    assert callback.message is not None
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        row = await OpenPositionRepository(session).get_for_user_with_recommendation(
            user.id, UUID(position_id)
        )
        if row is None or row[0].status == "active":
            await callback.answer(POSITION_NOT_FOUND_TEXT)
            return

    field, target_state, prompt = _modify_prompt_for(action)
    await callback.answer()
    await state.clear()
    await state.update_data({_K_POSITION_ID: position_id, _K_FIELD: field})
    await state.set_state(target_state)
    await send_text(callback.message, prompt, reply_markup=cancel_keyboard())


def _modify_prompt_for(action: str) -> tuple[str, State, str]:
    if action == "mod_entry":
        return (
            "entry_price",
            HistoryModifyStates.entry_price,
            "Send the corrected entry price per contract, e.g. 1.25.",
        )
    if action == "mod_exit":
        return (
            "exit_price",
            HistoryModifyStates.exit_price,
            "Send the corrected exit price per contract, e.g. 2.10.",
        )
    if action == "mod_qty":
        return (
            "quantity",
            HistoryModifyStates.quantity,
            "Send the corrected number of contracts as a whole number.",
        )
    if action == "mod_edate":
        return (
            "entry_date",
            HistoryModifyStates.entry_date,
            "Send the corrected entry date as YYYY-MM-DD.",
        )
    return (
        "exit_date",
        HistoryModifyStates.exit_date,
        "Send the corrected exit date as YYYY-MM-DD.",
    )


# ---------- Modify capture handlers ----------


@router.message(HistoryModifyStates.entry_price, F.text == CANCEL_BTN)
@router.message(HistoryModifyStates.exit_price, F.text == CANCEL_BTN)
@router.message(HistoryModifyStates.quantity, F.text == CANCEL_BTN)
@router.message(HistoryModifyStates.entry_date, F.text == CANCEL_BTN)
@router.message(HistoryModifyStates.exit_date, F.text == CANCEL_BTN)
async def cancel_modify(message: Message, state: FSMContext) -> None:
    await state.clear()
    await send_text(message, "Cancelled.", reply_markup=main_menu_keyboard())


@router.message(HistoryModifyStates.entry_price)
async def capture_modify_entry_price(message: Message, state: FSMContext) -> None:
    new_price = _parse_positive_decimal(message.text)
    if new_price is None:
        await send_text(message, "Send a positive number, e.g. 1.25.")
        return
    await _commit_decimal_change(message, state, "entry_price", new_price)


@router.message(HistoryModifyStates.exit_price)
async def capture_modify_exit_price(message: Message, state: FSMContext) -> None:
    new_price = _parse_positive_decimal(message.text)
    if new_price is None:
        await send_text(message, "Send a positive number, e.g. 2.10.")
        return
    await _commit_decimal_change(message, state, "close_price", new_price)


@router.message(HistoryModifyStates.quantity)
async def capture_modify_quantity(message: Message, state: FSMContext) -> None:
    new_qty = _parse_positive_int(message.text)
    if new_qty is None:
        await send_text(message, "Send a positive whole number, e.g. 2.")
        return
    await _commit_int_change(message, state, "entry_quantity", new_qty)


@router.message(HistoryModifyStates.entry_date)
async def capture_modify_entry_date(message: Message, state: FSMContext) -> None:
    new_date = _parse_iso_date(message.text)
    if new_date is None:
        await send_text(message, "Send a date as YYYY-MM-DD, e.g. 2026-04-15.")
        return
    new_value = datetime.combine(new_date, time(0, 0, tzinfo=UTC))
    await _commit_datetime_change(message, state, "entry_at", new_value)


@router.message(HistoryModifyStates.exit_date)
async def capture_modify_exit_date(message: Message, state: FSMContext) -> None:
    new_date = _parse_iso_date(message.text)
    if new_date is None:
        await send_text(message, "Send a date as YYYY-MM-DD, e.g. 2026-04-22.")
        return
    new_value = datetime.combine(new_date, time(0, 0, tzinfo=UTC))
    await _commit_datetime_change(message, state, "close_at", new_value)


# ---------- Commit helpers ----------


async def _commit_decimal_change(
    message: Message,
    state: FSMContext,
    attr: str,
    new_value: Decimal,
) -> None:
    await _commit_change(message, state, attr, new_value, recompute_pnl=True)


async def _commit_int_change(
    message: Message,
    state: FSMContext,
    attr: str,
    new_value: int,
) -> None:
    await _commit_change(message, state, attr, new_value, recompute_pnl=True)


async def _commit_datetime_change(
    message: Message,
    state: FSMContext,
    attr: str,
    new_value: datetime,
) -> None:
    # Date-only edits don't affect P/L, but we still re-snapshot to keep the
    # account_size adjustment idempotent if other concurrent edits landed.
    await _commit_change(message, state, attr, new_value, recompute_pnl=False)


async def _commit_change(
    message: Message,
    state: FSMContext,
    attr: str,
    new_value: object,
    *,
    recompute_pnl: bool,
) -> None:
    data = await state.get_data()
    position_id = str(data.get(_K_POSITION_ID, ""))
    if not position_id:
        await state.clear()
        await send_text(
            message,
            "I lost track of that trade. Open History again and retry.",
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
            user.id, UUID(position_id)
        )
        if row is None:
            await state.clear()
            await send_text(
                message,
                POSITION_NOT_FOUND_TEXT,
                reply_markup=main_menu_keyboard(),
            )
            return
        position, recommendation = row
        if position.status == "active":
            await state.clear()
            await send_text(
                message,
                "That trade is still open. Close it first to edit history.",
                reply_markup=main_menu_keyboard(),
            )
            return

        if recompute_pnl:
            previous_pnl = realized_pnl(position, recommendation)
            reverse_pnl_from_account(user, position, recommendation)
            setattr(position, attr, new_value)
            apply_pnl_to_account(user, position, recommendation)
            new_pnl = realized_pnl(position, recommendation)
            confirmation = (
                f"Updated. P/L moved from {_pnl_text(previous_pnl)} to {_pnl_text(new_pnl)}."
            )
        else:
            setattr(position, attr, new_value)
            confirmation = "Updated."

    await state.clear()
    await send_text(message, confirmation, reply_markup=main_menu_keyboard())


# ---------- Parsing helpers ----------


def _parse_positive_decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value.strip())
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_positive_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value.strip())
    except ValueError:
        return None
    return parsed if parsed > 0 else None


def _parse_iso_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def _pnl_text(pnl: Decimal) -> str:
    if pnl >= 0:
        return f"+${pnl:.2f}"
    return f"-${abs(pnl):.2f}"
