from __future__ import annotations

from uuid import UUID

from aiogram import Router
from aiogram.types import CallbackQuery

from app.db.models.feedback_event import FeedbackEvent
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.services.user_service import UserService
from app.telegram.deps import session_scope
from app.telegram.handlers._common import send_text
from app.telegram.keyboards.settings import RecCB

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
        if callback_data.action == "alts":
            candidates = await CandidateRepository(session).list_for_run(recommendation.run_id)
            await callback.answer()
            await send_text(
                callback.message,
                _render_alternatives(recommendation.ticker, candidates),
            )
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


def _render_alternatives(selected_ticker: str, candidates) -> str:
    ranked = sorted(
        (candidate for candidate in candidates if candidate.ticker != selected_ticker),
        key=lambda candidate: candidate.final_opportunity_score,
        reverse=True,
    )
    lines = ["📈 <b>Alternatives</b>", ""]
    if not ranked:
        lines.append("No additional ranked candidates were stored for this run.")
        return "\n".join(lines)

    for index, candidate in enumerate(ranked[:3], start=1):
        lines.append(
            f"{index}. {candidate.ticker} — {candidate.direction_classification} — "
            f"{candidate.final_opportunity_score}/100"
        )
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
