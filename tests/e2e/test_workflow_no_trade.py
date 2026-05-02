from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.steps.scoring import CandidateScoringStep
from tests.e2e.testkit import (
    FakeNotifier,
    StaticCandidateStep,
    StaticMarketDataStep,
    StaticNewsStep,
    StaticOptionsStep,
    make_batch,
    make_contract,
    make_news_bundle,
    make_snapshot,
    make_user,
)

pytestmark = pytest.mark.asyncio


async def test_critical_missing_field_returns_specific_no_trade_reason(
    db_session: AsyncSession,
) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=StaticCandidateStep(batch),
        market_data_step=StaticMarketDataStep(
            {
                record.ticker: make_snapshot(record, current_price=None)
                for record in batch.candidates
            }
        ),
        news_step=StaticNewsStep(
            {record.ticker: make_news_bundle(record) for record in batch.candidates}
        ),
        options_step=StaticOptionsStep(
            {
                record.ticker: (
                    make_contract(
                        record.ticker,
                        option_type="call",
                        position_side="long",
                        strike=str(record.current_price),
                    ),
                )
                for record in batch.candidates
            }
        ),
        scoring_step=CandidateScoringStep(),
        notifier=notifier,
    )
    user = await make_user(db_session, telegram_chat_id="e2e-no-trade")
    run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)

    assert outcome.decision.action == "no_trade"
    assert outcome.decision.reasoning == "Current price is unavailable."
    assert run.status == "no_trade"
    assert recommendations == []
    assert "Current price is unavailable." in notifier.calls[2].text
    assert "1. AMD" in notifier.calls[2].text
