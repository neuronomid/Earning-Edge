"""Main-menu reply-button router.

Phase 3 wires the manual run button into the workflow runner. Other buttons
still remain placeholders until their phases land.
"""

from __future__ import annotations

from datetime import date

from aiogram import F, Router
from aiogram.types import Message

from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.scheduler.jobs import RUN_ALREADY_ACTIVE_TEXT, get_workflow_runner
from app.services.positions.quotes import fetch_bid_ask
from app.services.user_service import UserService
from app.telegram.deps import session_scope, user_service_scope
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.main_menu import (
    BTN_LAST_RECOMMENDATION,
    BTN_POSITIONS,
    BTN_RUN_SCAN,
    main_menu_keyboard,
)
from app.telegram.keyboards.settings import position_list_keyboard, recommendation_keyboard
from app.telegram.templates.main_recommendation import render_main_recommendation
from app.telegram.templates.positions import render_position_card

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
            ("⚠️ I couldn't start that scan cleanly. Please try again in a minute."),
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
        rank_position = 1
        if recommendations:
            run_recommendations = await RecommendationRepository(session).list_for_run(
                recommendations[0].run_id
            )
            rank_position = _recommendation_rank(
                run_recommendations,
                recommendation_id=recommendations[0].id,
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
            rank_position=rank_position,
            watchlist_only=recommendation.suggested_quantity == 0,
        ),
        reply_markup=recommendation_keyboard(str(recommendation.id)),
    )


@router.message(F.text == BTN_POSITIONS)
async def show_positions(message: Message) -> None:
    chat_id = str(message.chat.id)
    today = date.today()
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
        await repo.expire_past_due_for_user(user.id, today)
        rows = await repo.list_active_with_recommendations_for_user(user.id)
        await session.commit()

    if not rows:
        await send_text(
            message,
            "📂 No active positions.",
            reply_markup=main_menu_keyboard(),
        )
        return

    for position, recommendation in rows:
        quote = await fetch_bid_ask(user=user, recommendation=recommendation, today=today)
        await send_text(
            message,
            render_position_card(position, recommendation, quote),
            reply_markup=position_list_keyboard(str(position.id)),
        )


# BTN_MANAGE_SCHEDULE is handled by app/telegram/handlers/schedule.py.
# BTN_API_KEYS and BTN_SETTINGS are handled by app/telegram/handlers/settings.py.
# Those routers are registered before this one so their handlers win.


def _recommendation_rank(recommendations, *, recommendation_id) -> int:
    for index, recommendation in enumerate(recommendations, start=1):
        if recommendation.id == recommendation_id:
            return index
    return 1
