from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.recommendation_repo import RecommendationRepository
from app.pipeline.orchestrator import PipelineOrchestrator
from app.scheduler.jobs import WorkflowRunner
from app.services.run_lock import RunLockService
from tests.e2e.testkit import (
    FakeNotifier,
    FakeRedis,
    FakeScoringStep,
    FakeSizingStep,
    ScoringPlan,
    StaticCandidateStep,
    StaticMarketDataStep,
    StaticNewsStep,
    StaticOptionsStep,
    make_batch,
    make_contract,
    make_news_bundle,
    make_snapshot,
    make_user,
    sessionmaker_from,
)

pytestmark = pytest.mark.asyncio


async def test_watchlist_path_sets_zero_quantity_and_watchlist_copy(
    db_session: AsyncSession,
) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    runner = WorkflowRunner(
        sessionmaker_from(db_session),
        RunLockService(FakeRedis(), ttl_seconds=60),
        pipeline=PipelineOrchestrator(
            candidate_step=StaticCandidateStep(batch),
            market_data_step=StaticMarketDataStep(
                {record.ticker: make_snapshot(record) for record in batch.candidates}
            ),
            news_step=StaticNewsStep(
                {record.ticker: make_news_bundle(record) for record in batch.candidates}
            ),
            options_step=StaticOptionsStep(
                {
                    "AMD": (
                        make_contract(
                            "AMD",
                            option_type="call",
                            position_side="long",
                            strike="104",
                        ),
                    )
                }
            ),
            scoring_step=FakeScoringStep(
                {
                    "AMD": ScoringPlan("watchlist", 63, "bullish", 68, 65),
                    "AAPL": ScoringPlan("no_trade", 52, "neutral", 54),
                    "MSFT": ScoringPlan("no_trade", 51, "neutral", 53),
                    "NFLX": ScoringPlan("no_trade", 49, "bearish", 50),
                    "JPM": ScoringPlan("no_trade", 45, "neutral", 47),
                }
            ),
            sizing_step=FakeSizingStep(),
            notifier=notifier,
        ).run,
    )
    user = await make_user(db_session, telegram_chat_id="e2e-watchlist")
    await db_session.commit()

    result = await runner.run_workflow(user.id, trigger_type="manual")
    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)
    recommendation = recommendations[0]

    assert result.outcome == "success"
    assert recommendation.suggested_quantity == 0
    assert "watching, but not sizing yet" in notifier.calls[1].text
    assert "Watchlist only" in notifier.calls[2].text
