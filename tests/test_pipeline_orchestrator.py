from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.pipeline.orchestrator import _expected_move_percent, _select_decision_finalists
from app.pipeline.types import PipelineCandidate
from app.scoring.types import OptionContractInput
from app.services.candidate_models import CandidateRecord


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
