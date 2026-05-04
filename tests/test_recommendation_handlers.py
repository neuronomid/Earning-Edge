from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.candidate import Candidate
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.user_repo import UserRepository
from app.services.recommendation_alternatives import AlternativeRecommendationResult
from app.telegram.handlers import recommendation as recommendation_handlers
from app.telegram.keyboards.settings import AltRecCB, RecCB, recommendation_keyboard
from tests.telegram_testkit import SendRecorder, make_callback, make_message

pytestmark = pytest.mark.asyncio


@pytest.fixture
def send_recorder(monkeypatch: pytest.MonkeyPatch) -> SendRecorder:
    recorder = SendRecorder()
    monkeypatch.setattr(recommendation_handlers, "send_text", recorder)
    return recorder


@pytest.fixture
def patch_session_scope(monkeypatch: pytest.MonkeyPatch, db_session: AsyncSession) -> None:
    @asynccontextmanager
    async def scope():
        try:
            yield db_session
            await db_session.commit()
        except Exception:
            await db_session.rollback()
            raise

    monkeypatch.setattr(recommendation_handlers, "session_scope", scope)


@pytest_asyncio.fixture
async def seeded_recommendation(db_session: AsyncSession) -> Recommendation:
    crypto.reset_cache()
    user = await UserRepository(db_session).add(
        User(
            telegram_chat_id="12345",
            account_size=Decimal("15000.00"),
            risk_profile="Balanced",
            broker="IBKR",
            timezone_label="ET",
            timezone_iana="America/Toronto",
            strategy_permission="long_and_short",
            max_contracts=3,
            openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
        )
    )
    run = WorkflowRun(
        user_id=user.id,
        trigger_type="manual",
        status="success",
        run_summary_json={"warning_text": "⚠️ Fixture warning"},
    )
    db_session.add(run)
    await db_session.flush()
    recommendation = Recommendation(
        user_id=user.id,
        run_id=run.id,
        ticker="AMD",
        company_name="AMD Corp.",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        suggested_entry=Decimal("1.25"),
        suggested_quantity=2,
        estimated_max_loss="$125.00 max loss per contract",
        account_risk_percent=Decimal("2.0000"),
        confidence_score=82,
        risk_level="High",
        reasoning_summary="AMD had the cleanest earnings setup in the group.",
        key_evidence_json=["Momentum held up into the week."],
        key_concerns_json=["IV crush is still a risk."],
    )
    db_session.add(recommendation)
    db_session.add(
        Candidate(
            run_id=run.id,
            ticker="AAPL",
            company_name="Apple Inc.",
            market_cap=Decimal("850"),
            earnings_date=date(2026, 5, 8),
            earnings_timing="AMC",
            current_price=Decimal("190"),
            direction_classification="bullish",
            candidate_direction_score=70,
            best_strategy="long_call",
            final_opportunity_score=66,
            data_confidence_score=84,
            selected_for_final=False,
        )
    )
    await db_session.flush()
    await db_session.commit()
    return recommendation


async def _make_recommendation(
    session: AsyncSession,
    seeded_recommendation: Recommendation,
    *,
    ticker: str,
    parent_recommendation_id=None,
    suggested_quantity: int = 2,
) -> Recommendation:
    recommendation = Recommendation(
        user_id=seeded_recommendation.user_id,
        run_id=seeded_recommendation.run_id,
        parent_recommendation_id=parent_recommendation_id,
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("110.00"),
        expiry=date(2026, 5, 16),
        suggested_entry=Decimal("1.40"),
        suggested_quantity=suggested_quantity,
        estimated_max_loss="$140.00 max loss per contract",
        account_risk_percent=Decimal("2.0000"),
        confidence_score=78,
        risk_level="High",
        reasoning_summary=f"{ticker} became the next strongest setup.",
        key_evidence_json=[f"{ticker} had supportive momentum."],
        key_concerns_json=["IV crush is still a risk."],
    )
    session.add(recommendation)
    await session.flush()
    return recommendation


def _editable_message(
    *,
    displayed_rec_id: str,
    cursor_rec_id: str,
    chat_id: int = 12345,
) -> object:
    message = make_message(chat_id=chat_id)
    message.reply_markup = recommendation_keyboard(
        displayed_rec_id,
        alternative_cursor_id=cursor_rec_id,
    )
    message.edit_reply_markup = AsyncMock()
    return message


async def test_why_button_renders_reasoning_view(
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="why", rec_id=str(seeded_recommendation.id)),
    )

    assert "<b>Why AMD</b>" in send_recorder.calls[-1].text
    assert "Momentum held up into the week." in send_recorder.calls[-1].text


async def test_bought_button_persists_feedback_event(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="bought", rec_id=str(seeded_recommendation.id)),
    )

    feedback = await FeedbackEventRepository(db_session).list_for_recommendation(
        seeded_recommendation.id
    )

    assert len(feedback) == 1
    assert feedback[0].user_action == "bought"
    assert (
        send_recorder.calls[-1].text
        == "✅ Feedback saved. I'll keep that attached to this recommendation."
    )


async def test_alternative_button_sends_full_report_and_advances_cursor(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    cursor = await _make_recommendation(
        db_session,
        seeded_recommendation,
        ticker="AAPL",
        parent_recommendation_id=seeded_recommendation.id,
    )
    next_recommendation = await _make_recommendation(
        db_session,
        seeded_recommendation,
        ticker="MSFT",
        parent_recommendation_id=cursor.id,
        suggested_quantity=0,
    )
    await db_session.commit()

    class FakeAlternativeService:
        def __init__(self, session: AsyncSession) -> None:
            del session

        async def get_next_alternative(self, *, cursor: Recommendation, user) -> AlternativeRecommendationResult:
            del user
            assert cursor.id == cursor_id
            return AlternativeRecommendationResult(
                status="recommendation",
                recommendation=next_recommendation,
                run=SimpleNamespace(run_summary_json={"warning_text": "⚠️ Fixture warning"}),
            )

    cursor_id = cursor.id
    monkeypatch.setattr(
        recommendation_handlers,
        "AlternativeRecommendationService",
        FakeAlternativeService,
    )
    message = _editable_message(
        displayed_rec_id=str(seeded_recommendation.id),
        cursor_rec_id=str(cursor.id),
    )
    callback = make_callback(chat_id=12345, message=message)

    await recommendation_handlers.recommendation_alternative(
        callback,
        AltRecCB(cursor_rec_id=str(cursor.id)),
    )

    callback.answer.assert_awaited_once_with("Assessing the next setup...")
    assert "<b>Weekly Earnings Options Signal</b>" in send_recorder.calls[-1].text
    assert "<b>Next best setup:</b> MSFT" in send_recorder.calls[-1].text
    assert "Watchlist only" in send_recorder.calls[-1].text

    sent_markup = send_recorder.calls[-1].kwargs["reply_markup"]
    sent_alt = AltRecCB.unpack(sent_markup.inline_keyboard[1][0].callback_data)
    assert sent_alt.cursor_rec_id == str(next_recommendation.id)

    message.edit_reply_markup.assert_awaited_once()
    edited_markup = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    why_button = edited_markup.inline_keyboard[0][0]
    alt_button = edited_markup.inline_keyboard[1][0]
    assert RecCB.unpack(why_button.callback_data).rec_id == str(seeded_recommendation.id)
    assert AltRecCB.unpack(alt_button.callback_data).cursor_rec_id == str(next_recommendation.id)


async def test_alternative_button_no_trade_removes_alternative_button(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    class FakeAlternativeService:
        def __init__(self, session: AsyncSession) -> None:
            del session

        async def get_next_alternative(self, *, cursor: Recommendation, user) -> AlternativeRecommendationResult:
            del cursor, user
            return AlternativeRecommendationResult(
                status="no_trade",
                outcome=SimpleNamespace(
                    decision=SimpleNamespace(
                        reasoning="Nothing else cleared the bar.",
                        watchlist_tickers=["AAPL", "MSFT"],
                    )
                ),
                run=SimpleNamespace(run_summary_json={"warning_text": "⚠️ Fixture warning"}),
            )

    monkeypatch.setattr(
        recommendation_handlers,
        "AlternativeRecommendationService",
        FakeAlternativeService,
    )
    message = _editable_message(
        displayed_rec_id=str(seeded_recommendation.id),
        cursor_rec_id=str(seeded_recommendation.id),
    )
    callback = make_callback(chat_id=12345, message=message)

    await recommendation_handlers.recommendation_alternative(
        callback,
        AltRecCB(cursor_rec_id=str(seeded_recommendation.id)),
    )

    assert "<b>Result:</b> No trade recommended." in send_recorder.calls[-1].text
    edited_markup = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    labels = [button.text for row in edited_markup.inline_keyboard for button in row]
    assert "📈 Alternatives" not in labels


async def test_alternative_button_exhausted_shows_notice_and_removes_button(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    class FakeAlternativeService:
        def __init__(self, session: AsyncSession) -> None:
            del session

        async def get_next_alternative(self, *, cursor: Recommendation, user) -> AlternativeRecommendationResult:
            del cursor, user
            return AlternativeRecommendationResult(status="exhausted")

    monkeypatch.setattr(
        recommendation_handlers,
        "AlternativeRecommendationService",
        FakeAlternativeService,
    )
    message = _editable_message(
        displayed_rec_id=str(seeded_recommendation.id),
        cursor_rec_id=str(seeded_recommendation.id),
    )
    callback = make_callback(chat_id=12345, message=message)

    await recommendation_handlers.recommendation_alternative(
        callback,
        AltRecCB(cursor_rec_id=str(seeded_recommendation.id)),
    )

    assert send_recorder.calls[-1].text == "📈 No additional stored alternatives remain for this scan."
    edited_markup = message.edit_reply_markup.await_args.kwargs["reply_markup"]
    labels = [button.text for row in edited_markup.inline_keyboard for button in row]
    assert "📈 Alternatives" not in labels
