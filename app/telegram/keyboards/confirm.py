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
    action: str  # "yes" | "no" | "cancel"


class ChoiceCB(CallbackData, prefix="choice"):
    group: str
    value: str


SKIP_BTN = "⏭ Skip"
CANCEL_BTN = "✖️ Cancel"
CHOICE_CANCEL_VALUE = "__cancel__"


def confirm_keyboard(
    yes_label: str = "✅ Confirm",
    no_label: str = "✏️ Edit",
    *,
    cancel_label: str | None = None,
) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=yes_label, callback_data=ConfirmCB(action="yes").pack()),
        InlineKeyboardButton(text=no_label, callback_data=ConfirmCB(action="no").pack()),
    ]
    rows = [row]
    if cancel_label is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cancel_label,
                    callback_data=ConfirmCB(action="cancel").pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def choice_keyboard(
    group: str,
    options: list[tuple[str, str]],
    *,
    cancel_label: str | None = CANCEL_BTN,
) -> InlineKeyboardMarkup:
    """Inline keyboard for a single-pick set of options (label, value)."""
    rows = [
        [InlineKeyboardButton(text=label, callback_data=ChoiceCB(group=group, value=value).pack())]
        for label, value in options
    ]
    if cancel_label is not None:
        rows.append(
            [
                InlineKeyboardButton(
                    text=cancel_label,
                    callback_data=ChoiceCB(group=group, value=CHOICE_CANCEL_VALUE).pack(),
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
