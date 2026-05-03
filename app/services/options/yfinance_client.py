from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.services.options.types import OptionContract


class YFinanceOptionsClient:
    def __init__(self, *, max_attempts: int = 2) -> None:
        self.max_attempts = max_attempts

    async def fetch_chain(
        self,
        ticker: str,
        *,
        expiry_window_days: int,
        today: date | None = None,
    ) -> tuple[OptionContract, ...]:
        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception_type((RuntimeError, TimeoutError)),
            reraise=True,
        ):
            with attempt:
                return await asyncio.to_thread(
                    self._fetch_chain_sync,
                    ticker,
                    expiry_window_days,
                    today,
                )

        raise RuntimeError("unreachable")

    def _fetch_chain_sync(
        self,
        ticker: str,
        expiry_window_days: int,
        today: date | None,
    ) -> tuple[OptionContract, ...]:
        try:
            import yfinance as yf  # type: ignore[import-untyped]
        except Exception as exc:  # pragma: no cover - import failure is environment-specific
            raise RuntimeError("yfinance import failed") from exc

        cutoff = (today or date.today()) + timedelta(days=max(expiry_window_days, 1))

        try:
            ticker_client = yf.Ticker(ticker)
            expiries = tuple(getattr(ticker_client, "options", ()) or ())
        except Exception as exc:
            raise RuntimeError(f"yfinance options listing failed for {ticker.upper()}") from exc

        contracts: list[OptionContract] = []
        for expiry_str in expiries:
            expiry = _parse_expiry(expiry_str)
            if expiry is None or expiry < (today or date.today()) or expiry > cutoff:
                continue

            try:
                chain = ticker_client.option_chain(expiry_str)
            except Exception as exc:
                raise RuntimeError(
                    f"yfinance option-chain fetch failed for {ticker.upper()} on {expiry_str}"
                ) from exc

            for row in _frame_to_rows(getattr(chain, "calls", None)):
                parsed = _build_contract(ticker.upper(), "call", expiry, row)
                if parsed is not None:
                    contracts.append(parsed)

            for row in _frame_to_rows(getattr(chain, "puts", None)):
                parsed = _build_contract(ticker.upper(), "put", expiry, row)
                if parsed is not None:
                    contracts.append(parsed)

        return tuple(contracts)


def _frame_to_rows(frame: Any) -> list[Mapping[str, Any]]:
    if frame is None or getattr(frame, "empty", False):
        return []

    if hasattr(frame, "to_dict"):
        try:
            rows = frame.to_dict("records")
            if isinstance(rows, Sequence):
                return [row for row in rows if isinstance(row, Mapping)]
        except Exception:
            return []

    if isinstance(frame, Sequence):
        return [row for row in frame if isinstance(row, Mapping)]

    return []


def _build_contract(
    ticker: str,
    option_type: str,
    expiry: date,
    row: Mapping[str, Any],
) -> OptionContract | None:
    strike = _to_decimal(row.get("strike"))
    if strike is None:
        return None

    bid = _to_decimal(row.get("bid"))
    ask = _to_decimal(row.get("ask"))
    mid = _compute_mid(bid, ask)
    spread_absolute = _compute_spread_absolute(bid, ask)
    spread_percent = _compute_spread_percent(bid, ask, mid)

    return OptionContract(
        ticker=ticker,
        option_type=option_type,  # type: ignore[arg-type]
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=mid,
        last_trade_price=_to_decimal(row.get("lastPrice")),
        volume=_to_int(row.get("volume")),
        open_interest=_to_int(row.get("openInterest")),
        implied_volatility=_to_decimal(row.get("impliedVolatility")),
        spread_absolute=spread_absolute,
        spread_percent=spread_percent,
        source="yfinance",
        symbol=_to_text(row.get("contractSymbol")),
    )


def _parse_expiry(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except ValueError:
        return None


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


def _compute_mid(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is not None and ask is not None:
        return (bid + ask) / Decimal("2")
    return ask or bid


def _compute_spread_absolute(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is None or ask is None:
        return None
    return ask - bid


def _compute_spread_percent(
    bid: Decimal | None,
    ask: Decimal | None,
    mid: Decimal | None,
) -> Decimal | None:
    if bid is None or ask is None or mid is None or mid <= 0:
        return None
    return (ask - bid) / mid
