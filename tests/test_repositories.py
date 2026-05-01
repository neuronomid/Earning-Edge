from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import crypto
from app.db.models import (
    Candidate,
    CronJob,
    FeedbackEvent,
    OptionContract,
    Recommendation,
    User,
    WorkflowRun,
)
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.contract_repo import OptionContractRepository
from app.db.repositories.cron_repo import CronJobRepository
from app.db.repositories.feedback_repo import FeedbackEventRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.repositories.user_repo import UserRepository

pytestmark = pytest.mark.asyncio


async def _make_user(session: AsyncSession, telegram_chat_id: str = "tg-1") -> User:
    repo = UserRepository(session)
    user = User(
        telegram_chat_id=telegram_chat_id,
        account_size=Decimal("5000.00"),
        risk_profile="Balanced",
        broker="Wealthsimple",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=1,
        openrouter_api_key_encrypted=crypto.encrypt("sk-test-or"),
    )
    return await repo.add(user)


async def test_user_crud_and_unique_lookup(db_session: AsyncSession) -> None:
    crypto.reset_cache()
    user = await _make_user(db_session)
    await db_session.commit()

    repo = UserRepository(db_session)
    fetched = await repo.get_by_telegram_chat_id("tg-1")
    assert fetched is not None
    assert fetched.id == user.id
    assert crypto.decrypt(fetched.openrouter_api_key_encrypted) == "sk-test-or"


async def test_cron_repo_list_for_user(db_session: AsyncSession) -> None:
    user = await _make_user(db_session, telegram_chat_id="tg-cron")
    repo = CronJobRepository(db_session)
    await repo.add(
        CronJob(
            user_id=user.id,
            day_of_week="monday",
            local_time="10:30",
            timezone_label="ET",
            timezone_iana="America/Toronto",
        )
    )
    await db_session.commit()
    jobs = await repo.list_for_user(user.id)
    assert len(jobs) == 1
    assert jobs[0].day_of_week == "monday"


async def test_run_candidate_contract_recommendation_feedback_chain(
    db_session: AsyncSession,
) -> None:
    user = await _make_user(db_session, telegram_chat_id="tg-chain")

    run_repo = WorkflowRunRepository(db_session)
    run = await run_repo.add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    candidate_repo = CandidateRepository(db_session)
    candidate = await candidate_repo.add(
        Candidate(
            run_id=run.id,
            ticker="AAPL",
            company_name="Apple Inc.",
            market_cap=Decimal("3000000000000.00"),
            earnings_date=date(2026, 5, 8),
            earnings_timing="AMC",
            current_price=Decimal("190.00"),
            direction_classification="bullish",
            candidate_direction_score=72,
            best_strategy="long_call",
            final_opportunity_score=78,
            data_confidence_score=85,
        )
    )

    contract_repo = OptionContractRepository(db_session)
    await contract_repo.add(
        OptionContract(
            candidate_id=candidate.id,
            ticker="AAPL",
            option_type="call",
            position_side="long",
            strike=Decimal("195.00"),
            expiry=date(2026, 5, 16),
            bid=Decimal("1.20"),
            ask=Decimal("1.30"),
            mid=Decimal("1.25"),
            breakeven=Decimal("196.25"),
            spread_percent=Decimal("8.0000"),
            liquidity_score=70,
            contract_opportunity_score=80,
            passed_hard_filters=True,
        )
    )

    rec_repo = RecommendationRepository(db_session)
    rec = await rec_repo.add(
        Recommendation(
            user_id=user.id,
            run_id=run.id,
            ticker="AAPL",
            company_name="Apple Inc.",
            strategy="long_call",
            option_type="call",
            position_side="long",
            strike=Decimal("195.00"),
            expiry=date(2026, 5, 16),
            suggested_entry=Decimal("1.25"),
            suggested_quantity=1,
            estimated_max_loss="$125",
            account_risk_percent=Decimal("2.5000"),
            confidence_score=82,
            risk_level="moderate",
            reasoning_summary="Bullish momentum into earnings.",
            key_evidence_json={"items": ["20-day momentum +6%"]},
            key_concerns_json=["IV elevated"],
        )
    )

    feedback_repo = FeedbackEventRepository(db_session)
    await feedback_repo.add(
        FeedbackEvent(
            recommendation_id=rec.id,
            user_id=user.id,
            user_action="bought",
            entry_price=Decimal("1.25"),
        )
    )

    run.status = "success"
    run.finished_at = datetime.now(UTC)
    run.final_recommendation_id = rec.id
    run.selected_candidate_count = 1
    await db_session.commit()

    fetched_run = await run_repo.get(run.id)
    assert fetched_run is not None
    assert fetched_run.final_recommendation_id == rec.id

    runs_for_user = await run_repo.list_by_user_status(user.id, "success")
    assert len(runs_for_user) == 1

    candidates_for_run = await candidate_repo.list_for_run(run.id)
    assert len(candidates_for_run) == 1

    contracts_for_candidate = await contract_repo.list_for_candidate(candidate.id)
    assert len(contracts_for_candidate) == 1

    recent_recs = await rec_repo.list_recent_for_user(user.id)
    assert len(recent_recs) == 1
    assert recent_recs[0].key_evidence_json == {"items": ["20-day momentum +6%"]}

    feedback = await feedback_repo.list_for_recommendation(rec.id)
    assert len(feedback) == 1
    assert feedback[0].user_action == "bought"
