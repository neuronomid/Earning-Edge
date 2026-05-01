from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Protocol
from zoneinfo import ZoneInfo

from app.services.market_data.types import (
    ConfidenceNote,
    MarketSnapshot,
    NewsSentimentSummary,
    ReturnMetrics,
)

MARKET_TIMEZONE = ZoneInfo("America/New_York")
MARKET_CLOSE_TIME = time(16, 0)


class CacheClient(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> Any: ...


class MarketDataCache:
    def __init__(
        self,
        client: CacheClient,
        *,
        key_prefix: str = "mkt",
        now_provider: Callable[[], datetime] | None = None,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix
        self.now_provider = now_provider or (lambda: datetime.now(tz=MARKET_TIMEZONE))

    async def load(self, ticker: str) -> MarketSnapshot | None:
        payload = await self.client.get(self.key_for(ticker))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return snapshot_from_json(payload)

    async def store(self, snapshot: MarketSnapshot) -> None:
        await self.client.set(
            self.key_for(snapshot.ticker),
            snapshot_to_json(snapshot),
            ex=self.ttl_seconds(),
        )

    def key_for(self, ticker: str) -> str:
        market_now = self.now_provider().astimezone(MARKET_TIMEZONE)
        return f"{self.key_prefix}:{ticker.upper()}:{market_now.date().isoformat()}"

    def ttl_seconds(self) -> int:
        market_now = self.now_provider().astimezone(MARKET_TIMEZONE)
        close_at = datetime.combine(
            market_now.date(),
            MARKET_CLOSE_TIME,
            tzinfo=MARKET_TIMEZONE,
        )
        if market_now >= close_at:
            close_at += timedelta(days=1)
        return max(60, int((close_at - market_now).total_seconds()))


def snapshot_to_json(snapshot: MarketSnapshot) -> str:
    payload = {
        "ticker": snapshot.ticker,
        "as_of_date": _encode_date(snapshot.as_of_date),
        "company_name": snapshot.company_name,
        "sector": snapshot.sector,
        "sector_etf": snapshot.sector_etf,
        "market_cap": _encode_decimal(snapshot.market_cap),
        "current_price": _encode_decimal(snapshot.current_price),
        "latest_volume": snapshot.latest_volume,
        "average_volume_20d": _encode_decimal(snapshot.average_volume_20d),
        "volume_vs_average_20d": _encode_decimal(snapshot.volume_vs_average_20d),
        "stock_returns": _returns_to_dict(snapshot.stock_returns),
        "spy_returns": _returns_to_dict(snapshot.spy_returns),
        "qqq_returns": _returns_to_dict(snapshot.qqq_returns),
        "sector_returns": (
            None if snapshot.sector_returns is None else _returns_to_dict(snapshot.sector_returns)
        ),
        "relative_strength_vs_spy": _encode_decimal(snapshot.relative_strength_vs_spy),
        "relative_strength_vs_qqq": _encode_decimal(snapshot.relative_strength_vs_qqq),
        "relative_strength_vs_sector": _encode_decimal(snapshot.relative_strength_vs_sector),
        "av_news_sentiment": _news_to_dict(snapshot.av_news_sentiment),
        "price_source": snapshot.price_source,
        "overview_source": snapshot.overview_source,
        "sources": list(snapshot.sources),
        "confidence_adjustment": snapshot.confidence_adjustment,
        "confidence_notes": [_note_to_dict(note) for note in snapshot.confidence_notes],
    }
    return json.dumps(payload, separators=(",", ":"))


def snapshot_from_json(payload: str) -> MarketSnapshot:
    data = json.loads(payload)
    return MarketSnapshot(
        ticker=data["ticker"],
        as_of_date=_decode_date(data["as_of_date"]),
        company_name=data["company_name"],
        sector=data["sector"],
        sector_etf=data["sector_etf"],
        market_cap=_decode_decimal(data["market_cap"]),
        current_price=_decode_decimal(data["current_price"]),
        latest_volume=data["latest_volume"],
        average_volume_20d=_decode_decimal(data["average_volume_20d"]),
        volume_vs_average_20d=_decode_decimal(data["volume_vs_average_20d"]),
        stock_returns=_returns_from_dict(data["stock_returns"]),
        spy_returns=_returns_from_dict(data["spy_returns"]),
        qqq_returns=_returns_from_dict(data["qqq_returns"]),
        sector_returns=(
            None
            if data["sector_returns"] is None
            else _returns_from_dict(data["sector_returns"])
        ),
        relative_strength_vs_spy=_decode_decimal(data["relative_strength_vs_spy"]),
        relative_strength_vs_qqq=_decode_decimal(data["relative_strength_vs_qqq"]),
        relative_strength_vs_sector=_decode_decimal(data["relative_strength_vs_sector"]),
        av_news_sentiment=_news_from_dict(data["av_news_sentiment"]),
        price_source=data["price_source"],
        overview_source=data["overview_source"],
        sources=tuple(data["sources"]),
        confidence_adjustment=int(data["confidence_adjustment"]),
        confidence_notes=tuple(_note_from_dict(note) for note in data["confidence_notes"]),
    )


def _encode_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decode_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)


def _encode_date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _decode_date(value: str | None) -> date | None:
    return None if value is None else date.fromisoformat(value)


def _returns_to_dict(value: ReturnMetrics) -> dict[str, str | None]:
    return {
        "one_day": _encode_decimal(value.one_day),
        "five_day": _encode_decimal(value.five_day),
        "twenty_day": _encode_decimal(value.twenty_day),
        "fifty_day": _encode_decimal(value.fifty_day),
    }


def _returns_from_dict(value: dict[str, str | None]) -> ReturnMetrics:
    return ReturnMetrics(
        one_day=_decode_decimal(value["one_day"]),
        five_day=_decode_decimal(value["five_day"]),
        twenty_day=_decode_decimal(value["twenty_day"]),
        fifty_day=_decode_decimal(value["fifty_day"]),
    )


def _news_to_dict(value: NewsSentimentSummary | None) -> dict[str, Any] | None:
    if value is None:
        return None
    return {
        "article_count": value.article_count,
        "average_sentiment": _encode_decimal(value.average_sentiment),
        "overall_sentiment": value.overall_sentiment,
    }


def _news_from_dict(value: dict[str, Any] | None) -> NewsSentimentSummary | None:
    if value is None:
        return None
    return NewsSentimentSummary(
        article_count=int(value["article_count"]),
        average_sentiment=_decode_decimal(value["average_sentiment"]),
        overall_sentiment=value["overall_sentiment"],
    )


def _note_to_dict(value: ConfidenceNote) -> dict[str, Any]:
    return {
        "source": value.source,
        "field": value.field,
        "detail": value.detail,
        "severity": value.severity,
        "score_delta": value.score_delta,
    }


def _note_from_dict(value: dict[str, Any]) -> ConfidenceNote:
    return ConfidenceNote(
        source=value["source"],
        field=value["field"],
        detail=value["detail"],
        severity=value["severity"],
        score_delta=int(value["score_delta"]),
    )
