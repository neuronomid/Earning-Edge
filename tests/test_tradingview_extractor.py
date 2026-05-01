from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.candidate_models import CandidateRecord
from app.services.tradingview.browser import TradingViewTableSnapshot
from app.services.tradingview.extractor import TradingViewExtractor

pytestmark = pytest.mark.asyncio

FIXTURE = (
    Path(__file__).parent / "fixtures" / "tradingview" / "screener_next_week.html"
)


@dataclass
class FakeBrowser:
    snapshot: TradingViewTableSnapshot

    async def capture_table_snapshot(self, *, limit: int = 5) -> TradingViewTableSnapshot:
        del limit
        return self.snapshot


async def test_extractor_returns_accessibility_rows_first() -> None:
    rows = [
        CandidateRecord(
            ticker=f"TICK{index}",
            company_name=f"Company {index}",
            market_cap=Decimal(str(100 - index)),
            earnings_date=date(2026, 5, 8),
            current_price=Decimal("100.00"),
            sources=("tradingview",),
        )
        for index in range(5)
    ]
    extractor = TradingViewExtractor(
        FakeBrowser(TradingViewTableSnapshot(accessible_rows=tuple(rows), table_html=None))
    )

    result = await extractor.get_top_five()

    assert [row.ticker for row in result] == [row.ticker for row in rows]


async def test_extractor_falls_back_to_html_parser() -> None:
    extractor = TradingViewExtractor(
        FakeBrowser(
            TradingViewTableSnapshot(
                accessible_rows=tuple(),
                table_html=FIXTURE.read_text(encoding="utf-8"),
            )
        ),
        today_provider=lambda: date(2026, 5, 1),
    )

    result = await extractor.get_top_five()

    assert [row.ticker for row in result] == ["NVDA", "GOOG", "AAPL", "MSFT", "AMZN"]
