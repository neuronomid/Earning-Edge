from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pytest

from app.services.candidate_models import CandidateRecord
from app.services.candidate_service import (
    TRADINGVIEW_FALLBACK_WARNING,
    CandidateSelectionError,
    CandidateService,
)

pytestmark = pytest.mark.asyncio


@dataclass
class FakeExtractor:
    rows: list[CandidateRecord] | None = None
    error: Exception | None = None

    async def get_top_five(self, *, limit: int = 5) -> list[CandidateRecord]:
        del limit
        if self.error is not None:
            raise self.error
        assert self.rows is not None
        return self.rows


@dataclass
class FakeSource:
    details: dict[str, CandidateRecord]
    upcoming: list[CandidateRecord]

    async def get_candidate_details(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None:
        del window
        return self.details.get(ticker.upper())

    async def list_upcoming_candidates(
        self,
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]:
        del window
        return self.upcoming[:limit]


def _candidate(
    ticker: str,
    market_cap: str,
    *,
    earnings_date: date | None,
    current_price: str | None,
    sources: tuple[str, ...],
) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        market_cap=Decimal(market_cap),
        earnings_date=earnings_date,
        current_price=None if current_price is None else Decimal(current_price),
        sector="Technology services",
        sources=sources,
    )


async def test_candidate_service_validates_tradingview_rows() -> None:
    tradingview_rows = [
        _candidate(
            "AAA",
            "900",
            earnings_date=None,
            current_price="100.00",
            sources=("tradingview",),
        ),
        _candidate(
            "BBB",
            "800",
            earnings_date=None,
            current_price="90.00",
            sources=("tradingview",),
        ),
        _candidate(
            "CCC",
            "700",
            earnings_date=None,
            current_price="80.00",
            sources=("tradingview",),
        ),
        _candidate(
            "DDD",
            "600",
            earnings_date=None,
            current_price="70.00",
            sources=("tradingview",),
        ),
        _candidate(
            "EEE",
            "500",
            earnings_date=None,
            current_price="60.00",
            sources=("tradingview",),
        ),
    ]
    source = FakeSource(
        details={
            ticker: _candidate(
                ticker,
                market_cap,
                earnings_date=date(2026, 5, 8),
                current_price=current_price,
                sources=("yfinance",),
            )
            for ticker, market_cap, current_price in [
                ("AAA", "901", "100.10"),
                ("BBB", "801", "90.10"),
                ("CCC", "701", "80.10"),
                ("DDD", "601", "70.10"),
                ("EEE", "501", "60.10"),
            ]
        },
        upcoming=[],
    )
    service = CandidateService(
        FakeExtractor(rows=tradingview_rows),
        sources=(source,),
        today_provider=lambda: date(2026, 5, 1),
    )

    batch = await service.get_top_five()

    assert batch.tradingview_status == "success"
    assert batch.fallback_used is False
    assert [candidate.ticker for candidate in batch.candidates] == [
        "AAA",
        "BBB",
        "CCC",
        "DDD",
        "EEE",
    ]
    assert all(candidate.earnings_date == date(2026, 5, 8) for candidate in batch.candidates)


async def test_candidate_service_falls_back_when_tradingview_fails() -> None:
    backup_rows = [
        _candidate(
            "AAA",
            "900",
            earnings_date=date(2026, 5, 8),
            current_price="100.00",
            sources=("finnhub",),
        ),
        _candidate(
            "BBB",
            "800",
            earnings_date=date(2026, 5, 8),
            current_price="90.00",
            sources=("finnhub",),
        ),
        _candidate(
            "CCC",
            "700",
            earnings_date=date(2026, 5, 8),
            current_price="80.00",
            sources=("finnhub",),
        ),
        _candidate(
            "DDD",
            "600",
            earnings_date=date(2026, 5, 8),
            current_price="70.00",
            sources=("finnhub",),
        ),
        _candidate(
            "EEE",
            "500",
            earnings_date=date(2026, 5, 8),
            current_price="60.00",
            sources=("finnhub",),
        ),
    ]
    source = FakeSource(
        details={row.ticker: row for row in backup_rows},
        upcoming=backup_rows,
    )
    service = CandidateService(
        FakeExtractor(error=RuntimeError("TradingView down")),
        sources=(source,),
        today_provider=lambda: date(2026, 5, 1),
    )

    batch = await service.get_top_five()

    assert batch.tradingview_status == "failed"
    assert batch.fallback_used is True
    assert batch.warning_text == TRADINGVIEW_FALLBACK_WARNING
    assert [candidate.ticker for candidate in batch.candidates] == [
        "AAA",
        "BBB",
        "CCC",
        "DDD",
        "EEE",
    ]


async def test_candidate_service_rejects_candidates_outside_next_week_window() -> None:
    tradingview_rows = [
        _candidate(
            "AAA",
            "900",
            earnings_date=None,
            current_price="100.00",
            sources=("tradingview",),
        ),
        _candidate(
            "BBB",
            "800",
            earnings_date=None,
            current_price="90.00",
            sources=("tradingview",),
        ),
        _candidate(
            "CCC",
            "700",
            earnings_date=None,
            current_price="80.00",
            sources=("tradingview",),
        ),
        _candidate(
            "DDD",
            "600",
            earnings_date=None,
            current_price="70.00",
            sources=("tradingview",),
        ),
        _candidate(
            "EEE",
            "500",
            earnings_date=None,
            current_price="60.00",
            sources=("tradingview",),
        ),
    ]
    source = FakeSource(
        details={
            ticker: _candidate(
                ticker,
                market_cap,
                earnings_date=date(2026, 7, 30),
                current_price=current_price,
                sources=("yfinance",),
            )
            for ticker, market_cap, current_price in [
                ("AAA", "901", "100.10"),
                ("BBB", "801", "90.10"),
                ("CCC", "701", "80.10"),
                ("DDD", "601", "70.10"),
                ("EEE", "501", "60.10"),
            ]
        },
        upcoming=[],
    )
    service = CandidateService(
        FakeExtractor(rows=tradingview_rows),
        sources=(source,),
        today_provider=lambda: date(2026, 5, 1),
    )

    with pytest.raises(
        CandidateSelectionError,
        match="fewer than five validated candidates",
    ):
        await service.get_top_five()
