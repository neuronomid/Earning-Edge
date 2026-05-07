from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from aiogram.exceptions import TelegramBadRequest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models.candidate import Candidate
from app.db.models.option_contract import OptionContract
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.user_repo import UserRepository
from app.services.alternative_recommendation_service import AlternativeRecommendationResult
from app.telegram.handlers import recommendation as recommendation_handlers
from app.telegram.keyboards.settings import AltRecCB, RecCB, recommendation_keyboard
from tests.telegram_testkit import SendRecorder, make_callback, make_message, make_state

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
    aapl = Candidate(
        run_id=run.id,
        ticker="AAPL",
        company_name="Apple Inc.",
        market_cap=Decimal("850"),
        earnings_date=date(2026, 5, 8),
        earnings_timing="AMC",
        current_price=Decimal("190"),
        direction_classification="bullish",
        candidate_direction_score=76,
        best_strategy="long_call",
        final_opportunity_score=72,
        data_confidence_score=84,
        selected_for_final=False,
        strategy_source="catalyst_confluence",
    )
    db_session.add(aapl)
    await db_session.flush()
    db_session.add(
        OptionContract(
            candidate_id=aapl.id,
            ticker="AAPL",
            option_type="call",
            position_side="long",
            strike=Decimal("195.00"),
            expiry=date(2026, 5, 16),
            bid=Decimal("1.10"),
            ask=Decimal("1.25"),
            mid=Decimal("1.175"),
            volume=120,
            open_interest=300,
            implied_volatility=Decimal("0.44"),
            delta=Decimal("0.52"),
            breakeven=Decimal("196.25"),
            spread_percent=Decimal("12.7600"),
            liquidity_score=82,
            contract_opportunity_score=74,
            passed_hard_filters=True,
            rejection_reason=None,
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


async def test_bought_button_starts_fill_capture(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    state, _ = await make_state(chat_id=12345)

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="bought", rec_id=str(seeded_recommendation.id)),
        state,
    )

    feedback = await FeedbackEventRepository(db_session).list_for_recommendation(
        seeded_recommendation.id
    )

    assert feedback == []
    assert send_recorder.calls[-1].text == "What was your fill price per contract?"
    assert await state.get_state() == "BoughtPositionStates:entry_price"


async def test_bought_fill_flow_creates_open_position_and_feedback(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    state, _ = await make_state(chat_id=12345)
    await state.set_state(recommendation_handlers.BoughtPositionStates.entry_price)
    await state.update_data(
        bought_recommendation_id=str(seeded_recommendation.id),
        default_quantity=seeded_recommendation.suggested_quantity,
    )

    await recommendation_handlers.capture_entry_price(
        make_message("1.35", chat_id=12345),
        state,
    )
    await recommendation_handlers.capture_entry_quantity(
        make_message("2", chat_id=12345),
        state,
    )

    feedback = await FeedbackEventRepository(db_session).list_for_recommendation(
        seeded_recommendation.id
    )
    position = await OpenPositionRepository(db_session).get_active_for_recommendation(
        seeded_recommendation.id
    )

    assert len(feedback) == 1
    assert feedback[0].user_action == "bought"
    assert feedback[0].entry_price == Decimal("1.3500")
    assert position is not None
    assert position.entry_price == Decimal("1.3500")
    assert position.entry_quantity == 2
    assert send_recorder.calls[-1].text.startswith("Tracking this position.")
    assert await state.get_state() is None


async def test_alternative_button_sends_next_full_recommendation(
    db_session: AsyncSession,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="alts", rec_id=str(seeded_recommendation.id)),
    )

    assert "<b>Weekly Earnings Options Signal</b>" in send_recorder.calls[-1].text
    assert "<b>2nd best setup:</b> 🥈 AAPL" in send_recorder.calls[-1].text
    assert send_recorder.calls[-1].kwargs["reply_markup"] is not None
    assert callback.answer.await_count == 1

    recommendations = await RecommendationRepository(db_session).list_for_run(
        seeded_recommendation.run_id
    )
    assert [recommendation.ticker for recommendation in recommendations] == ["AMD", "AAPL"]


async def test_alternative_button_answers_callback_before_building_result(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    events: list[str] = []

    async def answer_side_effect(*args, **kwargs) -> None:
        del args, kwargs
        events.append("answered")

    callback.answer.side_effect = answer_side_effect

    class StubAlternativeRecommendationService:
        def __init__(self, session) -> None:
            self.session = session

        async def build_next(
            self,
            *,
            user,
            current_recommendation,
        ) -> AlternativeRecommendationResult:
            del user, current_recommendation
            events.append("build")
            return AlternativeRecommendationResult(
                recommendation=None,
                message="No additional qualified alternatives are available for this run.",
            )

    monkeypatch.setattr(
        recommendation_handlers,
        "AlternativeRecommendationService",
        StubAlternativeRecommendationService,
    )

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="alts", rec_id=str(seeded_recommendation.id)),
    )

    assert events[:2] == ["answered", "build"]
    assert (
        send_recorder.calls[-1].text
        == "No additional qualified alternatives are available for this run."
    )


async def test_alternative_button_still_sends_message_when_callback_query_has_expired(
    monkeypatch: pytest.MonkeyPatch,
    send_recorder: SendRecorder,
    patch_session_scope: None,
    seeded_recommendation: Recommendation,
) -> None:
    callback = make_callback(chat_id=12345, message=make_message(chat_id=12345))
    callback.answer.side_effect = TelegramBadRequest(
        method=SimpleNamespace(),
        message="query is too old and response timeout expired or query ID is invalid",
    )

    class StubAlternativeRecommendationService:
        def __init__(self, session) -> None:
            self.session = session

        async def build_next(
            self,
            *,
            user,
            current_recommendation,
        ) -> AlternativeRecommendationResult:
            del user, current_recommendation
            return AlternativeRecommendationResult(
                recommendation=None,
                message="No additional qualified alternatives are available for this run.",
            )

    monkeypatch.setattr(
        recommendation_handlers,
        "AlternativeRecommendationService",
        StubAlternativeRecommendationService,
    )

    await recommendation_handlers.recommendation_action(
        callback,
        RecCB(action="alts", rec_id=str(seeded_recommendation.id)),
    )

    assert (
        send_recorder.calls[-1].text
        == "No additional qualified alternatives are available for this run."
    )
