from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.services.market_data.indicators import (
    compute_returns,
    relative_strength,
    volume_vs_average,
)
from app.services.market_data.types import PriceBar

FIXTURES = Path(__file__).parent / "fixtures" / "market_data"


def test_indicator_math_matches_fixed_csv_fixture() -> None:
    stock_history = _load_history(FIXTURES / "sample_stock_history.csv")
    spy_history = _load_history(FIXTURES / "sample_spy_history.csv")

    stock_returns = compute_returns(stock_history)
    spy_returns = compute_returns(spy_history)

    assert stock_returns.one_day == (Decimal("154") / Decimal("153")) - Decimal("1")
    assert stock_returns.five_day == (Decimal("154") / Decimal("149")) - Decimal("1")
    assert stock_returns.twenty_day == (Decimal("154") / Decimal("134")) - Decimal("1")
    assert stock_returns.fifty_day == (Decimal("154") / Decimal("104")) - Decimal("1")
    assert volume_vs_average(stock_history) == Decimal("1540") / Decimal("1435")
    assert relative_strength(stock_returns, spy_returns) == (
        ((Decimal("154") / Decimal("134")) - Decimal("1"))
        - ((Decimal("427.0") / Decimal("417.0")) - Decimal("1"))
    )


def test_indicator_math_returns_none_when_history_is_too_short() -> None:
    short_history = tuple(
        PriceBar(
            date=date(2026, 1, day),
            close=Decimal(str(100 + day)),
            volume=1000 + day,
        )
        for day in range(1, 11)
    )

    returns = compute_returns(short_history)

    assert returns.twenty_day is None
    assert returns.fifty_day is None
    assert volume_vs_average(short_history) is None


def _load_history(path: Path) -> tuple[PriceBar, ...]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [
            PriceBar(
                date=date.fromisoformat(row["date"]),
                close=Decimal(row["close"]),
                volume=int(row["volume"]),
            )
            for row in reader
        ]
    return tuple(rows)
