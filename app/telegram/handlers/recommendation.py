from __future__ import annotations

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from app.db.models.feedback_event import FeedbackEvent
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.recommendation_alternatives import AlternativeRecommendationService
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.settings import AltRecCB, RecCB, recommendation_keyboard
from app.telegram.templates.main_recommendation import render_main_recommendation
from app.telegram.templates.no_trade import render_no_trade

router = Router(name="recommendation")


@router.callback_query(RecCB.filter())
async def recommendation_action(callback: CallbackQuery, callback_data: RecCB) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return

        recommendation = await RecommendationRepository(session).get(UUID(callback_data.rec_id))
        if recommendation is None or recommendation.user_id != user.id:
            await callback.answer("That recommendation is unavailable.")
            return

        if callback_data.action == "why":
            await callback.answer()
            await send_text(callback.message, _render_why(recommendation))
            return
        if callback_data.action == "risk":
            await callback.answer()
            await send_text(callback.message, _render_risk(recommendation))
            return
        if callback_data.action == "save_note":
            await callback.answer()
            await send_text(callback.message, _render_note(recommendation))
            return
        if callback_data.action in {"bought", "skipped"}:
            await FeedbackEventRepository(session).add(
                FeedbackEvent(
                    recommendation_id=recommendation.id,
                    user_id=user.id,
                    user_action="bought" if callback_data.action == "bought" else "skipped",
                )
            )
            await callback.answer("Saved")
            await send_text(
                callback.message,
                "✅ Feedback saved. I'll keep that attached to this recommendation.",
            )
            return

    await callback.answer()


@router.callback_query(AltRecCB.filter())
async def recommendation_alternative(callback: CallbackQuery, callback_data: AltRecCB) -> None:
    if callback.message is None:
        await callback.answer()
        return

    async with session_scope() as session:
        user = await UserService(session).get_by_chat_id(str(callback.from_user.id))
        if user is None:
            await callback.answer("Finish setup first.")
            return

        cursor = await RecommendationRepository(session).get(UUID(callback_data.cursor_rec_id))
        if cursor is None or cursor.user_id != user.id:
            await callback.answer("That recommendation is unavailable.")
            return

        await callback.answer("Assessing the next setup...")
        displayed_recommendation_id = _displayed_recommendation_id(callback) or str(cursor.id)

        service = AlternativeRecommendationService(session)
        result = await service.get_next_alternative(cursor=cursor, user=user)

        if result.status == "recommendation":
            assert result.recommendation is not None
            warning_text = _warning_text(result.run)
            watchlist_only = result.recommendation.suggested_quantity == 0
            next_cursor_id = str(result.recommendation.id)
            await send_text(
                callback.message,
                render_main_recommendation(
                    result.recommendation,
                    warning_text=warning_text,
                    watchlist_only=watchlist_only,
                    setup_label="Next best setup",
                ),
                reply_markup=recommendation_keyboard(next_cursor_id),
            )
            await _edit_alternative_cursor(
                callback,
                displayed_recommendation_id=displayed_recommendation_id,
                next_cursor_id=next_cursor_id,
            )
            return

        if result.status == "no_trade":
            assert result.outcome is not None
            warning_text = _warning_text(result.run)
            await send_text(
                callback.message,
                render_no_trade(
                    reason=result.outcome.decision.reasoning,
                    watchlist_tickers=result.outcome.decision.watchlist_tickers,
                    warning_text=warning_text,
                ),
            )
            await _edit_alternative_cursor(
                callback,
                displayed_recommendation_id=displayed_recommendation_id,
                next_cursor_id=None,
            )
            return

        await send_text(
            callback.message,
            "📈 No additional stored alternatives remain for this scan.",
        )
        await _edit_alternative_cursor(
            callback,
            displayed_recommendation_id=displayed_recommendation_id,
            next_cursor_id=None,
        )


def _render_why(recommendation) -> str:
    evidence = _normalize_string_list(recommendation.key_evidence_json)
    concerns = _normalize_string_list(recommendation.key_concerns_json)

    lines = [
        f"🔍 <b>Why {recommendation.ticker}</b>",
        "",
        recommendation.reasoning_summary,
    ]
    if evidence:
        lines.extend(["", "<b>Key evidence</b>"])
        lines.extend(f"• {item}" for item in evidence[:4])
    if concerns:
        lines.extend(["", "<b>Main concerns</b>"])
        lines.extend(f"• {item}" for item in concerns[:3])
    return "\n".join(lines)


def _render_risk(recommendation) -> str:
    lines = [
        f"⚖️ <b>Risk / Sizing for {recommendation.ticker}</b>",
        "",
        (
            "Contract: "
            f"{recommendation.position_side.capitalize()} "
            f"{recommendation.option_type.capitalize()}"
        ),
        f"Strike: ${recommendation.strike}",
        f"Expiry: {recommendation.expiry.isoformat()}",
        f"Suggested quantity: {recommendation.suggested_quantity} contract(s)",
        f"Stored sizing note: {recommendation.estimated_max_loss}",
        f"Account risk: {recommendation.account_risk_percent}%",
    ]
    return "\n".join(lines)


def _render_note(recommendation) -> str:
    return (
        f"📘 <b>Saved Note for {recommendation.ticker}</b>\n\n"
        f"{recommendation.reasoning_summary}\n\n"
        f"Confidence: {recommendation.confidence_score}/100"
    )


def _normalize_string_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [str(item) for item in items]
    return []


async def _edit_alternative_cursor(
    callback: CallbackQuery,
    *,
    displayed_recommendation_id: str,
    next_cursor_id: str | None,
) -> None:
    if callback.message is None or not hasattr(callback.message, "edit_reply_markup"):
        return
    await callback.message.edit_reply_markup(
        reply_markup=recommendation_keyboard(
            displayed_recommendation_id,
            alternative_cursor_id=next_cursor_id,
            include_alternative=next_cursor_id is not None,
        )
    )


def _warning_text(run) -> str | None:
    if run is None or not isinstance(run.run_summary_json, dict):
        return None
    value = run.run_summary_json.get("warning_text")
    return None if value is None else str(value)


def _displayed_recommendation_id(callback: CallbackQuery) -> str | None:
    if callback.message is None:
        return None
    markup = getattr(callback.message, "reply_markup", None)
    rows = getattr(markup, "inline_keyboard", None)
    if not isinstance(rows, list):
        return None
    for row in rows:
        if not isinstance(row, list):
            continue
        for button in row:
            packed = getattr(button, "callback_data", None)
            if not isinstance(packed, str):
                continue
            try:
                parsed = RecCB.unpack(packed)
            except (TypeError, ValueError):
                continue
            return parsed.rec_id
    return None
