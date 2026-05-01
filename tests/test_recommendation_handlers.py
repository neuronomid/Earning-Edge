from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal

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
from app.telegram.handlers import recommendation as recommendation_handlers
from app.telegram.keyboards.settings import RecCB
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
