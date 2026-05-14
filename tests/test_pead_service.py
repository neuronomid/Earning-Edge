from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from app.core.config import Settings
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.finviz.query import FinvizQuery
from app.services.finviz.strategies import (
    STRATEGY_C_EARNINGS_PREFIX,
    STRATEGY_C_EARNINGS_VALUES,
)
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.pead_service import (
    PEAD_STRATEGY_SOURCE,
    PEADCandidateService,
    PEADEarningsEvent,
)

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 5, 14)


@dataclass
class FakeRunner:
    rows: list[CandidateRecord] = field(default_factory=list)
    error: Exception | None = None
    last_call: dict[str, Any] | None = None

    async def run_with_swap(
        self,
        base: FinvizQuery,
        *,
        swap_prefix: str,
        swap_values: tuple[str, ...],
        limit: int,
        strategy_source: str,
    ) -> list[CandidateRecord]:
        self.last_call = {
            "base": base,
            "swap_prefix": swap_prefix,
            "swap_values": swap_values,
            "limit": limit,
            "strategy_source": strategy_source,
        }
        if self.error is not None:
            raise self.error
        return list(self.rows)


@dataclass
class FakeSurpriseSource:
    name: str
    events: dict[str, PEADEarningsEvent | Exception | None]
    calls: list[str] = field(default_factory=list)

    async def get_earnings_event(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None:
        assert as_of == TODAY
        self.calls.append(ticker.upper())
        value = self.events.get(ticker.upper())
        if isinstance(value, Exception):
            raise value
        return value


@dataclass
class FakeOpenPositions:
    tickers: frozenset[str] = frozenset()

    async def active_catalyst_tickers(
        self,
        *,
        as_of: date,
        user_id: object | None = None,
    ) -> frozenset[str]:
        del user_id
        assert as_of == TODAY
        return self.tickers


class FakeMarketData:
    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key, refresh
        return _snapshot(ticker)


def _row(
    ticker: str,
    *,
    change: str = "4.0",
    sector: str | None = "Industrials",
    market_cap: str | None = "1000000000",
) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=None if market_cap is None else Decimal(market_cap),
        earnings_date=None,
        current_price=Decimal("50"),
        screener_rank=1,
        daily_change_percent=Decimal(change),
        volume=1_000_000,
        sector=sector,
        sources=("finviz",),
    )


def _event(
    surprise: str,
    *,
    announcement_date: date | None = date(2026, 5, 12),
    source: str = "yfinance",
) -> PEADEarningsEvent:
    return PEADEarningsEvent(
        surprise_pct=Decimal(surprise),
        announcement_date=announcement_date,
        source=source,
    )


def _source(events: dict[str, PEADEarningsEvent | Exception | None]) -> FakeSurpriseSource:
    return FakeSurpriseSource("yfinance", events)


def _service(
    rows: list[CandidateRecord],
    sources: tuple[FakeSurpriseSource, ...],
    *,
    open_tickers: frozenset[str] = frozenset(),
) -> PEADCandidateService:
    return PEADCandidateService(
        FakeRunner(rows=rows),
        market_data=FakeMarketData(),
        surprise_sources=sources,
        open_positions=FakeOpenPositions(open_tickers),
        settings=Settings(),
        today_provider=lambda: TODAY,
    )


async def test_pead_service_uses_strategy_c_variant_swap() -> None:
    runner = FakeRunner(rows=[_row("AAA")])
    service = PEADCandidateService(
        runner,
        market_data=FakeMarketData(),
        surprise_sources=(_source({"AAA": _event("0.06")}),),
        settings=Settings(),
        today_provider=lambda: TODAY,
    )

    batch = await service.get_top_five()

    assert isinstance(batch, CandidateBatch)
    assert runner.last_call is not None
    assert runner.last_call["swap_prefix"] == STRATEGY_C_EARNINGS_PREFIX
    assert runner.last_call["swap_values"] == STRATEGY_C_EARNINGS_VALUES
    assert runner.last_call["limit"] == 20
    assert runner.last_call["strategy_source"] == PEAD_STRATEGY_SOURCE


async def test_post_filter_drops_below_surprise_threshold() -> None:
    service = _service(
        [_row("LOW"), _row("PASS")],
        (_source({"LOW": _event("0.049"), "PASS": _event("0.05")}),),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["PASS"]


async def test_post_filter_drops_tech_and_communication_services() -> None:
    service = _service(
        [
            _row("TECH", sector="Technology"),
            _row("COMM", sector="Communication Services"),
            _row("IND", sector="Industrials"),
        ],
        (
            _source(
                {
                    "TECH": _event("0.07"),
                    "COMM": _event("0.07"),
                    "IND": _event("0.07"),
                }
            ),
        ),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["IND"]


async def test_post_filter_drops_outside_market_cap_band() -> None:
    service = _service(
        [
            _row("SMALL", market_cap="299999999"),
            _row("LARGE", market_cap="10000000001"),
            _row("PASS", market_cap="500000000"),
        ],
        (
            _source(
                {
                    "SMALL": _event("0.07"),
                    "LARGE": _event("0.07"),
                    "PASS": _event("0.07"),
                }
            ),
        ),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["PASS"]


async def test_post_filter_drops_same_day_announcement() -> None:
    service = _service(
        [_row("TODAY"), _row("OLD")],
        (
            _source(
                {
                    "TODAY": _event("0.07", announcement_date=TODAY),
                    "OLD": _event("0.07", announcement_date=date(2026, 5, 12)),
                }
            ),
        ),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["OLD"]


async def test_yfinance_failure_falls_back_to_finnhub() -> None:
    yfinance = FakeSurpriseSource("yfinance", {"AAA": RuntimeError("yf down")})
    finnhub = FakeSurpriseSource("finnhub", {"AAA": _event("0.07", source="finnhub")})
    service = _service([_row("AAA")], (yfinance, finnhub))

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["AAA"]
    assert yfinance.calls == ["AAA"]
    assert finnhub.calls == ["AAA"]
    assert "PEAD surprise source: finnhub" in batch.candidates[0].validation_notes


async def test_finnhub_failure_falls_back_to_alpha_vantage() -> None:
    yfinance = FakeSurpriseSource("yfinance", {"AAA": None})
    finnhub = FakeSurpriseSource("finnhub", {"AAA": RuntimeError("finnhub down")})
    alpha = FakeSurpriseSource(
        "alphavantage",
        {"AAA": _event("0.07", source="alphavantage")},
    )
    service = _service([_row("AAA")], (yfinance, finnhub, alpha))

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["AAA"]
    assert alpha.calls == ["AAA"]
    assert "PEAD surprise source: alphavantage" in batch.candidates[0].validation_notes


async def test_all_three_data_sources_fail_returns_empty_batch() -> None:
    yfinance = FakeSurpriseSource("yfinance", {"AAA": RuntimeError("yf down")})
    finnhub = FakeSurpriseSource("finnhub", {"AAA": RuntimeError("finnhub down")})
    alpha = FakeSurpriseSource("alphavantage", {"AAA": RuntimeError("av down")})
    service = _service([_row("AAA")], (yfinance, finnhub, alpha))

    batch = await service.get_top_five()

    assert batch.candidates == ()
    assert batch.screener_status == "empty"
    assert batch.strategy_reports[0].status == "empty"


async def test_top_5_ranking_by_composite_score() -> None:
    rows = [
        _row("T1", change="3.0"),
        _row("T2", change="6.0"),
        _row("T3", change="4.0"),
        _row("T4", change="9.0"),
        _row("T5", change="5.0"),
        _row("T6", change="8.0"),
    ]
    service = _service(
        rows,
        (
            _source(
                {
                    "T1": _event("0.05"),
                    "T2": _event("0.05"),
                    "T3": _event("0.09"),
                    "T4": _event("0.08"),
                    "T5": _event("0.06"),
                    "T6": _event("0.10"),
                }
            ),
        ),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["T6", "T4", "T3", "T2", "T5"]


async def test_partial_batch_when_fewer_than_5_pass() -> None:
    service = _service(
        [_row("PASS"), _row("LOW", change="1.0")],
        (_source({"PASS": _event("0.07"), "LOW": _event("0.07")}),),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["PASS"]
    assert batch.screener_status == "partial"


async def test_does_not_pad_with_unconfirmed_names() -> None:
    service = _service(
        [_row("PASS"), _row("NOEVENT")],
        (_source({"PASS": _event("0.07"), "NOEVENT": None}),),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["PASS"]
    assert len(batch.candidates) == 1


async def test_event_signal_populated_with_surprise_and_day1() -> None:
    service = _service([_row("AAA", change="3.0")], (_source({"AAA": _event("0.05")}),))

    batch = await service.get_top_five()

    signal = batch.candidates[0].event_signal
    assert signal is not None
    assert signal.score == 100
    assert signal.detail == "Earnings surprise 5.0%, day-1 reaction +3.0%"


async def test_cross_arm_dedupe_skips_open_strategy_a_positions() -> None:
    service = _service(
        [_row("OPEN"), _row("PASS")],
        (_source({"OPEN": _event("0.07"), "PASS": _event("0.07")}),),
        open_tickers=frozenset({"OPEN"}),
    )

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["PASS"]


def _snapshot(ticker: str) -> MarketSnapshot:
    returns = ReturnMetrics(
        one_day=Decimal("0.04"),
        five_day=None,
        twenty_day=None,
        fifty_day=None,
    )
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=TODAY,
        company_name=f"{ticker} Co",
        sector="Industrials",
        sector_etf="XLI",
        market_cap=Decimal("1000000000"),
        current_price=Decimal("50"),
        latest_volume=1_000_000,
        average_volume_20d=Decimal("900000"),
        volume_vs_average_20d=Decimal("1.1"),
        stock_returns=returns,
        spy_returns=returns,
        qqq_returns=returns,
        sector_returns=returns,
        relative_strength_vs_spy=Decimal("0.02"),
        relative_strength_vs_qqq=Decimal("0.02"),
        relative_strength_vs_sector=Decimal("0.01"),
        av_news_sentiment=None,
        price_source="yfinance",
        overview_source="yfinance",
        sources=("yfinance",),
    )
