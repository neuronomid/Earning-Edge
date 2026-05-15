from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from app.services.candidate_models import CandidateRecord
from app.services.finviz.query import FinvizQuery
from app.services.finviz.strategies import STRATEGY_D_SECTOR_PREFIX, build_strategy_d_query
from app.services.sector_relative_strength_service import (
    SECTOR_RS_STRATEGY_SOURCE,
    RankedSector,
    SectorRelativeStrengthService,
)

pytestmark = pytest.mark.asyncio


@dataclass
class FakePriceSource:
    histories: Mapping[str, tuple[Decimal, ...]]
    error: Exception | None = None
    requested: tuple[str, ...] = ()

    async def fetch_closes(self, etfs: Sequence[str]) -> Mapping[str, tuple[Decimal, ...]]:
        self.requested = tuple(etfs)
        if self.error is not None:
            raise self.error
        return self.histories


@dataclass
class FakeRunner:
    rows_by_filter: Mapping[str, list[CandidateRecord]] = field(default_factory=dict)
    errors_by_filter: Mapping[str, Exception] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)

    async def run_with_swap(
        self,
        base: FinvizQuery,
        *,
        swap_prefix: str,
        swap_values: tuple[str, ...],
        limit: int,
        strategy_source: str,
    ) -> list[CandidateRecord]:
        sector_filter = swap_values[0]
        self.calls.append(
            {
                "base": base,
                "swap_prefix": swap_prefix,
                "swap_values": swap_values,
                "limit": limit,
                "strategy_source": strategy_source,
            }
        )
        if sector_filter in self.errors_by_filter:
            raise self.errors_by_filter[sector_filter]
        return list(self.rows_by_filter.get(sector_filter, ()))[:limit]


def _service(
    histories: Mapping[str, tuple[Decimal, ...]],
    *,
    runner: FakeRunner | None = None,
    price_error: Exception | None = None,
) -> SectorRelativeStrengthService:
    return SectorRelativeStrengthService(
        runner or FakeRunner(),
        price_source=FakePriceSource(histories, error=price_error),
        settings=Settings(),
    )


def _row(ticker: str, *, rank: int) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=Decimal("1000000000"),
        earnings_date=None,
        current_price=Decimal("50"),
        screener_rank=rank,
        daily_change_percent=Decimal("1.0"),
        volume=1_000_000,
        sector="Industrials",
        sources=("finviz",),
    )


def _histories(
    values: Mapping[str, tuple[str, bool]],
) -> dict[str, tuple[Decimal, ...]]:
    return {
        etf: _history(perf_4w=Decimal(perf), below_sma=below_sma)
        for etf, (perf, below_sma) in values.items()
    }


def _history(*, perf_4w: Decimal, below_sma: bool = False) -> tuple[Decimal, ...]:
    latest = Decimal("100")
    lookback = latest / (Decimal("1") + perf_4w)
    filler = Decimal("120") if below_sma else lookback
    closes = [filler for _ in range(50)]
    closes[-21] = lookback
    closes[-1] = latest
    return tuple(closes)


async def test_ranks_etfs_by_4w_return() -> None:
    service = _service(
        _histories(
            {
                "XLE": ("0.03", False),
                "XLF": ("0.08", False),
                "XLI": ("0.04", False),
            }
        )
    )

    ranked = await service._rank_sectors()

    assert [sector.etf for sector in ranked[:3]] == ["XLF", "XLI", "XLE"]


async def test_excludes_xlk_and_xlc_unconditionally() -> None:
    source = FakePriceSource(
        _histories(
            {
                "XLE": ("0.03", False),
                "XLK": ("0.20", False),
                "XLC": ("0.19", False),
            }
        )
    )
    service = SectorRelativeStrengthService(
        FakeRunner(),
        price_source=source,
        settings=Settings(),
    )

    await service._rank_sectors()

    assert "XLK" not in source.requested
    assert "XLC" not in source.requested


async def test_regime_gate_blocks_when_top_below_sma50() -> None:
    service = _service(
        _histories(
            {
                "XLE": ("0.08", True),
                "XLF": ("0.06", False),
            }
        )
    )

    batch = await service.get_top_five()

    assert batch.candidates == ()
    assert batch.screener_status == "empty"
    assert batch.strategy_reports[0].warning_text == "regime gate blocked"


async def test_regime_gate_blocks_when_dispersion_below_2pct() -> None:
    service = _service(_histories({"XLE": ("0.019", False)}))

    batch = await service.get_top_five()

    assert batch.candidates == ()
    assert batch.screener_status == "empty"
    assert batch.strategy_reports[0].warning_text == "regime gate blocked"


async def test_drops_to_second_sector_when_first_returns_fewer_than_5() -> None:
    runner = FakeRunner(
        rows_by_filter={
            "sec_energy": [_row("AAA", rank=1), _row("BBB", rank=2)],
            "sec_financial": [
                _row("CCC", rank=1),
                _row("DDD", rank=2),
                _row("EEE", rank=3),
            ],
        }
    )
    service = _service(
        _histories(
            {
                "XLE": ("0.08", False),
                "XLF": ("0.06", False),
            }
        ),
        runner=runner,
    )

    batch = await service.get_top_five()

    assert len(batch.candidates) == 5
    assert [call["swap_values"][0] for call in runner.calls] == [
        "sec_energy",
        "sec_financial",
    ]


async def test_does_not_drop_to_second_sector_when_second_fails_regime_gate() -> None:
    runner = FakeRunner(
        rows_by_filter={
            "sec_energy": [_row("AAA", rank=1), _row("BBB", rank=2)],
            "sec_financial": [_row("CCC", rank=1), _row("DDD", rank=2)],
        }
    )
    service = _service(
        _histories(
            {
                "XLE": ("0.08", False),
                "XLF": ("0.01", False),
            }
        ),
        runner=runner,
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["AAA", "BBB"]
    assert batch.screener_status == "partial"
    assert [call["swap_values"][0] for call in runner.calls] == ["sec_energy"]


async def test_dynamic_finviz_url_built_correctly() -> None:
    query = build_strategy_d_query("sec_energy")

    assert query.to_url() == (
        "https://finviz.com/screener?"
        "v=111&f=sec_energy,geo_usa,sh_opt_option,sh_price_o10,"
        "sh_avgvol_o500,ta_sma50_pa&o=-perf4w"
    )
    with pytest.raises(ValueError, match="Expected sec_\\* filter"):
        build_strategy_d_query("ta_beta_o1")
    with pytest.raises(ValueError, match="Expected sec_\\* filter"):
        build_strategy_d_query("sec_energy,ta_beta_o1")


async def test_returns_empty_batch_when_yfinance_fails() -> None:
    service = _service({}, price_error=RuntimeError("yf down"))

    batch = await service.get_top_five()

    assert batch.candidates == ()
    assert batch.screener_status == "empty"
    assert batch.strategy_reports[0].status == "empty"
    assert batch.strategy_reports[0].warning_text == "yfinance unavailable"
    assert batch.strategy_reports[0].error == "yf down"


async def test_event_signal_populated_with_sector_and_stock_percentiles() -> None:
    runner = FakeRunner(
        rows_by_filter={
            "sec_energy": [_row("AAA", rank=1), _row("BBB", rank=2)],
        }
    )
    service = _service(_histories({"XLE": ("0.08", False)}), runner=runner)

    batch = await service.get_top_five()

    first_signal = batch.candidates[0].event_signal
    second_signal = batch.candidates[1].event_signal
    assert first_signal is not None
    assert second_signal is not None
    assert first_signal.score == 100
    assert second_signal.score == 80
    assert first_signal.detail == "XLE sector +8.0% (4w), stock screen percentile 100%"
    assert batch.candidates[0].strategy_source == SECTOR_RS_STRATEGY_SOURCE


async def test_strategy_run_report_query_urls_show_active_sector() -> None:
    runner = FakeRunner(rows_by_filter={"sec_energy": [_row("AAA", rank=1)]})
    service = _service(_histories({"XLE": ("0.08", False)}), runner=runner)

    batch = await service.get_top_five()

    report = batch.strategy_reports[0]
    assert report.query_urls == (build_strategy_d_query("sec_energy").to_url(),)
    assert report.filter_codes == build_strategy_d_query("sec_energy").filters
    assert report.strategy_source == SECTOR_RS_STRATEGY_SOURCE
    assert runner.calls[0]["swap_prefix"] == STRATEGY_D_SECTOR_PREFIX
    assert runner.calls[0]["strategy_source"] == SECTOR_RS_STRATEGY_SOURCE


async def test_regime_gate() -> None:
    service = _service({})
    sector = RankedSector(
        etf="XLE",
        sector_filter="sec_energy",
        perf_4w=Decimal("0.02"),
        above_sma=True,
    )

    assert service._regime_gate(sector.above_sma, sector.perf_4w) is True
