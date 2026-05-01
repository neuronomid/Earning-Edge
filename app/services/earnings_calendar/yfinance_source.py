from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.candidate_models import CandidateRecord
from app.services.tradingview.parser import parse_date_value


class YFinanceEarningsSource:
    name = "yfinance"

    def __init__(self, *, today_provider: Callable[[], date] | None = None) -> None:
        self.today_provider = today_provider or date.today

    async def get_candidate_details(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None:
        del window
        return await asyncio.to_thread(self._get_candidate_details_sync, ticker)

    async def list_upcoming_candidates(
        self,
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]:
        del window, limit
        return []

    def _get_candidate_details_sync(self, ticker: str) -> CandidateRecord | None:
        import yfinance as yf  # type: ignore[import-untyped]

        ticker_client = yf.Ticker(ticker)
        fast_info = _coerce_mapping(getattr(ticker_client, "fast_info", None))
        info = _coerce_mapping(getattr(ticker_client, "info", None))

        current_price = _to_decimal(
            fast_info.get("lastPrice")
            or fast_info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("regularMarketPrice")
        )
        market_cap = _to_decimal(fast_info.get("marketCap") or info.get("marketCap"))
        volume = _to_int(fast_info.get("lastVolume") or info.get("volume"))
        sector = _to_text(info.get("sector"))
        company_name = _to_text(info.get("shortName") or info.get("longName"))
        earnings_date = _extract_earnings_date(ticker_client, today=self.today_provider())

        if company_name is None and market_cap is None and current_price is None:
            return None

        return CandidateRecord(
            ticker=ticker.upper(),
            company_name=company_name,
            market_cap=market_cap,
            earnings_date=earnings_date,
            current_price=current_price,
            volume=volume,
            sector=sector,
            sources=(self.name,),
        )


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        return dict(value)
    except Exception:
        return {}


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    decimal_value = _to_decimal(value)
    return None if decimal_value is None else int(decimal_value)


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _extract_earnings_date(ticker_client: Any, *, today: date) -> date | None:
    get_earnings_dates = getattr(ticker_client, "get_earnings_dates", None)
    if callable(get_earnings_dates):
        try:
            frame = get_earnings_dates(limit=6)
        except Exception:
            frame = None
        candidate = _extract_earnings_date_from_frame(frame, today=today)
        if candidate is not None:
            return candidate

    try:
        calendar = ticker_client.calendar
    except Exception:
        calendar = None
    return _extract_earnings_date_from_calendar(calendar, today=today)


def _extract_earnings_date_from_frame(frame: Any, *, today: date) -> date | None:
    if frame is None:
        return None

    index = getattr(frame, "index", None)
    if index is not None:
        for item in index:
            candidate = _date_from_any(item, today=today)
            if candidate is not None and candidate >= today:
                return candidate
    return None


def _extract_earnings_date_from_calendar(calendar: Any, *, today: date) -> date | None:
    if calendar is None:
        return None

    if isinstance(calendar, dict):
        candidate = calendar.get("Earnings Date")
        return _date_from_any(candidate, today=today)

    to_dict = getattr(calendar, "to_dict", None)
    if callable(to_dict):
        try:
            values = to_dict()
        except Exception:
            values = None
        if isinstance(values, dict):
            candidate = values.get("Earnings Date")
            return _date_from_any(candidate, today=today)
    return None


def _date_from_any(value: Any, *, today: date) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (list, tuple)):
        for item in value:
            candidate = _date_from_any(item, today=today)
            if candidate is not None:
                return candidate
        return None
    iso_candidate = parse_date_value(str(value), today=today)
    return iso_candidate
