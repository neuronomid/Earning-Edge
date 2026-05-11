from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.services.market_data.alpaca_stock_client import AlpacaStockClient

pytestmark = pytest.mark.asyncio


@respx.mock
async def test_alpaca_stock_client_parses_latest_quote() -> None:
    respx.get("https://data.alpaca.markets/v2/stocks/quotes/latest").mock(
        return_value=httpx.Response(
            200,
            json={
                "quotes": {
                    "AMD": {
                        "bp": 123.40,
                        "ap": 123.46,
                        "t": "2026-05-08T14:30:00Z",
                    }
                }
            },
        )
    )

    quote = await AlpacaStockClient().fetch_quote(
        "amd",
        api_key="alpaca-key",
        api_secret="alpaca-secret",
        feed="iex",
    )

    assert quote.symbol == "AMD"
    assert quote.bid == Decimal("123.4")
    assert quote.ask == Decimal("123.46")
    assert quote.price == Decimal("123.43")
    assert quote.feed == "iex"
    assert quote.timestamp == "2026-05-08T14:30:00Z"
