from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.candidate_models import CandidateRecord
from app.services.earnings_calendar.reconciler import (
    CandidateReconciler,
    CandidateValidationError,
)


def test_reconciler_prefers_tradingview_ranking_but_fills_missing_fields() -> None:
    primary = CandidateRecord(
        ticker="AAPL",
        company_name="Apple Inc.",
        market_cap=Decimal("4170000000000"),
        earnings_date=None,
        current_price=None,
        daily_change_percent=Decimal("4.61"),
        volume=48870000,
        sector=None,
        sources=("tradingview",),
    )
    yfinance = CandidateRecord(
        ticker="AAPL",
        company_name="Apple Inc.",
        market_cap=Decimal("3900000000000"),
        earnings_date=date(2026, 5, 8),
        current_price=Decimal("283.86"),
        sector="Electronic technology",
        sources=("yfinance",),
    )
    finnhub = CandidateRecord(
        ticker="AAPL",
        company_name="Apple Inc.",
        market_cap=Decimal("3915000000000"),
        earnings_date=date(2026, 5, 8),
        current_price=Decimal("284.02"),
        sources=("finnhub",),
    )

    reconciled = CandidateReconciler().reconcile(primary, [yfinance, finnhub])

    assert reconciled.market_cap == Decimal("4170000000000")
    assert reconciled.current_price == Decimal("283.86")
    assert reconciled.earnings_date == date(2026, 5, 8)
    assert reconciled.sector == "Electronic technology"
    assert reconciled.sources == ("tradingview", "yfinance", "finnhub")
    assert "market cap differs across sources" in reconciled.validation_notes[0]


def test_reconciler_rejects_unverified_conflicting_earnings_dates() -> None:
    primary = CandidateRecord(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        market_cap=Decimal("3080000000000"),
        earnings_date=date(2026, 5, 8),
        current_price=Decimal("414.30"),
        sources=("tradingview",),
    )
    backup = CandidateRecord(
        ticker="MSFT",
        company_name="Microsoft Corporation",
        market_cap=Decimal("3079000000000"),
        earnings_date=date(2026, 5, 9),
        current_price=Decimal("414.10"),
        sources=("yfinance",),
    )

    with pytest.raises(CandidateValidationError, match="earnings date cannot be verified"):
        CandidateReconciler().reconcile(primary, [backup])
