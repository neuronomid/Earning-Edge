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

        payload = await self._request_json(
            "/calendar/earnings",
            params={
                "from": window[0].isoformat(),
                "to": window[1].isoformat(),
            },
        )
        calendar_rows = payload.get("earningsCalendar", [])
        if not isinstance(calendar_rows, list):
            return []

        seen: set[str] = set()
        candidates: list[tuple[str, date]] = []
        for row in calendar_rows:
            symbol = str(row.get("symbol") or "").upper().strip()
            earnings_date = parse_date_value(str(row.get("date") or ""), today=window[0])
            if symbol == "" or earnings_date is None or symbol in seen:
                continue
            candidates.append((symbol, earnings_date))
            seen.add(symbol)

        enriched = await asyncio.gather(
            *[
                self._enrich_candidate(ticker=symbol, earnings_date=earnings_date)
                for symbol, earnings_date in candidates[: limit * 4]
            ],
            return_exceptions=True,
        )

        rows = [row for row in enriched if isinstance(row, CandidateRecord)]
        rows.sort(key=lambda item: item.market_cap or Decimal("0"), reverse=True)
        return rows[:limit]

    async def _lookup_earnings_date(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> date | None:
        payload = await self._request_json(
            "/calendar/earnings",
            params={
                "from": window[0].isoformat(),
                "to": window[1].isoformat(),
            },
        )
        rows = payload.get("earningsCalendar", [])
        if not isinstance(rows, list):
            return None
        symbol = ticker.upper()
        for row in rows:
            if str(row.get("symbol") or "").upper().strip() != symbol:
                continue
            return parse_date_value(str(row.get("date") or ""), today=window[0])
        return None

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

        company_name = _to_text(profile_payload.get("name"))
        market_cap = _market_cap_to_decimal(profile_payload.get("marketCapitalization"))
        sector = _to_text(profile_payload.get("finnhubIndustry"))
        current_price = _to_decimal(quote_payload.get("c"))
        daily_change_percent = _to_decimal(quote_payload.get("dp"))

        if company_name is None and market_cap is None and current_price is None:
            return None

        return CandidateRecord(
            ticker=ticker.upper(),
            company_name=company_name,
            market_cap=market_cap,
            earnings_date=earnings_date,
            current_price=current_price,
            daily_change_percent=daily_change_percent,
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
