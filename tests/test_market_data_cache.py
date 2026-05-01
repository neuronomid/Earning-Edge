from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.services.market_data.cache import MarketDataCache
from app.services.market_data.types import (
    ConfidenceNote,
    MarketSnapshot,
    NewsSentimentSummary,
    ReturnMetrics,
)

pytestmark = pytest.mark.asyncio


@dataclass
class FakeRedis:
    values: dict[str, str] = field(default_factory=dict)
    ttl_by_key: dict[str, int] = field(default_factory=dict)

    async def get(self, key: str) -> str | None:
        return self.values.get(key)

    async def set(self, key: str, value: str, *, ex: int) -> bool:
        self.values[key] = value
        self.ttl_by_key[key] = ex
        return True


async def test_market_data_cache_round_trips_snapshot_and_uses_trading_day_key() -> None:
    redis = FakeRedis()
    cache = MarketDataCache(
        redis,
        now_provider=lambda: datetime(2026, 5, 1, 15, 30, tzinfo=ZoneInfo("America/New_York")),
    )
    snapshot = _sample_snapshot()

    await cache.store(snapshot)
    loaded = await cache.load("amd")

    assert loaded == snapshot
    assert cache.key_for("amd") == "mkt:AMD:2026-05-01"
    assert redis.ttl_by_key["mkt:AMD:2026-05-01"] == 1800


async def test_market_data_cache_miss_returns_none() -> None:
    cache = MarketDataCache(
        FakeRedis(),
        now_provider=lambda: datetime(2026, 5, 1, 9, 45, tzinfo=ZoneInfo("America/New_York")),
    )

    assert await cache.load("msft") is None


def _sample_snapshot() -> MarketSnapshot:
    return MarketSnapshot(
        ticker="AMD",
        as_of_date=date(2026, 5, 1),
        company_name="Advanced Micro Devices",
        sector="Technology",
        sector_etf="XLK",
        market_cap=Decimal("250000000000"),
        current_price=Decimal("164.50"),
        latest_volume=1500000,
        average_volume_20d=Decimal("1400000"),
        volume_vs_average_20d=Decimal("1.0714285714285714"),
        stock_returns=ReturnMetrics(
            one_day=Decimal("0.01"),
            five_day=Decimal("0.05"),
            twenty_day=Decimal("0.12"),
            fifty_day=Decimal("0.20"),
        ),
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.004"),
            five_day=Decimal("0.02"),
            twenty_day=Decimal("0.03"),
            fifty_day=Decimal("0.08"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.005"),
            five_day=Decimal("0.03"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.10"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.006"),
            five_day=Decimal("0.025"),
            twenty_day=Decimal("0.05"),
            fifty_day=Decimal("0.11"),
        ),
        relative_strength_vs_spy=Decimal("0.09"),
        relative_strength_vs_qqq=Decimal("0.08"),
        relative_strength_vs_sector=Decimal("0.07"),
        av_news_sentiment=NewsSentimentSummary(
            article_count=4,
            average_sentiment=Decimal("0.34"),
            overall_sentiment="Bullish",
        ),
        price_source="yfinance",
        overview_source="mixed",
        sources=("yfinance", "alphavantage"),
        confidence_adjustment=-8,
        confidence_notes=(
            ConfidenceNote(
                source="alphavantage",
                field="current_price",
                detail="Cross-check mismatch",
                severity="warning",
                score_delta=-5,
            ),
            ConfidenceNote(
                source="yfinance",
                field="sector_history",
                detail="Sector ETF history unavailable",
                severity="warning",
                score_delta=-3,
            ),
        ),
    )
