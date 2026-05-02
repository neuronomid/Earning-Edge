from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.pipeline.orchestrator import PipelineOrchestrator
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


@pytest.mark.parametrize(
    ("strategy", "option_type", "position_side", "strike", "expiry", "expected_text"),
    [
        ("long_call", "call", "long", "104", date(2026, 5, 16), "AMD Call"),
        ("long_put", "put", "long", "96", date(2026, 5, 16), "AMD Put"),
        ("short_put", "put", "short", "95", date(2026, 5, 16), "AMD Short Put"),
        ("short_call", "call", "short", "110", date(2026, 5, 16), "AMD Short Call"),
    ],
)
async def test_end_to_end_strategy_paths(
    db_session: AsyncSession,
    strategy: str,
    option_type: str,
    position_side: str,
    strike: str,
    expiry: date,
    expected_text: str,
) -> None:
    batch = make_batch()
    notifier = FakeNotifier()
    contract = make_contract(
        "AMD",
        option_type=option_type,
        position_side=position_side,
        strike=strike,
        expiry=expiry,
        implied_volatility="0.68" if position_side == "short" else "0.44",
        delta="0.24" if position_side == "short" and option_type == "put" else "0.52",
    )
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
                    contract,
                    make_contract(
                        "AMD",
                        option_type=option_type,
                        position_side=position_side,
                        strike=str(int(strike) + 4),
                        expiry=expiry,
                        bid="0.30",
                        ask="1.10",
                    ),
                )
            }
        ),
        scoring_step=FakeScoringStep(
            {
                "AMD": ScoringPlan("recommend", 80, "bullish", 78, 82),
                "AAPL": ScoringPlan("no_trade", 52, "neutral", 54),
                "MSFT": ScoringPlan("no_trade", 51, "neutral", 53),
                "NFLX": ScoringPlan("no_trade", 49, "bearish", 50),
                "JPM": ScoringPlan("no_trade", 45, "neutral", 47),
            }
        ),
        sizing_step=FakeSizingStep(),
        notifier=notifier,
    )
    user = await make_user(db_session, telegram_chat_id=f"e2e-{strategy}")
    run = await WorkflowRunRepository(db_session).add(
        WorkflowRun(user_id=user.id, trigger_type="manual", status="running")
    )

    await orchestrator.run(db_session, run)
    await db_session.commit()

    recommendation = (await RecommendationRepository(db_session).list_recent_for_user(user.id))[0]

    assert recommendation.strategy == strategy
    assert recommendation.option_type == option_type
    assert recommendation.position_side == position_side
    assert expected_text in notifier.calls[2].text
    if strategy == "short_call":
        assert "Undefined for naked short call" in notifier.calls[2].text
