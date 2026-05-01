from __future__ import annotations

from math import ceil

from aiogram import F, Router
from aiogram.filters.callback_data import CallbackData
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.run_repo import WorkflowRunRepository
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.handlers._common import enforce_tone, send_text
from app.telegram.keyboards.main_menu import BTN_LOGS

PAGE_SIZE = 5

router = Router(name="logs")


class LogsCB(CallbackData, prefix="logs"):
    page: int


@router.message(F.text == BTN_LOGS)
async def show_logs(message: Message) -> None:
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(message.chat.id))
        if user is None:
            await send_text(message, "Finish setup first with /start.")
            return
        total_runs = await WorkflowRunRepository(session).count_for_user(user.id)
        if total_runs == 0:
            await send_text(
                message,
                "📘 No logged runs yet. Your first completed scan will populate this view.",
            )
            return
        runs = await WorkflowRunRepository(session).list_recent_for_user(
            user.id,
            limit=PAGE_SIZE,
            offset=0,
        )
    await send_text(
        message,
        _render_page(runs, page=0, total_runs=total_runs),
        reply_markup=_pagination_keyboard(page=0, total_runs=total_runs),
    )


@router.callback_query(LogsCB.filter())
async def logs_page(callback: CallbackQuery, callback_data: LogsCB) -> None:
    if callback.message is None:
        await callback.answer()
        return
    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return
        total_runs = await WorkflowRunRepository(session).count_for_user(user.id)
        if total_runs == 0:
            await callback.answer("No runs yet.")
            return
        max_page = max(0, ceil(total_runs / PAGE_SIZE) - 1)
        page = max(0, min(callback_data.page, max_page))
        runs = await WorkflowRunRepository(session).list_recent_for_user(
            user.id,
            limit=PAGE_SIZE,
            offset=page * PAGE_SIZE,
        )
    await callback.answer()
    text = _render_page(runs, page=page, total_runs=total_runs)
    enforce_tone(text)
    await callback.message.edit_text(
        text,
        reply_markup=_pagination_keyboard(page=page, total_runs=total_runs),
    )


def _render_page(runs: list[WorkflowRun], *, page: int, total_runs: int) -> str:
    total_pages = max(1, ceil(total_runs / PAGE_SIZE))
    lines = [f"📘 <b>Recent Runs</b> ({page + 1}/{total_pages})", ""]
    base_index = page * PAGE_SIZE
    for offset, run in enumerate(runs, start=1):
        card = run.recommendation_card_json or {}
        summary = run.run_summary_json or {}
        ticker = card.get("selected_ticker") or "No trade"
        strategy = card.get("selected_strategy") or _status_label(run.status)
        confidence = card.get("confidence_score")
        data_confidence = card.get("data_confidence")
        reasoning = str(card.get("decision_reasoning") or "No reasoning snapshot was stored.")
        stamp = summary.get("finished_at") or summary.get("started_at") or "unknown"
        lines.append(
            f"{base_index + offset}. {stamp} | {run.trigger_type} | {_status_label(run.status)}"
        )
        lines.append(f"{ticker} | {strategy}")
        if confidence is not None:
            line = f"Confidence {confidence}/100"
            if data_confidence is not None:
                line += f" | Data {data_confidence}/100"
            lines.append(line)
        lines.append(reasoning)
        warning = summary.get("warning_text")
        if warning:
            lines.append(f"Warning: {warning}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _pagination_keyboard(*, page: int, total_runs: int) -> InlineKeyboardMarkup:
    total_pages = max(1, ceil(total_runs / PAGE_SIZE))
    buttons: list[InlineKeyboardButton] = []
    if page > 0:
        buttons.append(
            InlineKeyboardButton(
                text="⬅️ Newer",
                callback_data=LogsCB(page=page - 1).pack(),
            )
        )
    if page + 1 < total_pages:
        buttons.append(
            InlineKeyboardButton(
                text="Older ➡️",
                callback_data=LogsCB(page=page + 1).pack(),
            )
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])


def _status_label(status: str) -> str:
    if status == "no_trade":
        return "No Trade"
    return status.replace("_", " ").title()
