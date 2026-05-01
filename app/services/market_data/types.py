from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Literal

ConfidenceSeverity = Literal["info", "warning", "critical"]


@dataclass(slots=True, frozen=True)
class PriceBar:
    date: date
    close: Decimal
    volume: int | None = None


@dataclass(slots=True, frozen=True)
class SecuritySnapshot:
    ticker: str
    company_name: str | None
    sector: str | None
    market_cap: Decimal | None
    current_price: Decimal | None
    history: tuple[PriceBar, ...]


@dataclass(slots=True, frozen=True)
class ReturnMetrics:
    one_day: Decimal | None
    five_day: Decimal | None
    twenty_day: Decimal | None
    fifty_day: Decimal | None


@dataclass(slots=True, frozen=True)
class NewsSentimentSummary:
    article_count: int
    average_sentiment: Decimal | None
    overall_sentiment: str | None


@dataclass(slots=True, frozen=True)
class AlphaVantageSnapshot:
    ticker: str
    company_name: str | None
    sector: str | None
    market_cap: Decimal | None
    history: tuple[PriceBar, ...]
    news_sentiment: NewsSentimentSummary | None


@dataclass(slots=True, frozen=True)
class ConfidenceNote:
    source: str
    field: str
    detail: str
    severity: ConfidenceSeverity
    score_delta: int = 0


@dataclass(slots=True, frozen=True)
class MarketSnapshot:
    ticker: str
    as_of_date: date | None
    company_name: str | None
    sector: str | None
    sector_etf: str | None
    market_cap: Decimal | None
    current_price: Decimal | None
    latest_volume: int | None
    average_volume_20d: Decimal | None
    volume_vs_average_20d: Decimal | None
    stock_returns: ReturnMetrics
    spy_returns: ReturnMetrics
    qqq_returns: ReturnMetrics
    sector_returns: ReturnMetrics | None
    relative_strength_vs_spy: Decimal | None
    relative_strength_vs_qqq: Decimal | None
    relative_strength_vs_sector: Decimal | None
    av_news_sentiment: NewsSentimentSummary | None
    price_source: str
    overview_source: str
    sources: tuple[str, ...]
    confidence_adjustment: int = 0
    confidence_notes: tuple[ConfidenceNote, ...] = ()
