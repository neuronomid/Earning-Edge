from __future__ import annotations

import re
from collections.abc import Mapping
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.services.options.types import OptionContract

DEFAULT_TIMEOUT = 15.0
OCC_PATTERN = re.compile(
    r"^(?P<root>[A-Z0-9]+)(?P<yy>\d{2})(?P<mm>\d{2})(?P<dd>\d{2})(?P<cp>[CP])(?P<strike>\d{8})$"
)


class AlpacaAuthenticationError(RuntimeError):
    """Raised when Alpaca credentials are rejected."""


class AlpacaUnavailableError(RuntimeError):
    """Raised when Alpaca cannot return a usable option chain."""


class AlpacaOptionsClient:
    BASE_URL = "https://data.alpaca.markets"
    SNAPSHOTS_PATH = "/v1beta1/options/snapshots/{underlying}"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        feed: str = "indicative",
        page_limit: int = 1000,
    ) -> None:
        self._client = client
        self.max_attempts = max_attempts
        self.feed = feed
        self.page_limit = page_limit

    async def fetch_chain(
        self,
        ticker: str,
        *,
        api_key: str,
        api_secret: str,
        expiry_window_days: int,
        today: date | None = None,
    ) -> tuple[OptionContract, ...]:
        if not api_key.strip() or not api_secret.strip():
            raise AlpacaAuthenticationError("Alpaca API key or secret is missing.")

        today = today or date.today()
        params = {
            "feed": self.feed,
            "limit": self.page_limit,
            "expiration_date_gte": today.isoformat(),
            "expiration_date_lte": (
                today + timedelta(days=max(expiry_window_days, 1))
            ).isoformat(),
        }

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception_type((AlpacaUnavailableError, httpx.HTTPError, TimeoutError)),
            reraise=True,
        ):
            with attempt:
                if self._client is not None:
                    return await self._fetch_with_client(
                        self._client,
                        ticker=ticker,
                        params=params,
                        api_key=api_key,
                        api_secret=api_secret,
                    )

                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    return await self._fetch_with_client(
                        client,
                        ticker=ticker,
                        params=params,
                        api_key=api_key,
                        api_secret=api_secret,
                    )

        raise AlpacaUnavailableError("unreachable")

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        ticker: str,
        params: Mapping[str, str | int],
        api_key: str,
        api_secret: str,
    ) -> tuple[OptionContract, ...]:
        url = self.BASE_URL + self.SNAPSHOTS_PATH.format(underlying=ticker.upper())
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }

        contracts: list[OptionContract] = []
        page_token: str | None = None
        while True:
            request_params = dict(params)
            if page_token:
                request_params["page_token"] = page_token

            payload = await self._request_json(client, url, headers, request_params)
            snapshots = payload.get("snapshots", {})
            if not isinstance(snapshots, Mapping):
                snapshots = {}

            for symbol, snapshot in snapshots.items():
                if not isinstance(snapshot, Mapping):
                    continue
                parsed = _build_contract(ticker.upper(), str(symbol), snapshot)
                if parsed is not None:
                    contracts.append(parsed)

            page_token = _to_text(payload.get("next_page_token"))
            if not page_token:
                return tuple(contracts)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Mapping[str, str],
        params: Mapping[str, str | int],
    ) -> dict[str, Any]:
        response = await client.get(url, headers=headers, params=params)
        if response.status_code in {401, 403}:
            raise AlpacaAuthenticationError(
                f"Alpaca rejected credentials: HTTP {response.status_code}"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AlpacaUnavailableError(
                f"Alpaca options request failed: HTTP {response.status_code}"
            ) from exc

        payload = response.json()
        if not isinstance(payload, dict):
            raise AlpacaUnavailableError("Alpaca returned a non-object options payload.")
        return payload


def _build_contract(
    ticker: str,
    symbol: str,
    snapshot: Mapping[str, Any],
) -> OptionContract | None:
    parsed_symbol = _parse_occ_symbol(symbol)
    if parsed_symbol is None:
        return None

    option_type, strike, expiry = parsed_symbol
    quote = _coerce_mapping(snapshot.get("latestQuote"))
    trade = _coerce_mapping(snapshot.get("latestTrade"))
    greeks = _coerce_mapping(snapshot.get("greeks"))
    daily_bar = _coerce_mapping(snapshot.get("dailyBar"))

    bid = _to_decimal(quote.get("bp"))
    ask = _to_decimal(quote.get("ap"))
    mid = _compute_mid(bid, ask)
    spread_absolute = _compute_spread_absolute(bid, ask)
    spread_percent = _compute_spread_percent(bid, ask, mid)

    return OptionContract(
        ticker=ticker,
        option_type=option_type,
        strike=strike,
        expiry=expiry,
        bid=bid,
        ask=ask,
        mid=mid,
        last_trade_price=_to_decimal(trade.get("p")),
        volume=_to_int(snapshot.get("volume")) or _to_int(daily_bar.get("v")),
        open_interest=_to_int(snapshot.get("open_interest") or snapshot.get("openInterest")),
        implied_volatility=_to_decimal(
            snapshot.get("impliedVolatility") or snapshot.get("implied_volatility")
        ),
        delta=_to_decimal(greeks.get("delta")),
        gamma=_to_decimal(greeks.get("gamma")),
        theta=_to_decimal(greeks.get("theta")),
        vega=_to_decimal(greeks.get("vega")),
        rho=_to_decimal(greeks.get("rho")),
        spread_absolute=spread_absolute,
        spread_percent=spread_percent,
        source="alpaca",
        symbol=symbol,
    )


def _parse_occ_symbol(symbol: str) -> tuple[str, Decimal, date] | None:
    match = OCC_PATTERN.match(symbol)
    if match is None:
        return None
    try:
        year = 2000 + int(match.group("yy"))
        month = int(match.group("mm"))
        day = int(match.group("dd"))
        option_type = "call" if match.group("cp") == "C" else "put"
        strike = Decimal(match.group("strike")) / Decimal("1000")
        return option_type, strike, date(year, month, day)
    except (InvalidOperation, ValueError):
        return None


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    try:
        coerced = dict(value)
    except Exception:
        return {}
    return coerced


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
