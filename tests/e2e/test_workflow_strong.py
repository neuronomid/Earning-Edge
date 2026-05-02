from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.pipeline.orchestrator import PipelineOrchestrator
from app.scheduler.jobs import WorkflowRunner
from app.services.logging_service import LoggingService
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


def _strong_orchestrator(*, batch, notifier: FakeNotifier, archive_root) -> PipelineOrchestrator:
    return PipelineOrchestrator(
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
                    make_contract("AMD", option_type="call", position_side="long", strike="104"),
                    make_contract("AMD", option_type="call", position_side="long", strike="108"),
                ),
                "AAPL": (
                    make_contract("AAPL", option_type="call", position_side="long", strike="195"),
                ),
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan(
                    action="recommend",
                    final_score=82,
                    direction="bullish",
                    direction_score=80,
                    contract_score=84,
                    reasoning=("AMD had the strongest momentum and the cleanest contract.",),
                ),
                "AAPL": ScoringPlan("watchlist", 64, "bullish", 70, 66),
                "MSFT": ScoringPlan("no_trade", 55, "neutral", 52),
                "NFLX": ScoringPlan("no_trade", 48, "bearish", 50),
                "JPM": ScoringPlan("no_trade", 44, "neutral", 46),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
        logging_service=LoggingService(archive_root=archive_root),
    )


async def test_manual_workflow_acceptance_persists_card_and_messages(
    db_session: AsyncSession,
    tmp_path,
) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    runner = WorkflowRunner(
        sessionmaker_from(db_session),
        RunLockService(FakeRedis(), ttl_seconds=60),
        pipeline=_strong_orchestrator(
            batch=batch,
            notifier=notifier,
            archive_root=tmp_path / "runs",
        ).run,
    )
    user = await make_user(db_session, telegram_chat_id="e2e-strong")
    await db_session.commit()

    result = await runner.run_workflow(user.id, trigger_type="manual")

    assert result.outcome == "success"
    assert result.run_id is not None

    runs = await WorkflowRunRepository(db_session).list_recent_for_user(user.id)
    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)
    run = runs[0]
    recommendation = recommendations[0]

    assert run.status == "success"
    assert run.final_recommendation_id == recommendation.id
    assert run.recommendation_card_json is not None
    assert run.recommendation_card_json["selected_ticker"] == "AMD"
    assert run.run_summary_json is not None
    assert run.run_summary_json["contracts_considered_count"] == 3
    assert run.telegram_message_text == notifier.calls[2].text
    assert recommendation.ticker == "AMD"
    assert recommendation.strategy == "long_call"
    assert notifier.calls[0].text == "🧠 Starting a fresh earnings-options scan now."
    assert notifier.calls[1].text == "✅ Scan complete. Here is the strongest setup I found."
    assert "<b>Weekly Earnings Options Signal</b>" in notifier.calls[2].text
    assert notifier.calls[2].reply_markup is not None
    assert (tmp_path / "runs" / str(result.run_id) / "recommendation_card.json").exists()


async def test_multiple_users_are_isolated_across_runs(db_session: AsyncSession, tmp_path) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    runner = WorkflowRunner(
        sessionmaker_from(db_session),
        RunLockService(FakeRedis(), ttl_seconds=60),
        pipeline=_strong_orchestrator(
            batch=batch,
            notifier=notifier,
            archive_root=tmp_path / "runs",
        ).run,
    )
    first_user = await make_user(db_session, telegram_chat_id="e2e-user-1")
    second_user = await make_user(db_session, telegram_chat_id="e2e-user-2")
    await db_session.commit()

    first = await runner.run_workflow(first_user.id, trigger_type="manual")
    second = await runner.run_workflow(second_user.id, trigger_type="manual")

    assert first.outcome == "success"
    assert second.outcome == "success"

    first_runs = await WorkflowRunRepository(db_session).list_recent_for_user(first_user.id)
    second_runs = await WorkflowRunRepository(db_session).list_recent_for_user(second_user.id)
    first_recs = await RecommendationRepository(db_session).list_recent_for_user(first_user.id)
    second_recs = await RecommendationRepository(db_session).list_recent_for_user(second_user.id)

    assert len(first_runs) == 1
    assert len(second_runs) == 1
    assert len(first_recs) == 1
    assert len(second_recs) == 1
    assert first_recs[0].user_id == first_user.id
    assert second_recs[0].user_id == second_user.id

    first_messages = [call for call in notifier.calls if call.chat_id == "e2e-user-1"]
    second_messages = [call for call in notifier.calls if call.chat_id == "e2e-user-2"]
    assert len(first_messages) == 3
    assert len(second_messages) == 3
    assert all("AMD" in call.text or "scan" in call.text.lower() for call in first_messages)
    assert all("AMD" in call.text or "scan" in call.text.lower() for call in second_messages)
