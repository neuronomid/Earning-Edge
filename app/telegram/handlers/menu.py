"""Main-menu reply-button router.

Phase 3 wires the manual run button into the workflow runner. Other buttons
still remain placeholders until their phases land.
"""

from __future__ import annotations

from aiogram import F, Router
from aiogram.types import Message

from app.db.repositories.recommendation_repo import RecommendationRepository
from app.scheduler.jobs import RUN_ALREADY_ACTIVE_TEXT, get_workflow_runner
from app.services.user_service import UserService
from app.telegram.deps import session_scope, user_service_scope
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.main_menu import (
    BTN_LAST_RECOMMENDATION,
    BTN_RUN_SCAN,
    main_menu_keyboard,
)
from app.telegram.keyboards.settings import recommendation_keyboard
from app.telegram.templates.main_recommendation import render_main_recommendation

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
    chat_id = str(message.chat.id)
    async with user_service_scope() as (_, service):
        user = await service.get_by_chat_id(chat_id)
    if user is None:
        await send_text(
            message,
            "Looks like you haven't finished setup. Send /start to begin.",
            reply_markup=main_menu_keyboard(),
        )
        return

    result = await get_workflow_runner().run_workflow(user.id, trigger_type="manual")
    if result.outcome == "already_running":
        await send_text(
            message,
            RUN_ALREADY_ACTIVE_TEXT,
            reply_markup=main_menu_keyboard(),
        )
        return
    if result.outcome == "failed":
        await send_text(
            message,
            ("⚠️ I couldn't start that scan cleanly. " "Please try again in a minute."),
            reply_markup=main_menu_keyboard(),
        )
        return


@router.message(F.text == BTN_LAST_RECOMMENDATION)
async def last_recommendation(message: Message) -> None:
    chat_id = str(message.chat.id)
    async with session_scope() as session:
        service = UserService(session)
        user = await service.get_by_chat_id(chat_id)
        if user is None:
            await send_text(
                message,
                "Looks like you haven't finished setup. Send /start to begin.",
                reply_markup=main_menu_keyboard(),
            )
            return
        recommendations = await RecommendationRepository(session).list_recent_for_user(
            user.id,
            limit=1,
        )
    if not recommendations:
        await send_text(
            message,
            "📊 No recommendations yet. Your first scan will arrive on the next cron tick.",
            reply_markup=main_menu_keyboard(),
        )
        return
    recommendation = recommendations[0]
    await send_text(
        message,
        render_main_recommendation(
            recommendation,
            watchlist_only=recommendation.suggested_quantity == 0,
        ),
        reply_markup=recommendation_keyboard(str(recommendation.id)),
    )

# BTN_MANAGE_SCHEDULE is handled by app/telegram/handlers/schedule.py.
# BTN_API_KEYS and BTN_SETTINGS are handled by app/telegram/handlers/settings.py.
# Those routers are registered before this one so their handlers win.
