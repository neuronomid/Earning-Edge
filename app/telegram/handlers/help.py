"""Help handler — reachable via the ❓ Help button or /help command."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import Message

from app.telegram.handlers._common import send_text
from app.telegram.keyboards.main_menu import BTN_HELP, main_menu_keyboard

router = Router(name="help")

HELP_TEXT = (
    "<b>How Earning Edge works</b>\n\n"
    "Every Monday at 10:30 AM (in your timezone) I scan the largest companies "
    "reporting earnings the following week, score the option chain, and send you "
    "one clear setup — or a <b>No Trade</b> note if nothing looks strong enough.\n\n"
    "Use the menu below for everything:\n\n"
    "🚀 <b>Run Scan Now</b> — start a fresh scan immediately.\n"
    "📊 <b>Last Recommendation</b> — re-show the most recent setup.\n"
    "🗓 <b>Manage Schedule</b> — add, edit, pause cron jobs.\n"
    "⚙️ <b>Settings</b> — account size, risk, timezone, broker, etc.\n"
    "🔑 <b>API Keys</b> — OpenRouter, Alpaca, Alpha Vantage.\n"
    "📘 <b>Logs</b> — recent runs and the evidence behind each setup.\n\n"
    "Slash commands: /start /cancel /help.\n\n"
    "I never place trades — every recommendation is for you to review and execute "
    "in your own broker."
)


@router.message(Command("help"))
@router.message(F.text == BTN_HELP)
async def show_help(message: Message) -> None:
    await send_text(message, HELP_TEXT, reply_markup=main_menu_keyboard())
