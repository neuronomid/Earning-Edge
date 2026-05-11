from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx
from httpx import Response

from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource

pytestmark = pytest.mark.asyncio


@respx.mock
async def test_finnhub_source_caches_calendar_by_window() -> None:
    calendar_route = respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=Response(
            200,
            json={
                "earningsCalendar": [
                    {"symbol": "AAA", "date": "2026-05-08"},
                    {"symbol": "BBB", "date": "2026-05-09"},
                ]
            },
        )
    )
    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=Response(
            200,
            json={
                "name": "Example Corp",
                "marketCapitalization": 3000,
                "finnhubIndustry": "Technology",
            },
        )
    )
    respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=Response(
            200,
            json={"c": 100.0, "dp": 1.5},
        )
    )

    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1") as client:
        source = FinnhubEarningsSource(api_key="token", client=client)
        window = (date(2026, 5, 4), date(2026, 5, 17))

        first = await source.get_candidate_details("AAA", window=window)
        second = await source.get_candidate_details("BBB", window=window)

    assert first is not None
    assert second is not None
    assert first.earnings_date == date(2026, 5, 8)
    assert second.earnings_date == date(2026, 5, 9)
    assert calendar_route.call_count == 1


@respx.mock
async def test_finnhub_source_reuses_calendar_cache_for_upcoming_candidates() -> None:
    calendar_route = respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=Response(
            200,
            json={
                "earningsCalendar": [
                    {"symbol": "AAA", "date": "2026-05-08"},
                    {"symbol": "BBB", "date": "2026-05-09"},
                    {"symbol": "CCC", "date": "2026-05-10"},
                ]
            },
        )
    )
    profile_route = respx.get("https://finnhub.io/api/v1/stock/profile2").mock(
        return_value=Response(
            200,
            json={
                "name": "Example Corp",
                "marketCapitalization": 3000,
                "finnhubIndustry": "Technology",
                "exchange": "NASDAQ",
            },
        )
    )
    quote_route = respx.get("https://finnhub.io/api/v1/quote").mock(
        return_value=Response(
            200,
            json={"c": 100.0, "dp": 1.5},
        )
    )

    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1") as client:
        source = FinnhubEarningsSource(api_key="token", client=client)
        window = (date(2026, 5, 4), date(2026, 5, 17))

        await source.get_candidate_details("AAA", window=window)
        rows = await source.list_upcoming_candidates(window=window, limit=1)

    assert len(rows) == 1
    assert calendar_route.call_count == 1
    assert profile_route.call_count == 4
    assert quote_route.call_count == 4


@respx.mock
async def test_finnhub_source_upcoming_candidates_rank_later_large_caps_and_filter_low_price() -> (
    None
):
    respx.get("https://finnhub.io/api/v1/calendar/earnings").mock(
        return_value=Response(
            200,
            json={
                "earningsCalendar": [
                    {"symbol": "AAA", "date": "2026-05-08"},
                    {"symbol": "BBB", "date": "2026-05-09"},
                    {"symbol": "CCC", "date": "2026-05-10"},
                    {"symbol": "DDD", "date": "2026-05-11"},
                ]
            },
        )
    )

    def profile_responder(request: httpx.Request) -> Response:
        symbol = request.url.params["symbol"]
        payloads = {
            "AAA": {
                "name": "AAA Corp",
                "marketCapitalization": 3000,
                "finnhubIndustry": "Technology",
                "exchange": "NASDAQ",
            },
            "BBB": {
                "name": "BBB Corp",
                "marketCapitalization": 2800,
                "finnhubIndustry": "Technology",
                "exchange": "NYSE",
            },
            "CCC": {
                "name": "CCC Corp",
                "marketCapitalization": 8000,
                "finnhubIndustry": "Technology",
                "exchange": "NASDAQ",
            },
            "DDD": {
                "name": "DDD Corp",
                "marketCapitalization": 9000,
                "finnhubIndustry": "Technology",
                "exchange": "NASDAQ",
            },
        }
        return Response(200, json=payloads[symbol])

    def quote_responder(request: httpx.Request) -> Response:
        symbol = request.url.params["symbol"]
        payloads = {
            "AAA": {"c": 25, "dp": 1.5, "v": 2_000_000},
            "BBB": {"c": 28, "dp": 1.2, "v": 2_500_000},
            "CCC": {"c": 35, "dp": 2.1, "v": 3_000_000},
            "DDD": {"c": 10, "dp": 0.8, "v": 4_000_000},
        }
        return Response(200, json=payloads[symbol])

    respx.get("https://finnhub.io/api/v1/stock/profile2").mock(side_effect=profile_responder)
    respx.get("https://finnhub.io/api/v1/quote").mock(side_effect=quote_responder)

    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1") as client:
        source = FinnhubEarningsSource(api_key="token", client=client)
        rows = await source.list_upcoming_candidates(
            window=(date(2026, 5, 4), date(2026, 5, 17)),
            limit=2,
        )

    assert [row.ticker for row in rows] == ["CCC", "AAA"]
