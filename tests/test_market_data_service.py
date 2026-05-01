from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.services.market_data.service import MarketDataService, MarketDataUnavailableError
from app.services.market_data.types import (
    AlphaVantageSnapshot,
    MarketSnapshot,
    NewsSentimentSummary,
    PriceBar,
    SecuritySnapshot,
)

pytestmark = pytest.mark.asyncio


@dataclass
class FakeYFinanceClient:
    snapshots: dict[str, SecuritySnapshot]
    calls: Counter[str] = field(default_factory=Counter)

    async def fetch_security(self, ticker: str) -> SecuritySnapshot:
        normalized = ticker.upper()
        self.calls.update([normalized])
        if normalized not in self.snapshots:
            raise RuntimeError(f"missing snapshot for {normalized}")
        return self.snapshots[normalized]


@dataclass
class FakeAlphaVantageClient:
    snapshots: dict[str, AlphaVantageSnapshot | None]
    calls: Counter[str] = field(default_factory=Counter)

    async def fetch_snapshot(self, ticker: str, *, api_key: str) -> AlphaVantageSnapshot | None:
        assert api_key
        normalized = ticker.upper()
        self.calls.update([normalized])
        return self.snapshots.get(normalized)


@dataclass
class FakeCache:
    values: dict[str, MarketSnapshot] = field(default_factory=dict)
    load_calls: list[str] = field(default_factory=list)
    store_calls: list[str] = field(default_factory=list)

    async def load(self, ticker: str) -> MarketSnapshot | None:
        self.load_calls.append(ticker)
        return self.values.get(ticker)

    async def store(self, snapshot: MarketSnapshot) -> None:
        self.store_calls.append(snapshot.ticker)
        self.values[snapshot.ticker] = snapshot


async def test_market_data_service_builds_snapshot_and_hits_cache_on_repeat() -> None:
    yf_client = FakeYFinanceClient(
        {
            "AMD": _security("AMD", "Technology", "250000000000", current_price="159", step="1"),
            "SPY": _security("SPY", "Index", "0", current_price="430", step="0.5"),
            "QQQ": _security("QQQ", "Index", "0", current_price="370", step="0.75"),
            "XLK": _security("XLK", "Technology", "0", current_price="220", step="0.4"),
        }
    )
    cache = FakeCache()
    service = MarketDataService(
        yfinance_client=yf_client,
        alpha_vantage_client=FakeAlphaVantageClient({}),
        cache=cache,
    )

    first = await service.fetch("amd")
    second = await service.fetch("AMD")

    assert first == second
    assert first.ticker == "AMD"
    assert first.sector_etf == "XLK"
    assert first.sources == ("yfinance",)
    assert first.av_news_sentiment is None
    assert first.relative_strength_vs_spy is not None
    assert cache.load_calls == ["AMD", "AMD"]
    assert cache.store_calls == ["AMD"]
    assert yf_client.calls["AMD"] == 1


async def test_market_data_service_uses_alpha_vantage_for_missing_overview_and_conflicts() -> None:
    yf_client = FakeYFinanceClient(
        {
            "AMD": SecuritySnapshot(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                sector=None,
                market_cap=None,
                current_price=Decimal("159"),
                history=_bars(start=Decimal("100"), step=Decimal("1")),
            ),
            "SPY": _security("SPY", "Index", "0", current_price="430", step="0.5"),
            "QQQ": _security("QQQ", "Index", "0", current_price="370", step="0.75"),
            "XLK": _security("XLK", "Technology", "0", current_price="220", step="0.4"),
        }
    )
    av_client = FakeAlphaVantageClient(
        {
            "AMD": AlphaVantageSnapshot(
                ticker="AMD",
                company_name="AMD",
                sector="Technology",
                market_cap=Decimal("260000000000"),
                history=_bars(start=Decimal("100"), step=Decimal("0.8")),
                news_sentiment=NewsSentimentSummary(
                    article_count=3,
                    average_sentiment=Decimal("0.25"),
                    overall_sentiment="Bullish",
                ),
            )
        }
    )
    service = MarketDataService(
        yfinance_client=yf_client,
        alpha_vantage_client=av_client,
        cache=None,
    )

    snapshot = await service.fetch("AMD", alpha_vantage_api_key="av-key")

    assert snapshot.overview_source == "mixed"
    assert snapshot.sector == "Technology"
    assert snapshot.market_cap == Decimal("260000000000")
    assert snapshot.sources == ("yfinance", "alphavantage")
    assert snapshot.av_news_sentiment is not None
    assert snapshot.confidence_adjustment < 0
    assert {note.field for note in snapshot.confidence_notes} == {"current_price"}


async def test_market_data_service_falls_back_to_alpha_vantage_history() -> None:
    yf_client = FakeYFinanceClient(
        {
            "AMD": SecuritySnapshot(
                ticker="AMD",
                company_name="Advanced Micro Devices",
                sector="Technology",
                market_cap=Decimal("255000000000"),
                current_price=Decimal("159"),
                history=(),
            ),
            "SPY": _security("SPY", "Index", "0", current_price="430", step="0.5"),
            "QQQ": _security("QQQ", "Index", "0", current_price="370", step="0.75"),
            "XLK": _security("XLK", "Technology", "0", current_price="220", step="0.4"),
        }
    )
    av_client = FakeAlphaVantageClient(
        {
            "AMD": AlphaVantageSnapshot(
                ticker="AMD",
                company_name="AMD",
                sector="Technology",
                market_cap=Decimal("252000000000"),
                history=_bars(start=Decimal("100"), step=Decimal("0.9")),
                news_sentiment=None,
            )
        }
    )
    service = MarketDataService(
        yfinance_client=yf_client,
        alpha_vantage_client=av_client,
        cache=None,
    )

    snapshot = await service.fetch("AMD", alpha_vantage_api_key="av-key")

    assert snapshot.price_source == "alphavantage"
    assert snapshot.current_price == Decimal("153.1")
    assert snapshot.confidence_adjustment <= -5
    assert any(note.field == "price_history" for note in snapshot.confidence_notes)


async def test_market_data_service_raises_when_no_source_can_supply_history() -> None:
    service = MarketDataService(
        yfinance_client=FakeYFinanceClient({}),
        alpha_vantage_client=FakeAlphaVantageClient({}),
        cache=None,
    )

    with pytest.raises(MarketDataUnavailableError):
        await service.fetch("AMD", alpha_vantage_api_key="av-key")


def _security(
    ticker: str,
    sector: str,
    market_cap: str,
    *,
    current_price: str,
    step: str,
) -> SecuritySnapshot:
    return SecuritySnapshot(
        ticker=ticker,
        company_name=f"{ticker} Inc.",
        sector=sector,
        market_cap=Decimal(market_cap),
        current_price=Decimal(current_price),
        history=_bars(start=Decimal("100"), step=Decimal(step)),
    )


def _bars(
    *,
    start: Decimal,
    step: Decimal,
    days: int = 60,
    volume_start: int = 1000,
) -> tuple[PriceBar, ...]:
    first_day = date(2026, 1, 1)
    return tuple(
        PriceBar(
            date=first_day + timedelta(days=offset),
            close=start + (step * Decimal(offset)),
            volume=volume_start + (offset * 10),
        )
        for offset in range(days)
    )
