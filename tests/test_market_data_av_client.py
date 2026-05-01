from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.services.market_data.av_client import AlphaVantageClient

pytestmark = pytest.mark.asyncio


@respx.mock
async def test_alpha_vantage_client_parses_overview_history_and_news() -> None:
    def responder(request: httpx.Request) -> httpx.Response:
        function = request.url.params["function"]
        if function == "OVERVIEW":
            return httpx.Response(
                200,
                json={
                    "Name": "Advanced Micro Devices",
                    "Sector": "Technology",
                    "MarketCapitalization": "250000000000",
                },
            )
        if function == "TIME_SERIES_DAILY":
            return httpx.Response(
                200,
                json={
                    "Time Series (Daily)": {
                        "2026-05-01": {"4. close": "154.20", "5. volume": "12345"},
                        "2026-04-30": {"4. close": "150.00", "5. volume": "12000"},
                    }
                },
            )
        if function == "NEWS_SENTIMENT":
            return httpx.Response(
                200,
                json={
                    "feed": [
                        {
                            "overall_sentiment_score": "0.40",
                            "overall_sentiment_label": "Bullish",
                        },
                        {
                            "overall_sentiment_score": "0.20",
                            "overall_sentiment_label": "Bullish",
                        },
                    ]
                },
            )
        raise AssertionError(f"unexpected Alpha Vantage function: {function}")

    respx.get(AlphaVantageClient.URL).mock(side_effect=responder)

    snapshot = await AlphaVantageClient().fetch_snapshot("amd", api_key="av-key")

    assert snapshot is not None
    assert snapshot.ticker == "AMD"
    assert snapshot.company_name == "Advanced Micro Devices"
    assert snapshot.sector == "Technology"
    assert snapshot.market_cap == Decimal("250000000000")
    assert [bar.close for bar in snapshot.history] == [Decimal("150.00"), Decimal("154.20")]
    assert snapshot.news_sentiment is not None
    assert snapshot.news_sentiment.article_count == 2
    assert snapshot.news_sentiment.average_sentiment == Decimal("0.30")
    assert snapshot.news_sentiment.overall_sentiment == "Bullish"


@respx.mock
async def test_alpha_vantage_client_returns_none_on_rate_limit_payload() -> None:
    respx.get(AlphaVantageClient.URL).mock(
        return_value=httpx.Response(200, json={"Note": "slow down"})
    )

    snapshot = await AlphaVantageClient().fetch_snapshot("amd", api_key="av-key")

    assert snapshot is None
