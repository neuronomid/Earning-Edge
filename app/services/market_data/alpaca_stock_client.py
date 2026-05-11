from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

DEFAULT_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class AlpacaStockAuthenticationError(RuntimeError):
    """Raised when Alpaca rejects stock-data credentials."""


class AlpacaStockUnavailableError(RuntimeError):
    """Raised when Alpaca cannot return a usable stock quote."""


@dataclass(slots=True, frozen=True)
class AlpacaStockQuote:
    symbol: str
    bid: Decimal | None
    ask: Decimal | None
    price: Decimal | None
    timestamp: str | None
    feed: str


class AlpacaStockClient:
    BASE_URL = "https://data.alpaca.markets"
    LATEST_QUOTES_PATH = "/v2/stocks/quotes/latest"

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        max_attempts: int = 2,
        feed: str = "iex",
    ) -> None:
        self._client = client
        self.max_attempts = max_attempts
        self.feed = feed

    async def fetch_quote(
        self,
        symbol: str,
        *,
        api_key: str,
        api_secret: str,
        feed: str | None = None,
    ) -> AlpacaStockQuote:
        if not api_key.strip() or not api_secret.strip():
            raise AlpacaStockAuthenticationError("Alpaca API key or secret is missing.")

        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")

        selected_feed = (feed or self.feed).strip().lower()
        params = {"symbols": normalized, "feed": selected_feed}

        async for attempt in AsyncRetrying(
            stop=stop_after_attempt(self.max_attempts),
            wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
            retry=retry_if_exception_type((AlpacaStockUnavailableError, httpx.HTTPError)),
            reraise=True,
        ):
            with attempt:
                if self._client is not None:
                    return await self._fetch_with_client(
                        self._client,
                        symbol=normalized,
                        params=params,
                        api_key=api_key,
                        api_secret=api_secret,
                        feed=selected_feed,
                    )
                async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                    return await self._fetch_with_client(
                        client,
                        symbol=normalized,
                        params=params,
                        api_key=api_key,
                        api_secret=api_secret,
                        feed=selected_feed,
                    )

        raise AlpacaStockUnavailableError("unreachable")

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        *,
        symbol: str,
        params: Mapping[str, str],
        api_key: str,
        api_secret: str,
        feed: str,
    ) -> AlpacaStockQuote:
        headers = {
            "APCA-API-KEY-ID": api_key,
            "APCA-API-SECRET-KEY": api_secret,
            "Accept": "application/json",
        }
        response = await client.get(
            self.BASE_URL + self.LATEST_QUOTES_PATH,
            headers=headers,
            params=params,
        )
        if response.status_code in {401, 403}:
            raise AlpacaStockAuthenticationError(
                f"Alpaca rejected credentials or feed access: HTTP {response.status_code}"
            )
        try:
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AlpacaStockUnavailableError(
                f"Alpaca stock quote request failed: HTTP {response.status_code}"
            ) from exc

        payload = response.json()
        if not isinstance(payload, Mapping):
            raise AlpacaStockUnavailableError("Alpaca returned a non-object stock payload.")
        quote = _extract_quote(payload, symbol)
        if quote is None:
            raise AlpacaStockUnavailableError(f"Alpaca returned no quote for {symbol}.")
        bid = _positive_decimal(quote.get("bp"))
        ask = _positive_decimal(quote.get("ap"))
        price = _midpoint(bid, ask) or ask or bid
        if price is None:
            raise AlpacaStockUnavailableError(f"Alpaca quote for {symbol} had no bid/ask.")
        return AlpacaStockQuote(
            symbol=symbol,
            bid=bid,
            ask=ask,
            price=price,
            timestamp=_to_text(quote.get("t")),
            feed=feed,
        )


def _extract_quote(payload: Mapping[str, Any], symbol: str) -> Mapping[str, Any] | None:
    quotes = payload.get("quotes")
    if isinstance(quotes, Mapping):
        raw = quotes.get(symbol) or quotes.get(symbol.upper())
        return raw if isinstance(raw, Mapping) else None
    quote = payload.get("quote")
    return quote if isinstance(quote, Mapping) else None


def _midpoint(bid: Decimal | None, ask: Decimal | None) -> Decimal | None:
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        return (bid + ask) / Decimal("2")
    return None


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _positive_decimal(value: Any) -> Decimal | None:
    converted = _to_decimal(value)
    if converted is None or converted <= 0:
        return None
    return converted


def _to_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
