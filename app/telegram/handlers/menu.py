"""Main-menu reply-button router.

Each button is a placeholder until later phases land. The handlers reply with a
short status note so the UX feels alive rather than silent.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.telegram.deps import user_service_scope
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.main_menu import (
    BTN_LAST_RECOMMENDATION,
    BTN_LOGS,
    BTN_MANAGE_SCHEDULE,
    BTN_RUN_SCAN,
    main_menu_keyboard,
)

router = Router(name="menu")


async def _require_onboarded(message: Message) -> bool:
    chat_id = str(message.chat.id)
    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(chat_id)
    if user is None:
        await send_text(
            message,
            "Looks like you haven't finished setup. Send /start to begin.",
            reply_markup=main_menu_keyboard(),
        )
        return False
    return True


@router.message(F.text == BTN_RUN_SCAN)
async def run_scan_now(message: Message) -> None:
    if not await _require_onboarded(message):
        return
    await send_text(
        message,
        (
            "🧠 Got it — manual scans wire up in the next phase.\n"
            "For now your <b>Monday 10:30 AM</b> default is scheduled and saved."
        ),
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == BTN_LAST_RECOMMENDATION)
async def last_recommendation(message: Message) -> None:
    if not await _require_onboarded(message):
        return
    await send_text(
        message,
        "📊 No recommendations yet. Your first scan will arrive on the next cron tick.",
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == BTN_MANAGE_SCHEDULE)
async def manage_schedule(message: Message) -> None:
    if not await _require_onboarded(message):
        return
    await send_text(
        message,
        (
            "🗓 Schedule management UI ships in the next phase. "
            "Your default <b>Monday 10:30 AM</b> cron is already saved."
        ),
        reply_markup=main_menu_keyboard(),
    )


@router.message(F.text == BTN_LOGS)
async def show_logs(message: Message) -> None:
    if not await _require_onboarded(message):
        return
    await send_text(
        message,
        "📘 The logs view ships once the first scan has run.",
        reply_markup=main_menu_keyboard(),
    )


# BTN_API_KEYS and BTN_SETTINGS are handled by app/telegram/handlers/settings.py.
# That router is registered before this one so its handlers win.
