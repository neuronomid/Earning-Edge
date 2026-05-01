"""Generic confirmation/skip/back keyboards used during onboarding & settings."""

from __future__ import annotations

from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


class ConfirmCB(CallbackData, prefix="confirm"):
    action: str  # "yes" | "no"


class ChoiceCB(CallbackData, prefix="choice"):
    group: str
    value: str


def confirm_keyboard(yes_label: str = "✅ Confirm", no_label: str = "✏️ Edit") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=yes_label, callback_data=ConfirmCB(action="yes").pack()),
                InlineKeyboardButton(text=no_label, callback_data=ConfirmCB(action="no").pack()),
            ]
        ]
    )


def choice_keyboard(group: str, options: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Inline keyboard for a single-pick set of options (label, value)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=ChoiceCB(group=group, value=value).pack())]
            for label, value in options
        ]
    )


SKIP_BTN = "⏭ Skip"
CANCEL_BTN = "✖️ Cancel"


def skip_or_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=SKIP_BTN), KeyboardButton(text=CANCEL_BTN)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_BTN)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )
