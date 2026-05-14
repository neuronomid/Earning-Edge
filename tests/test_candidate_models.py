from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import get_args

from app.scoring.types import StrategySource as ScoringStrategySource
from app.services.candidate_models import (
    CandidateRecord,
    ScreenerStatus,
    StrategyEventSignal,
    StrategySource,
)


def test_strategy_source_literal_widened() -> None:
    expected = {
        "catalyst_confluence",
        "coiled_setup",
        "pead_continuation",
        "sector_relative_strength",
        "activist_13d_followthrough",
    }

    assert set(get_args(StrategySource)) == expected
    assert set(get_args(ScoringStrategySource)) == expected


def test_screener_status_includes_empty() -> None:
    assert set(get_args(ScreenerStatus)) == {"success", "partial", "failed", "empty"}


def test_event_signal_default_none() -> None:
    record = CandidateRecord(
        ticker="ABC",
        company_name="ABC Inc.",
        market_cap=Decimal("1000000000"),
        earnings_date=date(2026, 5, 8),
        current_price=Decimal("100"),
    )

    assert record.event_signal is None
    assert isinstance(hash(record), int)


def test_strategy_event_signal_is_frozen_and_hashable() -> None:
    signal = StrategyEventSignal(
        score=85,
        is_supportive=True,
        detail="Sector relative strength confirmed.",
    )

    assert hash(signal) == hash(signal)
