from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.tradingview.parser import parse_aria_snapshot, parse_candidate_table

FIXTURE = (
    Path(__file__).parent / "fixtures" / "tradingview" / "screener_next_week.html"
)


def test_parse_candidate_table_extracts_required_and_preferred_fields() -> None:
    rows = parse_candidate_table(
        FIXTURE.read_text(encoding="utf-8"),
        today=date(2026, 5, 1),
        limit=5,
    )

    assert len(rows) == 5
    first = rows[0]
    assert first.ticker == "NVDA"
    assert first.company_name == "NVIDIA Corporation"
    assert first.market_cap == Decimal("4830000000000")
    assert first.current_price == Decimal("198.80")
    assert first.daily_change_percent == Decimal("-0.39")
    assert first.volume == 69990000
    assert first.sector == "Electronic technology"
    assert first.earnings_date == date(2026, 5, 6)


def test_parse_candidate_table_respects_the_requested_limit() -> None:
    rows = parse_candidate_table(
        FIXTURE.read_text(encoding="utf-8"),
        today=date(2026, 5, 1),
        limit=3,
    )

    assert [row.ticker for row in rows] == ["NVDA", "GOOG", "AAPL"]


def test_parse_aria_snapshot_extracts_candidate_rows() -> None:
    snapshot = """
- table:
  - rowgroup:
    - row "Symbol 100 Price Change % Volume Rel Volume Market cap":
      - columnheader "Symbol 100"
      - columnheader "Price"
  - rowgroup:
    - row "AMD Advanced Micro Devices, Inc. 358.93 USD +1.25% 18.38 M 0.39 585.18 B USD":
      - cell "AMD Advanced Micro Devices, Inc."
      - cell "358.93 USD"
      - cell "+1.25%"
      - cell "18.38 M"
      - cell "0.39"
      - cell "585.18 B USD"
      - cell "135.71"
      - cell "2.64 USD"
      - cell "+163.64%"
      - cell "0.00%"
      - cell "Electronic technology"
      - cell "Buy"
    - row "PLTR Palantir Technologies Inc. 144.34 USD +3.76% 20.23 M 0.52 345.21 B USD":
      - cell "PLTR Palantir Technologies Inc."
      - cell "144.34 USD"
      - cell "+3.76%"
      - cell "20.23 M"
      - cell "0.52"
      - cell "345.21 B USD"
      - cell "228.10"
      - cell "0.63 USD"
      - cell "+234.64%"
      - cell "0.00%"
      - cell "Technology services"
      - cell "Buy"
""".strip()

    rows = parse_aria_snapshot(snapshot, limit=5)

    assert [row.ticker for row in rows] == ["AMD", "PLTR"]
    assert rows[0].market_cap == Decimal("585180000000")
    assert rows[0].sector == "Electronic technology"
