"""Main reply keyboard (PRD §10.2).

Persistent reply keyboard so users never have to type slash commands.
"""

from __future__ import annotations

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Button labels are constants because handlers route on exact text equality.
BTN_RUN_SCAN = "🚀 Run Scan Now"
BTN_LAST_RECOMMENDATION = "📊 Last Recommendation"
BTN_MANAGE_SCHEDULE = "🗓 Manage Schedule"
BTN_SETTINGS = "⚙️ Settings"
BTN_API_KEYS = "🔑 API Keys"
BTN_LOGS = "📘 Logs"
BTN_HELP = "❓ Help"

ALL_MAIN_MENU_BUTTONS: tuple[str, ...] = (
    BTN_RUN_SCAN,
    BTN_LAST_RECOMMENDATION,
    BTN_MANAGE_SCHEDULE,
    BTN_SETTINGS,
    BTN_API_KEYS,
    BTN_LOGS,
    BTN_HELP,
)


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_RUN_SCAN), KeyboardButton(text=BTN_LAST_RECOMMENDATION)],
            [KeyboardButton(text=BTN_MANAGE_SCHEDULE), KeyboardButton(text=BTN_LOGS)],
            [KeyboardButton(text=BTN_SETTINGS), KeyboardButton(text=BTN_API_KEYS)],
            [KeyboardButton(text=BTN_HELP)],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Pick an action…",
    )
