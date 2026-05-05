from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.multi_strategy_service import (
    BOTH_FAILED_WARNING,
    CATALYST_FAILED_WARNING,
    CATALYST_ONLY_WARNING,
    COILED_FAILED_WARNING,
    COILED_ONLY_WARNING,
    MultiStrategyCandidateService,
)

pytestmark = pytest.mark.asyncio


def _row(ticker: str, *, rank: int, strategy_source: str) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=Decimal("1000"),
        earnings_date=None,
        current_price=Decimal("100"),
        screener_rank=rank,
        sources=("finviz",),
        strategy_source=strategy_source,
    )


@dataclass
class FakeCatalyst:
    batch: CandidateBatch | None = None
    error: Exception | None = None

    async def get_top_five(self) -> CandidateBatch:
        if self.error is not None:
            raise self.error
        assert self.batch is not None
        return self.batch


@dataclass
class FakeCoiled:
    rows: tuple[CandidateRecord, ...] = field(default_factory=tuple)
    error: Exception | None = None

    async def get_top_five(self) -> tuple[CandidateRecord, ...]:
        if self.error is not None:
            raise self.error
        return self.rows


async def test_merges_disjoint_strategies() -> None:
    catalyst_batch = CandidateBatch(
        candidates=tuple(
            _row(t, rank=i, strategy_source="catalyst_confluence")
            for i, t in enumerate(["A", "B", "C", "D", "E"], start=1)
        ),
        screener_status="success",
        fallback_used=False,
    )
    coiled_rows = tuple(
        _row(t, rank=i, strategy_source="coiled_setup")
        for i, t in enumerate(["F", "G", "H", "I", "J"], start=1)
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(rows=coiled_rows),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "success"
    assert batch.warning_text is None
    assert batch.fallback_used is False
    assert len(batch.candidates) == 10
    sources = {row.strategy_source for row in batch.candidates}
    assert sources == {"catalyst_confluence", "coiled_setup"}
    assert {report.strategy_source for report in batch.strategy_reports} == {
        "catalyst_confluence",
        "coiled_setup",
    }


async def test_dedupes_overlapping_tickers_keeping_catalyst() -> None:
    catalyst_batch = CandidateBatch(
        candidates=(
            _row("AAA", rank=1, strategy_source="catalyst_confluence"),
            _row("BBB", rank=2, strategy_source="catalyst_confluence"),
        ),
        screener_status="success",
        fallback_used=False,
    )
    coiled_rows = (
        _row("AAA", rank=1, strategy_source="coiled_setup"),
        _row("CCC", rank=2, strategy_source="coiled_setup"),
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(rows=coiled_rows),
    )

    batch = await service.get_candidates()

    by_ticker = {row.ticker: row.strategy_source for row in batch.candidates}
    assert by_ticker == {
        "AAA": "catalyst_confluence",
        "BBB": "catalyst_confluence",
        "CCC": "coiled_setup",
    }


async def test_partial_when_only_catalyst_returns() -> None:
    catalyst_batch = CandidateBatch(
        candidates=(
            _row("AAA", rank=1, strategy_source="catalyst_confluence"),
        ),
        screener_status="success",
        fallback_used=False,
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(rows=()),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == CATALYST_ONLY_WARNING
    assert len(batch.candidates) == 1
    coiled_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "coiled_setup"
    )
    assert coiled_report.status == "empty"


async def test_partial_when_only_coiled_returns() -> None:
    catalyst_batch = CandidateBatch(
        candidates=(),
        screener_status="failed",
        fallback_used=False,
    )
    coiled_rows = (
        _row("XXX", rank=1, strategy_source="coiled_setup"),
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(rows=coiled_rows),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == COILED_ONLY_WARNING
    assert [row.ticker for row in batch.candidates] == ["XXX"]


async def test_failed_when_both_empty() -> None:
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=CandidateBatch(
            candidates=(),
            screener_status="failed",
            fallback_used=False,
        )),
        FakeCoiled(rows=()),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "failed"
    assert batch.warning_text == BOTH_FAILED_WARNING
    assert batch.candidates == ()


async def test_catalyst_exception_treated_as_zero_rows() -> None:
    coiled_rows = (
        _row("XXX", rank=1, strategy_source="coiled_setup"),
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(error=RuntimeError("catalyst exploded")),
        FakeCoiled(rows=coiled_rows),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == CATALYST_FAILED_WARNING
    assert [row.ticker for row in batch.candidates] == ["XXX"]


async def test_coiled_exception_is_reported_as_failed_not_empty() -> None:
    catalyst_batch = CandidateBatch(
        candidates=(
            _row("AAA", rank=1, strategy_source="catalyst_confluence"),
        ),
        screener_status="success",
        fallback_used=False,
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(error=RuntimeError("coiled exploded")),
    )

    batch = await service.get_candidates()

    assert batch.screener_status == "partial"
    assert batch.warning_text == COILED_FAILED_WARNING
    coiled_report = next(
        report for report in batch.strategy_reports if report.strategy_source == "coiled_setup"
    )
    assert coiled_report.status == "failed"


async def test_propagates_fallback_used_from_catalyst() -> None:
    catalyst_batch = CandidateBatch(
        candidates=(
            _row("AAA", rank=1, strategy_source="catalyst_confluence"),
        ),
        screener_status="failed",
        fallback_used=True,
        warning_text="catalyst-fallback warning",
    )
    coiled_rows = (
        _row("BBB", rank=1, strategy_source="coiled_setup"),
    )
    service = MultiStrategyCandidateService(
        FakeCatalyst(batch=catalyst_batch),
        FakeCoiled(rows=coiled_rows),
    )

    batch = await service.get_candidates()

    assert batch.fallback_used is True
    # Both strategies contributed, so status is success.
    assert batch.screener_status == "success"
