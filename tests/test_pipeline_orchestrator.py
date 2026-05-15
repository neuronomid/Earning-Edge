from __future__ import annotations

import time
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core import crypto
from app.core.config import get_settings
from app.db.models.user import User
from app.llm.schemas import ChosenContract, StructuredDecision
from app.pipeline.orchestrator import (
    DECISION_FINALIST_LIMIT,
    PipelineOrchestrator,
    _deferred_news_bundle,
    _expected_move_percent,
    _fallback_news_bundle,
    _select_decision_finalists,
)
from app.pipeline.types import DecisionStepResult, DecisionTrace, PipelineCandidate
from app.scoring.types import OptionContractInput
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    StrategyEventSignal,
)
from app.services.multi_strategy_service import MultiStrategyCandidateService
from app.services.strategy_catalog import build_strategy_report
from tests.fixtures.balanced_25_pool import (
    STRATEGIES,
    BalancedMarketDataStep,
    BalancedNewsStep,
    BalancedOptionsStep,
    build_balanced_batch,
    build_balanced_index,
)


def test_select_decision_finalists_keeps_top_four_by_scoring_order() -> None:
    candidates = [
        _candidate("AAA", final_score=61, confidence=90, direction=90),
        _candidate("BBB", final_score=88, confidence=70, direction=65),
        _candidate("CCC", final_score=72, confidence=95, direction=75),
        _candidate("DDD", final_score=72, confidence=88, direction=92),
        _candidate("EEE", final_score=42, confidence=99, direction=99),
        _candidate("FFF", final_score=80, confidence=60, direction=80),
    ]

    finalists = _select_decision_finalists(candidates)

    assert [item.record.ticker for item in finalists] == ["BBB", "FFF", "CCC", "DDD"]


def test_expected_move_uses_front_expiry_nearest_atm_straddle() -> None:
    chain = (
        _option("call", "long", "100", "2026-05-15", mid="4.00"),
        _option("put", "long", "100", "2026-05-15", mid="3.00"),
        _option("call", "short", "100", "2026-05-15", mid="4.00"),
        _option("put", "short", "100", "2026-05-15", mid="3.00"),
        _option("call", "long", "105", "2026-05-15", mid="1.50"),
        _option("put", "long", "105", "2026-05-15", mid="7.00"),
        _option("call", "long", "100", "2026-05-22", mid="6.00"),
        _option("put", "long", "100", "2026-05-22", mid="5.00"),
    )

    expected_move = _expected_move_percent(
        chain,
        Decimal("101"),
        date(2026, 5, 11),
    )

    assert expected_move == Decimal("0.058911")


def test_fallback_and_deferred_news_bundles_are_not_adequate() -> None:
    record = CandidateRecord(
        ticker="PM",
        company_name="Philip Morris International",
        market_cap=Decimal("299030000000"),
        earnings_date=None,
        current_price=Decimal("191.86"),
    )
    generated_at = datetime(2026, 5, 15, 0, 7, 46, tzinfo=UTC)

    fallback = _fallback_news_bundle(
        record,
        error="news service unavailable",
        generated_at=generated_at,
    )
    deferred = _deferred_news_bundle(record, generated_at=generated_at)

    assert fallback.news_coverage == "none"
    assert fallback.stale_news is True
    assert deferred.news_coverage == "none"
    assert deferred.stale_news is True


def _candidate(
    ticker: str,
    *,
    final_score: int,
    confidence: int,
    direction: int,
) -> PipelineCandidate:
    return PipelineCandidate(
        record=CandidateRecord(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            market_cap=Decimal("1000000000"),
            earnings_date=date(2026, 5, 8),
            current_price=Decimal("100"),
        ),
        context=SimpleNamespace(),
        evaluation=SimpleNamespace(
            final_score=final_score,
            confidence=SimpleNamespace(score=confidence),
            direction=SimpleNamespace(score=direction),
        ),
        news_bundle=SimpleNamespace(),
        sizing=None,
    )


@pytest.mark.asyncio
async def test_activist_13d_arm_contributes_to_finalists() -> None:
    activist_record = CandidateRecord(
        ticker="ACME",
        company_name="Acme Industries",
        market_cap=Decimal("2500000000"),
        earnings_date=None,
        current_price=Decimal("60"),
        sector="Industrials",
        sources=("sec_edgar",),
        validation_notes=("SC_13D_ACCESSION=0001234567-25-000123",),
        strategy_source="activist_13d_followthrough",
        event_signal=StrategyEventSignal(
            score=82,
            is_supportive=True,
            detail="Fresh SC 13D from Elliott Investment Management, 7.5% stake, active intent",
        ),
    )
    catalyst_record = CandidateRecord(
        ticker="BBB",
        company_name="BBB Corp",
        market_cap=Decimal("1000000000"),
        earnings_date=date(2026, 5, 20),
        current_price=Decimal("100"),
        sources=("finviz",),
        strategy_source="catalyst_confluence",
    )
    service = MultiStrategyCandidateService(
        (
            _StubArm(
                "catalyst_confluence",
                CandidateBatch(
                    candidates=(catalyst_record,),
                    screener_status="success",
                    fallback_used=False,
                    strategy_reports=(
                        build_strategy_report(
                            "catalyst_confluence",
                            status="success",
                            raw_row_count=1,
                            candidate_count=1,
                            finviz_candidate_count=1,
                        ),
                    ),
                ),
            ),
            _StubArm(
                "activist_13d_followthrough",
                CandidateBatch(
                    candidates=(activist_record,),
                    screener_status="success",
                    fallback_used=False,
                    strategy_reports=(
                        build_strategy_report(
                            "activist_13d_followthrough",
                            status="success",
                            raw_row_count=1,
                            candidate_count=1,
                            backup_candidate_count=1,
                        ),
                    ),
                ),
            ),
        )
    )

    batch = await service.get_candidates()

    tickers = [row.ticker for row in batch.candidates]
    assert "ACME" in tickers
    activist_rows = [
        row for row in batch.candidates if row.strategy_source == "activist_13d_followthrough"
    ]
    assert len(activist_rows) == 1
    assert activist_rows[0].event_signal is not None
    assert activist_rows[0].event_signal.score == 82


class _StubArm:
    def __init__(self, slug: str, batch: CandidateBatch) -> None:
        self.slug = slug
        self._batch = batch

    async def get_top_five(
        self,
        *,
        limit: int = 5,
        user_id: object | None = None,
    ) -> CandidateBatch:
        del limit, user_id
        return self._batch


def _option(
    option_type: str,
    position_side: str,
    strike: str,
    expiry: str,
    *,
    mid: str,
) -> OptionContractInput:
    return OptionContractInput(
        ticker="ABC",
        option_type=option_type,  # type: ignore[arg-type]
        position_side=position_side,  # type: ignore[arg-type]
        strike=Decimal(strike),
        expiry=date.fromisoformat(expiry),
        mid=Decimal(mid),
    )


# --- Phase 5: 5-strategy end-to-end integration tests ---------------------------


class _BatchCandidateStep:
    """Pipeline candidate step that returns a pre-built batch."""

    def __init__(self, batch: CandidateBatch) -> None:
        self._batch = batch

    async def execute(self, *, user_id: object | None = None) -> CandidateBatch:
        del user_id
        return self._batch


class _RecordingDecisionStep:
    """Heuristic-style decision step that records the candidate set it saw."""

    def __init__(self) -> None:
        self.seen_candidates: list[PipelineCandidate] = []

    async def execute(
        self,
        candidates,
        user_context,
        *,
        openrouter_api_key: str,
    ) -> DecisionStepResult:
        del user_context, openrouter_api_key
        self.seen_candidates = list(candidates)
        if not candidates:
            return DecisionStepResult(
                decision=StructuredDecision(
                    action="no_trade",
                    confidence_band="no_trade",
                    reasoning="No candidates.",
                ),
                trace=DecisionTrace(engine="heuristic"),
            )
        best = max(candidates, key=lambda item: item.evaluation.final_score)
        chosen = best.evaluation.chosen_contract
        return DecisionStepResult(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker=best.record.ticker,
                chosen_contract=ChosenContract(
                    ticker=best.record.ticker,
                    option_type=chosen.contract.option_type,
                    position_side=chosen.contract.position_side,
                    strike=chosen.contract.strike,
                    expiry=chosen.contract.expiry,
                    rationale="Recording stub picked highest final score.",
                ),
                contract_score=chosen.score,
                final_score=best.evaluation.final_score,
                reasoning="Recording stub.",
                key_evidence=["Recording stub."],
                key_concerns=[],
                watchlist_tickers=[item.record.ticker for item in candidates[:3]],
            ),
            trace=DecisionTrace(engine="heuristic"),
        )


def _user_with_key() -> User:
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


def _build_orchestrator(
    batch: CandidateBatch,
    *,
    decision_step=None,
) -> PipelineOrchestrator:
    index = build_balanced_index(
        successes=tuple(
            {record.strategy_source for record in batch.candidates if record.strategy_source}
        )
        or STRATEGIES,
    )
    return PipelineOrchestrator(
        candidate_step=_BatchCandidateStep(batch),
        market_data_step=BalancedMarketDataStep(index),
        news_step=BalancedNewsStep(index),
        options_step=BalancedOptionsStep(index),
        decision_step=decision_step,
    )


@pytest.mark.asyncio
async def test_all_five_strategies_concurrent_happy_path_25_pool() -> None:
    batch = build_balanced_batch()
    orchestrator = _build_orchestrator(batch)
    user = _user_with_key()

    outcome = await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )

    assert len(outcome.candidates) == 25
    assert outcome.decision.action in {"recommend", "watchlist", "no_trade"}
    seen_strategies = {item.context.strategy_source for item in outcome.candidates}
    assert seen_strategies == set(STRATEGIES)


@pytest.mark.asyncio
async def test_three_succeed_two_empty_runs_to_completion() -> None:
    batch = build_balanced_batch(
        successes=(
            "catalyst_confluence",
            "pead_continuation",
            "sector_relative_strength",
        )
    )
    orchestrator = _build_orchestrator(batch)
    user = _user_with_key()

    outcome = await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )

    assert len(outcome.candidates) == 15
    assert outcome.batch.screener_status == "partial"
    statuses = {report.strategy_source: report.status for report in outcome.batch.strategy_reports}
    assert statuses["coiled_setup"] == "empty"
    assert statuses["activist_13d_followthrough"] == "empty"
    assert outcome.decision.action in {"recommend", "watchlist", "no_trade"}


@pytest.mark.asyncio
async def test_top_4_finalists_selected_from_25_candidate_pool() -> None:
    batch = build_balanced_batch()
    orchestrator = _build_orchestrator(batch)
    user = _user_with_key()

    outcome = await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )

    finalists = _select_decision_finalists(list(outcome.candidates))
    assert len(finalists) == DECISION_FINALIST_LIMIT
    finalist_scores = [item.evaluation.final_score for item in finalists]
    other_scores = [
        item.evaluation.final_score for item in outcome.candidates if item not in finalists
    ]
    assert min(finalist_scores) >= max(other_scores, default=0)


@pytest.mark.asyncio
async def test_llm_only_sees_top_4_after_dedupe() -> None:
    batch = build_balanced_batch()
    recorder = _RecordingDecisionStep()
    orchestrator = _build_orchestrator(batch, decision_step=recorder)
    user = _user_with_key()

    await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )

    assert len(recorder.seen_candidates) == DECISION_FINALIST_LIMIT
    seen_tickers = [item.record.ticker for item in recorder.seen_candidates]
    assert len(set(seen_tickers)) == len(seen_tickers)


@pytest.mark.asyncio
async def test_finalists_include_at_least_three_distinct_strategies_on_balanced_day() -> None:
    batch = build_balanced_batch()
    recorder = _RecordingDecisionStep()
    orchestrator = _build_orchestrator(batch, decision_step=recorder)
    user = _user_with_key()

    await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )

    strategies_in_finalists = {item.context.strategy_source for item in recorder.seen_candidates}
    assert len(strategies_in_finalists) >= 3


@pytest.mark.asyncio
async def test_pipeline_completes_within_run_lock_ttl() -> None:
    batch = build_balanced_batch()
    orchestrator = _build_orchestrator(batch)
    user = _user_with_key()

    start = time.perf_counter()
    await orchestrator.evaluate_batch(
        batch,
        user,
        reference_dt=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
    )
    elapsed = time.perf_counter() - start

    ttl = get_settings().workflow_run_lock_ttl_seconds
    assert elapsed < ttl, f"Pipeline took {elapsed:.2f}s, exceeds TTL {ttl}s"
    # In-process fixture run should be far under the TTL (sanity guard).
    assert elapsed < 60
