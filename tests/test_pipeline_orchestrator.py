from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.pipeline.orchestrator import _expected_move_percent, _select_decision_finalists
from app.pipeline.types import PipelineCandidate
from app.scoring.types import OptionContractInput
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    StrategyEventSignal,
)
from app.services.multi_strategy_service import MultiStrategyCandidateService
from app.services.strategy_catalog import build_strategy_report


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

    async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
        del limit
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
