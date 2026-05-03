from __future__ import annotations

import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
import respx
from httpx import Response

from app.pipeline.orchestrator import PipelineOrchestrator
from app.pipeline.steps.options import OptionsFetchStep
from app.services.options import OptionsService
from app.services.options.alpaca_client import AlpacaOptionsClient
from app.services.options.yfinance_client import YFinanceOptionsClient

pytestmark = pytest.mark.asyncio


class FakeFrame:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.empty = not rows

    def to_dict(self, orient: str) -> list[dict[str, object]]:
        assert orient == "records"
        return self._rows


class FakeOptionChain:
    def __init__(self, *, calls: FakeFrame, puts: FakeFrame) -> None:
        self.calls = calls
        self.puts = puts


class FakeTicker:
    def __init__(self) -> None:
        self.options = ("2026-05-16",)

    def option_chain(self, expiry: str) -> FakeOptionChain:
        assert expiry == "2026-05-16"
        return FakeOptionChain(
            calls=FakeFrame(
                [
                    {
                        "contractSymbol": "AMD260516C00104000",
                        "strike": 104,
                        "bid": 1.1,
                        "ask": 1.3,
                        "lastPrice": 1.2,
                        "volume": 220,
                        "openInterest": 450,
                        "impliedVolatility": 0.44,
                    }
                ]
            ),
            puts=FakeFrame(
                [
                    {
                        "contractSymbol": "AMD260516P00095000",
                        "strike": 95,
                        "bid": 1.4,
                        "ask": 1.55,
                        "lastPrice": 1.48,
                        "volume": 180,
                        "openInterest": 390,
                        "impliedVolatility": 0.41,
                    }
                ]
            ),
        )


@respx.mock
async def test_alpaca_client_parses_snapshots_into_contracts() -> None:
    respx.get("https://data.alpaca.markets/v1beta1/options/snapshots/AMD").mock(
        return_value=Response(
            200,
            json={
                "snapshots": {
                    "AMD260516C00104000": {
                        "latestQuote": {"bp": 1.1, "ap": 1.3},
                        "latestTrade": {"p": 1.2},
                        "greeks": {"delta": 0.52, "theta": -0.08},
                        "impliedVolatility": 0.44,
                        "openInterest": 450,
                        "dailyBar": {"v": 220},
                    }
                }
            },
        )
    )

    contracts = await AlpacaOptionsClient().fetch_chain(
        "AMD",
        api_key="key",
        api_secret="secret",
        expiry_window_days=30,
        today=date(2026, 5, 1),
    )

    assert len(contracts) == 1
    contract = contracts[0]
    assert contract.ticker == "AMD"
    assert contract.option_type == "call"
    assert contract.strike == Decimal("104")
    assert contract.expiry == date(2026, 5, 16)
    assert contract.bid == Decimal("1.1")
    assert contract.ask == Decimal("1.3")
    assert contract.mid == Decimal("1.2")
    assert contract.delta == Decimal("0.52")
    assert contract.source == "alpaca"


async def test_yfinance_client_builds_calls_and_puts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda symbol: FakeTicker()),
    )

    contracts = await YFinanceOptionsClient().fetch_chain(
        "amd",
        expiry_window_days=30,
        today=date(2026, 5, 1),
    )

    assert len(contracts) == 2
    assert {contract.option_type for contract in contracts} == {"call", "put"}
    assert {contract.source for contract in contracts} == {"yfinance"}
    assert contracts[0].ticker == "AMD"


async def test_options_service_falls_back_to_yfinance_and_duplicates_sides(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "yfinance",
        SimpleNamespace(Ticker=lambda symbol: FakeTicker()),
    )

    service = OptionsService()
    chain = await service.get_chain(
        "AMD",
        alpaca_api_key=None,
        alpaca_api_secret=None,
        strategy_permission="long_and_short",
        earnings_date=date(2026, 5, 8),
        today=date(2026, 5, 1),
    )

    assert len(chain) == 4
    strategies = {contract.strategy for contract in chain}
    assert strategies == {"long_call", "short_call", "long_put", "short_put"}
    assert {contract.source for contract in chain} == {"yfinance"}


async def test_default_orchestrator_uses_live_options_step() -> None:
    orchestrator = PipelineOrchestrator()
    assert isinstance(orchestrator.options_step, OptionsFetchStep)
