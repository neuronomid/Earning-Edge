from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

import pytest

from app.core.config import Settings
from app.services.activist_13d_service import Activist13DCandidateService
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.sec.filings_client import FilingHeader

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 5, 14)


_BASE_ACTIVE_BODY = """
<html><body>
<p>Cover page: The Reporting Person beneficially owns {stake}% of the outstanding shares.</p>
<h2>Item 4. Purpose of Transaction</h2>
<p>The Reporting Persons intend to engage in engagement with management, including
proposals around strategic alternatives and operational changes; they may seek board
representation.</p>
<h2>Item 5. Interest in Securities of the Issuer</h2>
</body></html>
"""


@dataclass
class FakeFilingsClient:
    tier1: tuple[FilingHeader, ...] = ()
    tier2: tuple[FilingHeader, ...] = ()
    tier3: tuple[FilingHeader, ...] = ()
    documents: dict[str, str] = field(default_factory=dict)
    ticker_for_cik: dict[str, str] = field(default_factory=dict)
    document_calls: list[str] = field(default_factory=list)
    tier_calls: list[tuple[str, int]] = field(default_factory=list)
    raise_on: dict[Literal["SC 13D", "SC 13D/A"], Exception] = field(default_factory=dict)

    async def fetch_recent_filings(
        self,
        *,
        form_type: Literal["SC 13D", "SC 13D/A"],
        lookback_days: int,
    ) -> tuple[FilingHeader, ...]:
        self.tier_calls.append((form_type, lookback_days))
        if form_type in self.raise_on:
            raise self.raise_on[form_type]
        if form_type == "SC 13D":
            if lookback_days <= 5:
                return self.tier1
            return self.tier3
        return self.tier2

    async def fetch_filing_document(self, accession: str, primary_doc: str, *, cik: str) -> str:
        del primary_doc, cik
        self.document_calls.append(accession)
        return self.documents.get(accession, "")

    async def resolve_ticker(self, cik: str) -> str | None:
        return self.ticker_for_cik.get(cik)


@dataclass
class FakeMarketData:
    snapshots: dict[str, MarketSnapshot]
    fetch_failures: dict[str, Exception] = field(default_factory=dict)

    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot:
        del alpha_vantage_api_key, refresh
        if ticker in self.fetch_failures:
            raise self.fetch_failures[ticker]
        return self.snapshots[ticker]


def _header(
    *,
    accession: str,
    cik: str = "0000111111",
    form: Literal["SC 13D", "SC 13D/A"] = "SC 13D",
    ticker: str | None = None,
    filing_date: date = date(2026, 5, 12),
    filer_name: str = "Elliott Investment Management",
) -> FilingHeader:
    return FilingHeader(
        cik=cik,
        filer_name=filer_name,
        accession=accession,
        form_type=form,
        filing_date=filing_date,
        primary_doc="primary.htm",
        subject_ticker=ticker,
    )


def _snapshot(
    ticker: str,
    *,
    sector: str = "Industrials",
    price: Decimal = Decimal("50"),
    market_cap: Decimal = Decimal("1500000000"),
    avg_vol: Decimal = Decimal("1000000"),
    one_day: Decimal = Decimal("0.03"),
) -> MarketSnapshot:
    returns = ReturnMetrics(
        one_day=one_day,
        five_day=Decimal("0.05"),
        twenty_day=Decimal("0.07"),
        fifty_day=None,
    )
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=TODAY,
        company_name=f"{ticker} Industries",
        sector=sector,
        sector_etf="XLI",
        market_cap=market_cap,
        current_price=price,
        latest_volume=1_000_000,
        average_volume_20d=avg_vol,
        volume_vs_average_20d=Decimal("1.5"),
        stock_returns=returns,
        spy_returns=returns,
        qqq_returns=returns,
        sector_returns=returns,
        relative_strength_vs_spy=Decimal("0.02"),
        relative_strength_vs_qqq=Decimal("0.02"),
        relative_strength_vs_sector=Decimal("0.01"),
        av_news_sentiment=None,
        price_source="yfinance",
        overview_source="yfinance",
        sources=("yfinance",),
    )


def _build_service(
    client: FakeFilingsClient,
    market_data: FakeMarketData,
) -> Activist13DCandidateService:
    return Activist13DCandidateService(
        client,  # type: ignore[arg-type]
        market_data=market_data,
        settings=Settings(),
        today_provider=lambda: TODAY,
    )


def _body(stake: str = "7.5") -> str:
    return _BASE_ACTIVE_BODY.format(stake=stake)


async def test_tier_progression_until_5_candidates() -> None:
    tier1 = (_header(accession="ACC-1", cik="0000000001", ticker="AAA"),)
    tier2 = (
        _header(
            accession="ACC-2",
            cik="0000000002",
            form="SC 13D/A",
            ticker="BBB",
        ),
    )
    tier3 = (
        _header(accession="ACC-3", cik="0000000003", ticker="CCC"),
        _header(accession="ACC-4", cik="0000000004", ticker="DDD"),
        _header(accession="ACC-5", cik="0000000005", ticker="EEE"),
    )
    client = FakeFilingsClient(
        tier1=tier1,
        tier2=tier2,
        tier3=tier3,
        documents={
            "ACC-1": _body("8.0"),
            "ACC-2": _body("9.0"),
            "ACC-3": _body("7.0"),
            "ACC-4": _body("6.0"),
            "ACC-5": _body("5.5"),
        },
    )
    market = FakeMarketData(
        snapshots={
            "AAA": _snapshot("AAA"),
            "BBB": _snapshot("BBB"),
            "CCC": _snapshot("CCC"),
            "DDD": _snapshot("DDD"),
            "EEE": _snapshot("EEE"),
        }
    )
    service = _build_service(client, market)

    batch = await service.get_top_five()

    assert {row.ticker for row in batch.candidates} == {"AAA", "BBB", "CCC", "DDD", "EEE"}
    assert [form for form, _ in client.tier_calls] == ["SC 13D", "SC 13D/A", "SC 13D"]
    assert batch.screener_status == "success"


async def test_returns_partial_batch_when_universe_smaller_than_5() -> None:
    tier1 = (
        _header(accession="ACC-1", cik="0000000001", ticker="AAA"),
        _header(accession="ACC-2", cik="0000000002", ticker="BBB"),
    )
    client = FakeFilingsClient(
        tier1=tier1,
        documents={"ACC-1": _body("8.0"), "ACC-2": _body("6.0")},
    )
    market = FakeMarketData(snapshots={"AAA": _snapshot("AAA"), "BBB": _snapshot("BBB")})
    service = _build_service(client, market)

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["AAA", "BBB"]
    assert batch.screener_status == "partial"


async def test_excludes_illiquid_options() -> None:
    tier1 = (
        _header(accession="ACC-1", cik="0000000001", ticker="LIQ"),
        _header(accession="ACC-2", cik="0000000002", ticker="ILLQ"),
    )
    client = FakeFilingsClient(
        tier1=tier1,
        documents={"ACC-1": _body("7.0"), "ACC-2": _body("7.5")},
    )
    market = FakeMarketData(
        snapshots={
            "LIQ": _snapshot("LIQ"),
            # Falls below average volume and market cap floors.
            "ILLQ": _snapshot(
                "ILLQ",
                avg_vol=Decimal("100000"),
                market_cap=Decimal("100000000"),
                price=Decimal("5"),
            ),
        }
    )
    service = _build_service(client, market)

    batch = await service.get_top_five()

    assert [row.ticker for row in batch.candidates] == ["LIQ"]


async def test_persists_accession_and_filing_url_in_validation_notes() -> None:
    tier1 = (_header(accession="0001234567-25-000999", cik="0000000001", ticker="AAA"),)
    client = FakeFilingsClient(
        tier1=tier1,
        documents={"0001234567-25-000999": _body("8.0")},
    )
    market = FakeMarketData(snapshots={"AAA": _snapshot("AAA")})
    service = _build_service(client, market)

    batch = await service.get_top_five()

    assert batch.candidates, "expected one candidate"
    notes = batch.candidates[0].validation_notes
    accession_note = next(n for n in notes if n.startswith("SC_13D_ACCESSION="))
    url_note = next(n for n in notes if n.startswith("SC_13D_URL="))
    assert accession_note == "SC_13D_ACCESSION=0001234567-25-000999"
    assert "0001234567" in url_note
    assert url_note.endswith("primary.htm")


async def test_event_signal_populated_from_event_score() -> None:
    tier1 = (_header(accession="ACC-1", cik="0000000001", ticker="AAA"),)
    client = FakeFilingsClient(
        tier1=tier1,
        documents={"ACC-1": _body("8.0")},
    )
    market = FakeMarketData(snapshots={"AAA": _snapshot("AAA")})
    service = _build_service(client, market)

    batch = await service.get_top_five()

    record = batch.candidates[0]
    assert record.event_signal is not None
    assert record.event_signal.is_supportive is True
    assert 0 <= record.event_signal.score <= 100
    assert "Elliott" in record.event_signal.detail
    assert "active intent" in record.event_signal.detail
