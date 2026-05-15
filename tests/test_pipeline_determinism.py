"""Determinism guarantee for the deterministic scoring layer.

Locks in: given the same `CandidateContext` and `UserContext`, structural
data confidence and structural direction tier MUST be bit-identical across
re-runs. This is the regression test for the original bug where Gemini-
generated jitter caused confidence to vary between scans.

If this test ever fails, a non-determinism source has been reintroduced.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.core import crypto
from app.db.models.user import User
from app.pipeline.orchestrator import PipelineOrchestrator, _select_decision_finalists
from app.scoring.final import score_candidate
from app.scoring.types import (
    CandidateContext,
    UserContext,
)
from app.services.candidate_models import CandidateBatch
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle
from tests.fixtures.balanced_25_pool import (
    BalancedMarketDataStep,
    BalancedNewsStep,
    BalancedOptionsStep,
    build_balanced_batch,
    build_balanced_index,
)


def _stub_news_brief() -> NewsBrief:
    return NewsBrief(
        neutral_contextual_evidence=["Sector trade flow stayed orderly."],
        key_uncertainty="Guidance reset risk into the print.",
        summary="Channel checks signal stronger demand; margins guidance softer than consensus.",
        key_facts=[
            "Channel checks point to stronger demand quarter-over-quarter.",
            "Sell-side guidance estimates softer margins for the upcoming quarter.",
        ],
    )


def _stub_news_bundle(ticker: str) -> NewsBundle:
    return NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        generated_at=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
        search_results=(),
        articles=(),
        brief=_stub_news_brief(),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def _stub_market_snapshot(ticker: str) -> MarketSnapshot:
    returns = ReturnMetrics(
        one_day=Decimal("0.012"),
        five_day=Decimal("0.034"),
        twenty_day=Decimal("0.058"),
        fifty_day=Decimal("0.077"),
    )
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=date(2026, 5, 1),
        company_name=f"{ticker} Corp.",
        sector="Information Technology",
        sector_etf="XLK",
        market_cap=Decimal("180000000000"),
        current_price=Decimal("420.50"),
        latest_volume=2500000,
        average_volume_20d=Decimal("2100000"),
        volume_vs_average_20d=Decimal("1.19"),
        stock_returns=returns,
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.003"),
            five_day=Decimal("0.012"),
            twenty_day=Decimal("0.028"),
            fifty_day=Decimal("0.045"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.004"),
            five_day=Decimal("0.018"),
            twenty_day=Decimal("0.036"),
            fifty_day=Decimal("0.058"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.005"),
            five_day=Decimal("0.020"),
            twenty_day=Decimal("0.040"),
            fifty_day=Decimal("0.062"),
        ),
        relative_strength_vs_spy=Decimal("0.018"),
        relative_strength_vs_qqq=Decimal("0.011"),
        relative_strength_vs_sector=Decimal("0.005"),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
    )


def _stub_context(ticker: str = "ABCD") -> CandidateContext:
    snapshot = _stub_market_snapshot(ticker)
    bundle = _stub_news_bundle(ticker)
    return CandidateContext(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        earnings_date=date(2026, 5, 8),
        earnings_timing="AMC",
        market_snapshot=snapshot,
        news_brief=bundle.brief,
        option_chain=(),
        verified_earnings_date=True,
        identity_verified=True,
        source_conflicts=(),
        calculation_errors=(),
    )


def _stub_user_context() -> UserContext:
    return UserContext(
        risk_profile="Balanced",
        strategy_permission="long_and_short",
        account_size=Decimal("50000"),
        has_valid_openrouter_api_key=True,
    )


def test_scoring_is_bit_identical_across_repeated_runs() -> None:
    """Same inputs MUST produce same structural confidence and direction outputs."""
    context = _stub_context()
    user = _stub_user_context()

    runs = [score_candidate(context, user) for _ in range(3)]

    confidences = {run.confidence.score for run in runs}
    direction_scores = {run.direction.score for run in runs}
    direction_classifications = {run.direction.classification for run in runs}
    direction_biases = {run.direction.bias for run in runs}

    assert len(confidences) == 1, f"data confidence varied: {confidences}"
    assert len(direction_scores) == 1, f"direction score varied: {direction_scores}"
    assert len(direction_classifications) == 1, (
        f"direction classification varied: {direction_classifications}"
    )
    assert len(direction_biases) == 1, f"direction bias varied: {direction_biases}"


class _BatchCandidateStep:
    def __init__(self, batch: CandidateBatch) -> None:
        self._batch = batch

    async def execute(self) -> CandidateBatch:
        return self._batch


def _balanced_user() -> User:
    crypto.reset_cache()
    return User(
        id=uuid4(),
        telegram_chat_id="12345",
        account_size=Decimal("20000.00"),
        risk_profile="Balanced",
        broker="IBKR",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=3,
        openrouter_api_key_encrypted=crypto.encrypt("sk-or-test"),
    )


@pytest.mark.asyncio
async def test_five_strategy_run_is_deterministic_under_frozen_inputs() -> None:
    """The balanced 25-candidate pool MUST produce identical finalist orderings."""
    batch = build_balanced_batch()
    index = build_balanced_index()
    reference_dt = datetime(2026, 5, 1, 15, 55, tzinfo=UTC)

    runs = []
    for _ in range(3):
        orchestrator = PipelineOrchestrator(
            candidate_step=_BatchCandidateStep(batch),
            market_data_step=BalancedMarketDataStep(index),
            news_step=BalancedNewsStep(index),
            options_step=BalancedOptionsStep(index),
        )
        outcome = await orchestrator.evaluate_batch(
            batch,
            _balanced_user(),
            reference_dt=reference_dt,
        )
        finalists = _select_decision_finalists(list(outcome.candidates))
        runs.append(
            tuple(
                (
                    item.record.ticker,
                    item.context.strategy_source,
                    item.evaluation.final_score,
                    item.evaluation.confidence.score,
                    item.evaluation.direction.score,
                )
                for item in finalists
            )
        )

    assert runs[0] == runs[1] == runs[2], f"finalist order drifted across runs: {runs}"
