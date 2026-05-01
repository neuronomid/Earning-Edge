from __future__ import annotations

import sys
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.market_data.yf_client import YFinanceClient

pytestmark = pytest.mark.asyncio


class FakeFrame:
    def __init__(self, rows: list[tuple[datetime, dict[str, object]]]) -> None:
        self._rows = rows
        self.empty = False

    def iterrows(self) -> list[tuple[datetime, dict[str, object]]]:
        return self._rows


class FakeTicker:
    def __init__(
        self,
        *,
        fast_info: dict[str, object],
        info: dict[str, object],
        frame: FakeFrame,
    ) -> None:
        self.fast_info = fast_info
        self.info = info
        self._frame = frame

    def history(self, *, period: str, auto_adjust: bool) -> FakeFrame:
        assert period == "6mo"
        assert auto_adjust is False
        return self._frame


async def test_yfinance_client_parses_security_snapshot(monkeypatch: pytest.MonkeyPatch) -> None:
    ticker = FakeTicker(
        fast_info={"lastPrice": 154.5, "marketCap": 250000000000},
        info={"shortName": "Advanced Micro Devices", "sector": "Technology"},
        frame=FakeFrame(
            [
                (datetime(2026, 4, 30, 0, 0), {"Close": 150.0, "Volume": 12000}),
                (datetime(2026, 5, 1, 0, 0), {"Close": 154.2, "Volume": 12345}),
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: ticker))

    snapshot = await YFinanceClient().fetch_security("amd")

    assert snapshot.ticker == "AMD"
    assert snapshot.company_name == "Advanced Micro Devices"
    assert snapshot.sector == "Technology"
    assert snapshot.market_cap == Decimal("250000000000")
    assert snapshot.current_price == Decimal("154.5")
    assert [bar.close for bar in snapshot.history] == [Decimal("150.0"), Decimal("154.2")]


async def test_yfinance_client_falls_back_to_last_close_when_fast_price_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ticker = FakeTicker(
        fast_info={},
        info={"shortName": "Advanced Micro Devices", "sector": "Technology"},
        frame=FakeFrame(
            [
                (datetime(2026, 4, 30, 0, 0), {"Close": 150.0, "Volume": 12000}),
                (datetime(2026, 5, 1, 0, 0), {"Close": 154.2, "Volume": 12345}),
            ]
        ),
    )
    monkeypatch.setitem(sys.modules, "yfinance", SimpleNamespace(Ticker=lambda symbol: ticker))

    snapshot = await YFinanceClient().fetch_security("amd")

    assert snapshot.current_price == Decimal("154.2")
