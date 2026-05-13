from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.core import crypto
from app.services.options.types import OptionContract
from app.services.positions.snapshots import PositionSnapshotService

pytestmark = pytest.mark.asyncio


class FakeOptionsClient:
    def __init__(self, contracts: tuple[OptionContract, ...] = ()) -> None:
        self.contracts = contracts
        self.calls: list[dict[str, Any]] = []

    async def fetch_chain(self, ticker: str, **kwargs: Any) -> tuple[OptionContract, ...]:
        self.calls.append({"ticker": ticker, **kwargs})
        return self.contracts


class FakeMarketData:
    async def fetch(self, ticker: str, **kwargs: Any) -> object:
        del ticker, kwargs
        return SimpleNamespace(current_price=Decimal("100.00"))


def _recommendation(**overrides: object) -> object:
    values = {
        "ticker": "AMD",
        "option_type": "call",
        "position_side": "long",
        "strike": Decimal("104.00"),
        "expiry": date(2026, 5, 16),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _user(*, alpaca: bool = False) -> object:
    crypto.reset_cache()
    return SimpleNamespace(
        alpha_vantage_api_key_encrypted=None,
        alpaca_api_key_encrypted=crypto.encrypt("alp-key") if alpaca else None,
        alpaca_api_secret_encrypted=crypto.encrypt("alp-secret") if alpaca else None,
    )


async def test_snapshot_long_position_uses_bid_as_liquidation_premium() -> None:
    contract = OptionContract(
        ticker="AMD",
        option_type="call",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.20"),
        ask=Decimal("1.35"),
        mid=Decimal("1.28"),
        source="yfinance",
    )
    service = PositionSnapshotService(
        yfinance=FakeOptionsClient((contract,)),
        alpaca=FakeOptionsClient(),
        market_data=FakeMarketData(),
    )

    snapshot = await service.fetch_current(
        user=_user(),
        recommendation=_recommendation(),
        today=date(2026, 5, 13),
    )

    assert snapshot.liquidation_premium == Decimal("1.20")
    assert snapshot.underlying_price == Decimal("100.00")
    assert snapshot.status == "complete"


async def test_snapshot_short_position_uses_ask_as_liquidation_premium() -> None:
    contract = OptionContract(
        ticker="AMD",
        option_type="call",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.20"),
        ask=Decimal("1.35"),
        mid=Decimal("1.28"),
        source="yfinance",
    )
    service = PositionSnapshotService(
        yfinance=FakeOptionsClient((contract,)),
        alpaca=FakeOptionsClient(),
        market_data=FakeMarketData(),
    )

    snapshot = await service.fetch_current(
        user=_user(),
        recommendation=_recommendation(position_side="short"),
        today=date(2026, 5, 13),
    )

    assert snapshot.liquidation_premium == Decimal("1.35")


async def test_snapshot_preserves_alpaca_greeks() -> None:
    contract = OptionContract(
        ticker="AMD",
        option_type="call",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.20"),
        ask=Decimal("1.35"),
        mid=Decimal("1.28"),
        implied_volatility=Decimal("0.420000"),
        delta=Decimal("0.510000"),
        gamma=Decimal("0.030000"),
        theta=Decimal("-0.050000"),
        vega=Decimal("0.110000"),
        source="alpaca",
        symbol="AMD260516C00104000",
    )
    alpaca = FakeOptionsClient((contract,))
    service = PositionSnapshotService(
        yfinance=FakeOptionsClient(),
        alpaca=alpaca,
        market_data=FakeMarketData(),
    )

    snapshot = await service.fetch_current(
        user=_user(alpaca=True),
        recommendation=_recommendation(),
        today=date(2026, 5, 13),
    )

    assert snapshot.source == "alpaca"
    assert snapshot.implied_volatility == Decimal("0.420000")
    assert snapshot.delta == Decimal("0.510000")
    assert snapshot.gamma == Decimal("0.030000")
    assert snapshot.theta == Decimal("-0.050000")
    assert snapshot.vega == Decimal("0.110000")
    assert alpaca.calls[0]["symbols"] == ["AMD260516C00104000"]


async def test_snapshot_falls_back_from_alpaca_to_yfinance() -> None:
    yfinance_contract = OptionContract(
        ticker="AMD",
        option_type="call",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        bid=Decimal("1.10"),
        ask=Decimal("1.30"),
        mid=Decimal("1.20"),
        source="yfinance",
    )
    service = PositionSnapshotService(
        yfinance=FakeOptionsClient((yfinance_contract,)),
        alpaca=FakeOptionsClient(),
        market_data=FakeMarketData(),
    )

    snapshot = await service.fetch_current(
        user=_user(alpaca=True),
        recommendation=_recommendation(),
        today=date(2026, 5, 13),
    )

    assert snapshot.source == "yfinance"
    assert "alpaca_contract_not_found" in snapshot.notes


async def test_snapshot_unavailable_when_no_contract_matches() -> None:
    service = PositionSnapshotService(
        yfinance=FakeOptionsClient(),
        alpaca=FakeOptionsClient(),
        market_data=FakeMarketData(),
    )

    snapshot = await service.fetch_current(
        user=_user(),
        recommendation=_recommendation(),
        today=date(2026, 5, 13),
    )

    assert snapshot.status == "unavailable"
    assert snapshot.liquidation_premium is None
