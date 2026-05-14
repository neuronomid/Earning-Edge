from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from app.services.candidate_models import CandidateRecord, StrategyEventSignal, StrategySource
from app.services.finviz.query import FinvizQuery


class CacheClient(Protocol):
    async def get(self, key: str) -> str | bytes | None: ...

    async def set(self, key: str, value: str, *, ex: int) -> Any: ...


class FinvizScreenerCache:
    def __init__(
        self,
        client: CacheClient,
        *,
        key_prefix: str = "screener",
        ttl_seconds: int = 600,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.client = client
        self.key_prefix = key_prefix
        self.ttl_seconds = ttl_seconds
        self.today_provider = today_provider or date.today

    def key_for(self, strategy_source: StrategySource, query: FinvizQuery) -> str:
        today = self.today_provider().isoformat()
        return f"{self.key_prefix}:{strategy_source}:{query.stable_hash()}:{today}"

    async def load(
        self,
        strategy_source: StrategySource,
        query: FinvizQuery,
    ) -> list[CandidateRecord] | None:
        payload = await self.client.get(self.key_for(strategy_source, query))
        if payload is None:
            return None
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")
        return _records_from_json(payload)

    async def store(
        self,
        strategy_source: StrategySource,
        query: FinvizQuery,
        rows: list[CandidateRecord],
    ) -> None:
        await self.client.set(
            self.key_for(strategy_source, query),
            _records_to_json(rows),
            ex=self.ttl_seconds,
        )


def _records_to_json(rows: list[CandidateRecord]) -> str:
    return json.dumps([_record_to_dict(row) for row in rows], separators=(",", ":"))


def _records_from_json(payload: str) -> list[CandidateRecord]:
    data = json.loads(payload)
    return [_record_from_dict(item) for item in data]


def _record_to_dict(row: CandidateRecord) -> dict[str, Any]:
    return {
        "ticker": row.ticker,
        "company_name": row.company_name,
        "market_cap": _encode_decimal(row.market_cap),
        "earnings_date": row.earnings_date.isoformat() if row.earnings_date else None,
        "current_price": _encode_decimal(row.current_price),
        "earnings_date_verified": row.earnings_date_verified,
        "screener_rank": row.screener_rank,
        "daily_change_percent": _encode_decimal(row.daily_change_percent),
        "volume": row.volume,
        "sector": row.sector,
        "sources": list(row.sources),
        "validation_notes": list(row.validation_notes),
        "strategy_source": row.strategy_source,
        "event_signal": _event_signal_to_dict(row.event_signal),
    }


def _record_from_dict(data: dict[str, Any]) -> CandidateRecord:
    earnings = data.get("earnings_date")
    return CandidateRecord(
        ticker=data["ticker"],
        company_name=data.get("company_name"),
        market_cap=_decode_decimal(data.get("market_cap")),
        earnings_date=date.fromisoformat(earnings) if earnings else None,
        current_price=_decode_decimal(data.get("current_price")),
        earnings_date_verified=bool(data.get("earnings_date_verified", True)),
        screener_rank=data.get("screener_rank"),
        daily_change_percent=_decode_decimal(data.get("daily_change_percent")),
        volume=data.get("volume"),
        sector=data.get("sector"),
        sources=tuple(data.get("sources", ())),
        validation_notes=tuple(data.get("validation_notes", ())),
        strategy_source=data.get("strategy_source"),
        event_signal=_event_signal_from_dict(data.get("event_signal")),
    )


def _event_signal_to_dict(signal: StrategyEventSignal | None) -> dict[str, Any] | None:
    if signal is None:
        return None
    return {
        "score": signal.score,
        "is_supportive": signal.is_supportive,
        "detail": signal.detail,
    }


def _event_signal_from_dict(data: Any) -> StrategyEventSignal | None:
    if not isinstance(data, dict):
        return None
    return StrategyEventSignal(
        score=int(data["score"]),
        is_supportive=bool(data["is_supportive"]),
        detail=str(data["detail"]),
    )


def _encode_decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _decode_decimal(value: str | None) -> Decimal | None:
    return None if value is None else Decimal(value)
