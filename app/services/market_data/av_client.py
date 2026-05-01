from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.services.market_data.types import (
    AlphaVantageSnapshot,
    NewsSentimentSummary,
    PriceBar,
)

DEFAULT_TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class AlphaVantageClient:
    URL = "https://www.alphavantage.co/query"

    def __init__(
        self,
        client: httpx.AsyncClient | None = None,
        *,
        max_attempts: int = 3,
    ) -> None:
        self._client = client
        self.max_attempts = max_attempts

    async def fetch_snapshot(self, ticker: str, *, api_key: str) -> AlphaVantageSnapshot | None:
        if not api_key.strip():
            return None

        if self._client is not None:
            return await self._fetch_with_client(self._client, ticker, api_key=api_key.strip())

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            return await self._fetch_with_client(client, ticker, api_key=api_key.strip())

    async def _fetch_with_client(
        self,
        client: httpx.AsyncClient,
        ticker: str,
        *,
        api_key: str,
    ) -> AlphaVantageSnapshot | None:
        overview = await self._request_json(
            client,
            {
                "function": "OVERVIEW",
                "symbol": ticker.upper(),
                "apikey": api_key,
            },
        )
        daily = await self._request_json(
            client,
            {
                "function": "TIME_SERIES_DAILY",
                "symbol": ticker.upper(),
                "outputsize": "compact",
                "apikey": api_key,
            },
        )
        news = await self._request_json(
            client,
            {
                "function": "NEWS_SENTIMENT",
                "tickers": ticker.upper(),
                "sort": "LATEST",
                "limit": "10",
                "apikey": api_key,
            },
        )

        if overview is None and daily is None and news is None:
            return None

        company_name, sector, market_cap = _parse_overview(overview)
        history = _parse_daily_series(daily)
        news_sentiment = _parse_news_sentiment(news)

        return AlphaVantageSnapshot(
            ticker=ticker.upper(),
            company_name=company_name,
            sector=sector,
            market_cap=market_cap,
            history=history,
            news_sentiment=news_sentiment,
        )

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        params: dict[str, str],
    ) -> dict[str, Any] | None:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self.max_attempts),
                wait=wait_exponential(multiplier=0.25, min=0.25, max=2),
                retry=retry_if_exception_type(httpx.HTTPError),
                reraise=True,
            ):
                with attempt:
                    response = await client.get(self.URL, params=params)
                    response.raise_for_status()
                    payload = response.json()
                    if not isinstance(payload, dict):
                        return None
                    if "Note" in payload or "Information" in payload:
                        return None
                    if "Error Message" in payload:
                        return None
                    return payload
        except (ValueError, httpx.HTTPError):
            return None

        return None


def _parse_overview(
    payload: Mapping[str, Any] | None,
) -> tuple[str | None, str | None, Decimal | None]:
    if payload is None:
        return None, None, None
    return (
        _to_text(payload.get("Name")),
        _to_text(payload.get("Sector")),
        _to_decimal(payload.get("MarketCapitalization")),
    )


def _parse_daily_series(payload: Mapping[str, Any] | None) -> tuple[PriceBar, ...]:
    if payload is None:
        return ()

    series = payload.get("Time Series (Daily)")
    if not isinstance(series, Mapping):
        return ()

    bars: list[PriceBar] = []
    for entry_date, values in series.items():
        if not isinstance(values, Mapping):
            continue
        close = _to_decimal(values.get("4. close") or values.get("5. adjusted close"))
        if close is None:
            continue
        try:
            bar_date = date.fromisoformat(str(entry_date))
        except ValueError:
            continue
        bars.append(
            PriceBar(
                date=bar_date,
                close=close,
                volume=_to_int(values.get("5. volume") or values.get("6. volume")),
            )
        )

    bars.sort(key=lambda item: item.date)
    return tuple(bars)


def _parse_news_sentiment(payload: Mapping[str, Any] | None) -> NewsSentimentSummary | None:
    if payload is None:
        return None

    feed = payload.get("feed")
    if not isinstance(feed, list) or not feed:
        return None

    scores: list[Decimal] = []
    labels: Counter[str] = Counter()
    for item in feed:
        if not isinstance(item, Mapping):
            continue
        score = _to_decimal(item.get("overall_sentiment_score"))
        if score is not None:
            scores.append(score)
        label = _to_text(item.get("overall_sentiment_label"))
        if label is not None:
            labels.update([label])

    if not scores and not labels:
        return None

    average_score = None
    if scores:
        average_score = sum(scores) / Decimal(len(scores))

    overall = labels.most_common(1)[0][0] if labels else None
    return NewsSentimentSummary(
        article_count=len(feed),
        average_sentiment=average_score,
        overall_sentiment=overall,
    )


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
