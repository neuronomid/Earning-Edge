from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.llm.types import LLMAuthenticationError
from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.steps.scoring import CandidateScoringStep
from app.services.candidate_service import TRADINGVIEW_FALLBACK_WARNING
from tests.e2e.testkit import (
    FakeNotifier,
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
)

pytestmark = pytest.mark.asyncio


async def test_tradingview_failure_warning_surfaces_in_message_and_logs(
    db_session: AsyncSession,
) -> None:
    batch = make_batch(
        tradingview_status="failed",
        fallback_used=True,
        warning_text=TRADINGVIEW_FALLBACK_WARNING,
    )
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
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
                )
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("recommend", 82, "bullish", 80, 84),
                "AAPL": ScoringPlan("no_trade", 52, "neutral", 54),
                "MSFT": ScoringPlan("no_trade", 51, "neutral", 53),
                "NFLX": ScoringPlan("no_trade", 49, "bearish", 50),
                "JPM": ScoringPlan("no_trade", 45, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
    )
    user = await make_user(db_session, telegram_chat_id="e2e-tradingview-fallback")
    run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    await orchestrator.run(db_session, run)
    await db_session.commit()

    assert run.tradingview_status == "failed"
    assert run.run_summary_json is not None
    assert run.run_summary_json["warning_text"] == TRADINGVIEW_FALLBACK_WARNING
    assert run.telegram_message_text is not None
    assert TRADINGVIEW_FALLBACK_WARNING in run.telegram_message_text


async def test_invalid_openrouter_key_blocks_recommendation(db_session: AsyncSession) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=StaticCandidateStep(batch),
        market_data_step=StaticMarketDataStep(
            {record.ticker: make_snapshot(record) for record in batch.candidates}
        ),
        news_step=StaticNewsStep(
            {
                record.ticker: LLMAuthenticationError("OpenRouter rejected the API key.")
                for record in batch.candidates
            }
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
    user = await make_user(
        db_session,
        telegram_chat_id="e2e-bad-openrouter",
        openrouter_api_key="sk-or-bad",
    )
    run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendations = await RecommendationRepository(db_session).list_recent_for_user(user.id)

    assert outcome.decision.action == "no_trade"
    assert outcome.decision.reasoning == "OpenRouter API key is unavailable or invalid."
    assert run.status == "no_trade"
    assert recommendations == []
    assert "OpenRouter API key is unavailable or invalid." in notifier.calls[2].text


async def test_missing_option_chain_returns_no_trade_without_invented_contracts(
    db_session: AsyncSession,
) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    orchestrator = PipelineOrchestrator(
        candidate_step=StaticCandidateStep(batch),
        market_data_step=StaticMarketDataStep(
            {record.ticker: make_snapshot(record) for record in batch.candidates}
        ),
        news_step=StaticNewsStep(
            {record.ticker: make_news_bundle(record) for record in batch.candidates}
        ),
        options_step=StaticOptionsStep(
            {
                record.ticker: RuntimeError("Alpaca and yfinance both returned no usable chain.")
                for record in batch.candidates
            }
        ),
        scoring_step=CandidateScoringStep(),
        notifier=notifier,
    )
    user = await make_user(db_session, telegram_chat_id="e2e-missing-chain")
    run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    outcome = await orchestrator.run(db_session, run)
    await db_session.commit()

    assert outcome.decision.action == "no_trade"
    assert outcome.decision.reasoning == "No usable option contract was selected."
    assert run.option_contracts_json == []
    assert "No usable option contract was selected." in notifier.calls[2].text


async def test_yfinance_option_fallback_lowers_data_confidence(
    db_session: AsyncSession,
) -> None:
    batch = make_batch()
    base_maps = {
        record.ticker: make_snapshot(
            record,
            one_day="0.02",
            five_day="0.08",
            twenty_day="0.12",
            fifty_day="0.16",
            volume_ratio="1.25",
            relative_strength_vs_spy="0.05",
            relative_strength_vs_qqq="0.04",
            relative_strength_vs_sector="0.03",
            sector_five_day="0.03",
        )
        for record in batch.candidates
    }
    news_maps = {
        record.ticker: make_news_bundle(
            record,
            bullish=("Strong demand trend remained intact.", "Estimate revisions stayed firm."),
            news_confidence=78,
        )
        for record in batch.candidates
    }
    baseline = PipelineOrchestrator(
        candidate_step=StaticCandidateStep(batch),
        market_data_step=StaticMarketDataStep(base_maps),
        news_step=StaticNewsStep(news_maps),
        options_step=StaticOptionsStep(
            {
                "AMD": (
                    make_contract(
                        "AMD",
                        option_type="call",
                        position_side="long",
                        strike="104",
                        source="fixture",
                    ),
                )
            }
        ),
        scoring_step=CandidateScoringStep(),
        notifier=FakeNotifier(),
    )
    fallback = PipelineOrchestrator(
        candidate_step=StaticCandidateStep(batch),
        market_data_step=StaticMarketDataStep(base_maps),
        news_step=StaticNewsStep(news_maps),
        options_step=StaticOptionsStep(
            {
                "AMD": (
                    make_contract(
                        "AMD",
                        option_type="call",
                        position_side="long",
                        strike="104",
                        source="yfinance",
                    ),
                )
            }
        ),
        scoring_step=CandidateScoringStep(),
        notifier=FakeNotifier(),
    )
    baseline_user = await make_user(db_session, telegram_chat_id="e2e-yf-baseline")
    fallback_user = await make_user(db_session, telegram_chat_id="e2e-yf-fallback")
    baseline_run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=baseline_user.id, trigger_type="manual", status="running")
    )
    fallback_run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=fallback_user.id, trigger_type="manual", status="running")
    )

    baseline_outcome = await baseline.run(db_session, baseline_run)
    fallback_outcome = await fallback.run(db_session, fallback_run)

    assert baseline_outcome.selected is not None
    assert fallback_outcome.selected is not None
    assert (
        fallback_outcome.selected.evaluation.confidence.score
        < baseline_outcome.selected.evaluation.confidence.score
    )
    assert any(
        "yfinance option data" in note
        for note in fallback_outcome.selected.evaluation.confidence.notes
    )
