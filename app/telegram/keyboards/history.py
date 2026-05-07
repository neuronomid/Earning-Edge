from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


class HistCB(CallbackData, prefix="hist"):
    action: str  # mod_open, mod_entry, mod_exit, mod_qty, mod_edate, mod_xdate, del, del_ok, del_no
    position_id: str


def history_card_keyboard(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✏️ Modify",
                    callback_data=HistCB(action="mod_open", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="🗑 Delete",
                    callback_data=HistCB(action="del", position_id=position_id).pack(),
                ),
            ]
        ]
    )


def history_modify_keyboard(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Entry Price",
                    callback_data=HistCB(action="mod_entry", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="Exit Price",
                    callback_data=HistCB(action="mod_exit", position_id=position_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Contracts",
                    callback_data=HistCB(action="mod_qty", position_id=position_id).pack(),
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Entry Date",
                    callback_data=HistCB(action="mod_edate", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="Exit Date",
                    callback_data=HistCB(action="mod_xdate", position_id=position_id).pack(),
                ),
            ],
        ]
    )


def history_delete_confirm_keyboard(position_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Confirm Delete",
                    callback_data=HistCB(action="del_ok", position_id=position_id).pack(),
                ),
                InlineKeyboardButton(
                    text="✖ Cancel",
                    callback_data=HistCB(action="del_no", position_id=position_id).pack(),
                ),
            ]
        ]
    )
