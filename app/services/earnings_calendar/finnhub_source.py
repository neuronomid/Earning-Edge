from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.services.candidate_models import CandidateRecord
from app.services.parsing import parse_date_value

BACKUP_MIN_MARKET_CAP = Decimal("2000000000")
BACKUP_MIN_PRICE = Decimal("20")


class FinnhubEarningsSource:
    BASE_URL = "https://finnhub.io/api/v1"
    name = "finnhub"

    def __init__(
        self,
        api_key: str = "",
        *,
        client: httpx.AsyncClient | None = None,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client
        self.today_provider = today_provider or date.today
        self._earnings_calendar_cache: dict[tuple[date, date], dict[str, date]] = {}

    async def get_candidate_details(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None:
        if self.api_key == "":
            return None

        earnings_date = await self._lookup_earnings_date(ticker, window=window)
        return await self._enrich_candidate(
            ticker=ticker,
            earnings_date=earnings_date,
        )

    async def list_upcoming_candidates(
        self,
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]:
        if self.api_key == "":
            return []

        calendar = await self._load_calendar(window=window)
        if not calendar:
            return []

        candidates = list(calendar.items())
        profile_limit = min(len(candidates), max(limit * 16, 64))
        profiled = await asyncio.gather(
            *[
                self._request_json("/stock/profile2", params={"symbol": symbol})
                for symbol, _ in candidates[:profile_limit]
            ],
            return_exceptions=True,
        )

        ranked: list[tuple[str, date, dict[str, Any]]] = []
        for (symbol, earnings_date), payload in zip(
            candidates[:profile_limit], profiled, strict=True
        ):
            if not isinstance(payload, dict):
                continue
            market_cap = _market_cap_to_decimal(payload.get("marketCapitalization"))
            if market_cap is None or market_cap < BACKUP_MIN_MARKET_CAP:
                continue
            if not _is_allowed_exchange(payload.get("exchange")):
                continue
            ranked.append((symbol, earnings_date, payload))

        ranked.sort(
            key=lambda item: (
                _market_cap_to_decimal(item[2].get("marketCapitalization")) or Decimal("0")
            ),
            reverse=True,
        )
        quote_limit = max(limit * 3, 12)

        shortlisted = ranked[:quote_limit]
        quotes = await asyncio.gather(
            *[
                self._request_json("/quote", params={"symbol": symbol})
                for symbol, _, _ in shortlisted
            ],
            return_exceptions=True,
        )
        enriched = [
            self._build_candidate(
                ticker=symbol,
                earnings_date=earnings_date,
                profile_payload=profile_payload,
                quote_payload=quote_payload,
            )
            if isinstance(quote_payload, dict)
            else quote_payload
            for (symbol, earnings_date, profile_payload), quote_payload in zip(
                shortlisted,
                quotes,
                strict=True,
            )
        ]

        rows = [
            row
            for row in enriched
            if isinstance(row, CandidateRecord) and _is_viable_backup_candidate(row)
        ]
        rows.sort(key=lambda item: item.market_cap or Decimal("0"), reverse=True)
        return rows[:limit]

    async def _lookup_earnings_date(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> date | None:
        calendar = await self._load_calendar(window=window)
        return calendar.get(ticker.upper())

    async def _load_calendar(
        self,
        *,
        window: tuple[date, date],
    ) -> dict[str, date]:
        cached = self._earnings_calendar_cache.get(window)
        if cached is not None:
            return cached

        payload = await self._request_json(
            "/calendar/earnings",
            params={
                "from": window[0].isoformat(),
                "to": window[1].isoformat(),
            },
        )
        rows = payload.get("earningsCalendar", [])
        if not isinstance(rows, list):
            self._earnings_calendar_cache[window] = {}
            return {}

        calendar: dict[str, date] = {}
        for row in rows:
            symbol = str(row.get("symbol") or "").upper().strip()
            earnings_date = parse_date_value(str(row.get("date") or ""), today=window[0])
            if symbol and earnings_date is not None and symbol not in calendar:
                calendar[symbol] = earnings_date
        self._earnings_calendar_cache[window] = calendar
        return calendar

    async def _enrich_candidate(
        self,
        *,
        ticker: str,
        earnings_date: date | None,
    ) -> CandidateRecord | None:
        profile_payload, quote_payload = await asyncio.gather(
            self._request_json("/stock/profile2", params={"symbol": ticker}),
            self._request_json("/quote", params={"symbol": ticker}),
        )
        return self._build_candidate(
            ticker=ticker,
            earnings_date=earnings_date,
            profile_payload=profile_payload,
            quote_payload=quote_payload,
        )

    def _build_candidate(
        self,
        *,
        ticker: str,
        earnings_date: date | None,
        profile_payload: dict[str, Any],
        quote_payload: dict[str, Any],
    ) -> CandidateRecord | None:

        company_name = _to_text(profile_payload.get("name"))
        market_cap = _market_cap_to_decimal(profile_payload.get("marketCapitalization"))
        sector = _to_text(profile_payload.get("finnhubIndustry"))
        current_price = _to_decimal(quote_payload.get("c"))
        daily_change_percent = _to_decimal(quote_payload.get("dp"))
        volume = _to_int(quote_payload.get("v"))

        if company_name is None and market_cap is None and current_price is None:
            return None

        return CandidateRecord(
            ticker=ticker.upper(),
            company_name=company_name,
            market_cap=market_cap,
            earnings_date=earnings_date,
            current_price=current_price,
            daily_change_percent=daily_change_percent,
            volume=volume,
            sector=sector,
            sources=(self.name,),
        )

    async def _request_json(self, path: str, *, params: dict[str, str]) -> dict[str, Any]:
        async with self._client() as client:
            response = await client.get(
                path,
                params={**params, "token": self.api_key},
            )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                return {}
            return payload

    @asynccontextmanager
    async def _client(self) -> AsyncIterator[httpx.AsyncClient]:
        if self.client is not None:
            yield self.client
            return

        async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=20.0) as client:
            yield client


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _market_cap_to_decimal(value: Any) -> Decimal | None:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return None
    return decimal_value * Decimal("1000000")


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_int(value: Any) -> int | None:
    decimal_value = _to_decimal(value)
    return None if decimal_value is None else int(decimal_value)


def _is_allowed_exchange(value: Any) -> bool:
    exchange = _to_text(value)
    if exchange is None:
        return True
    upper = exchange.upper()
    return "NASDAQ" in upper or "NYSE" in upper


def _is_viable_backup_candidate(row: CandidateRecord) -> bool:
    if row.market_cap is None or row.market_cap < BACKUP_MIN_MARKET_CAP:
        return False
    if row.current_price is None or row.current_price < BACKUP_MIN_PRICE:
        return False
    return True
