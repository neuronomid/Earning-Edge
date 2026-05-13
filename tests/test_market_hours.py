from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.market_hours import current_market_session, is_market_open, next_market_open

ET = ZoneInfo("America/New_York")


def test_market_open_regular_session_boundaries() -> None:
    assert is_market_open(datetime(2026, 5, 13, 9, 29, tzinfo=ET)) is False
    assert is_market_open(datetime(2026, 5, 13, 9, 30, tzinfo=ET)) is True
    assert is_market_open(datetime(2026, 5, 13, 15, 59, tzinfo=ET)) is True
    assert is_market_open(datetime(2026, 5, 13, 16, 0, tzinfo=ET)) is False


def test_market_closed_on_weekend_and_holiday() -> None:
    assert is_market_open(datetime(2026, 5, 16, 12, 0, tzinfo=ET)) is False
    assert is_market_open(datetime(2026, 5, 25, 10, 0, tzinfo=ET)) is False


def test_next_market_open_skips_weekend() -> None:
    next_open = next_market_open(datetime(2026, 5, 16, 12, 0, tzinfo=ET))

    assert next_open == datetime(2026, 5, 18, 9, 30, tzinfo=ET)


def test_market_helper_respects_early_close() -> None:
    open_session = current_market_session(datetime(2026, 11, 27, 12, 30, tzinfo=ET))

    assert open_session is not None
    assert open_session.close_at == datetime(2026, 11, 27, 13, 0, tzinfo=ET)
    assert is_market_open(datetime(2026, 11, 27, 13, 0, tzinfo=ET)) is False


def test_naive_input_is_accepted() -> None:
    assert is_market_open(datetime(2026, 5, 13, 14, 0)) is True
