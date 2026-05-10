from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from app.services.news.sources import FinnhubNewsSource, SecEdgarNewsSource

pytestmark = pytest.mark.asyncio


@respx.mock
async def test_finnhub_news_source_builds_articles_from_company_news() -> None:
    respx.get("https://finnhub.io/api/v1/company-news").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "headline": "Cisco Stock Finds New Growth In AI Infrastructure",
                    "summary": "Cisco stayed near highs ahead of earnings.",
                    "url": "https://example.com/csco-ai",
                    "source": "Yahoo",
                    "datetime": 1778251903,
                },
                {
                    "headline": "Missing url row",
                    "summary": "Should be ignored.",
                    "source": "Yahoo",
                    "datetime": 1778251903,
                },
            ],
        )
    )

    async with httpx.AsyncClient(base_url="https://finnhub.io/api/v1") as client:
        source = FinnhubNewsSource(
            api_key="token",
            client=client,
            today_provider=lambda: date(2026, 5, 10),
        )
        articles = await source.fetch_ticker("CSCO", company_name="Cisco Systems")

    assert len(articles) == 1
    assert articles[0].title == "Cisco Stock Finds New Growth In AI Infrastructure"
    assert articles[0].source == "Yahoo"
    assert articles[0].snippet == "Cisco stayed near highs ahead of earnings."


@respx.mock
async def test_sec_edgar_news_source_filters_current_year_filings() -> None:
    respx.get("https://www.sec.gov/files/company_tickers.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "0": {"ticker": "CSCO", "cik_str": 858877, "title": "Cisco Systems, Inc."},
            },
        )
    )
    respx.get("https://data.sec.gov/submissions/CIK0000858877.json").mock(
        return_value=httpx.Response(
            200,
            json={
                "name": "Cisco Systems, Inc.",
                "filings": {
                    "recent": {
                        "form": ["8-K", "4", "8-K", "S-8"],
                        "filingDate": ["2026-05-01", "2026-04-13", "2025-12-20", "2026-03-01"],
                        "reportDate": ["2026-04-27", "2026-04-10", "2025-12-18", "2026-03-01"],
                        "accessionNumber": [
                            "0000858877-26-000057",
                            "0000858877-26-000054",
                            "0000858877-25-000099",
                            "0000858877-26-000011",
                        ],
                        "primaryDocument": [
                            "csco-20260427.htm",
                            "form4.xml",
                            "old.htm",
                            "ignore.htm",
                        ],
                    }
                },
            },
        )
    )

    source = SecEdgarNewsSource(
        user_agent="Earning-Edge/1.0 (contact: ops@example.com)",
        today_provider=lambda: date(2026, 5, 10),
    )
    articles = await source.fetch_ticker("CSCO", company_name="Cisco Systems")

    assert [article.title for article in articles] == [
        "Cisco Systems, Inc. 8-K filed on 2026-05-01",
        "Cisco Systems, Inc. 4 filed on 2026-04-13",
    ]
    assert articles[0].url.endswith("/csco-20260427.htm")
    assert articles[1].source == "SEC EDGAR"
