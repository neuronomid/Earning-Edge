from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.services.market_data.types import PriceBar, SecuritySnapshot


class YFinanceClient:
    def __init__(self, *, history_period: str = "6mo", max_attempts: int = 3) -> None:
        self.history_period = history_period
        self.max_attempts = max_attempts

    async def fetch_security(self, ticker: str) -> SecuritySnapshot:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception_type((RuntimeError, TimeoutError)),
            reraise=True,
        ):
            with attempt:
                return await asyncio.to_thread(self._fetch_security_sync, ticker)

        raise RuntimeError("unreachable")

    def _fetch_security_sync(self, ticker: str) -> SecuritySnapshot:
        try:
            import yfinance as yf  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - import failure is environment-specific
            raise RuntimeError("yfinance import failed") from exc

        try:
            ticker_client = yf.Ticker(ticker)
            fast_info = _coerce_mapping(getattr(ticker_client, "fast_info", None))
            info = _coerce_mapping(getattr(ticker_client, "info", None))
            history = _extract_history(
                ticker_client.history(period=self.history_period, auto_adjust=False)
            )
        except Exception as exc:
            raise RuntimeError(f"yfinance request failed for {ticker.upper()}") from exc

        current_price = _to_decimal(
            fast_info.get("lastPrice")
            or fast_info.get("regularMarketPrice")
            or info.get("currentPrice")
            or info.get("regularMarketPrice")
        )
        if current_price is None and history:
            current_price = history[-1].close

        return SecuritySnapshot(
            ticker=ticker.upper(),
            company_name=_to_text(info.get("shortName") or info.get("longName")),
            sector=_to_text(info.get("sector")),
            market_cap=_to_decimal(fast_info.get("marketCap") or info.get("marketCap")),
            current_price=current_price,
            history=history,
        )


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    try:
        coerced = dict(value)
    except Exception:
        return {}
    return coerced


def _extract_history(frame: Any) -> tuple[PriceBar, ...]:
    if frame is None or getattr(frame, "empty", True):
        return ()

    bars: list[PriceBar] = []
    iterrows = getattr(frame, "iterrows", None)
    if not callable(iterrows):
        return ()

    for idx, row in iterrows():
        close = _to_decimal(row.get("Close"))
        if close is None:
            continue
        bar_date = _to_date(idx)
        if bar_date is None:
            continue
        bars.append(
            PriceBar(
                date=bar_date,
                close=close,
                volume=_to_int(row.get("Volume")),
            )
        )

    bars.sort(key=lambda item: item.date)
    return tuple(bars)


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    converted = _to_decimal(value)
    return None if converted is None else int(converted)


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _to_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        text = str(value)
        return datetime.fromisoformat(text).date()
    except ValueError:
        return None
