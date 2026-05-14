from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

import pytest

from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.coiled_setup_service import (
    COILED_STRATEGY_SOURCE,
    CoiledSetupCandidateService,
)
from app.services.finviz.strategies import (
    STRATEGY_B_VARIANT_PREFIX,
    STRATEGY_B_VARIANT_VALUES,
)

pytestmark = pytest.mark.asyncio


@dataclass
class FakeRunner:
    rows: list[CandidateRecord] = field(default_factory=list)
    error: Exception | None = None
    last_call: dict | None = None

    async def run_with_swap(
        self,
        base,
        *,
        swap_prefix,
        swap_values,
        limit,
        strategy_source,
    ):
        self.last_call = {
            "base": base,
            "swap_prefix": swap_prefix,
            "swap_values": swap_values,
            "limit": limit,
            "strategy_source": strategy_source,
        }
        if self.error is not None:
            raise self.error
        return list(self.rows)


def _row(ticker: str, *, rank: int) -> CandidateRecord:
    return CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Co",
        market_cap=Decimal("1000"),
        earnings_date=None,
        current_price=Decimal("50"),
        screener_rank=rank,
        sources=("finviz",),
        strategy_source=COILED_STRATEGY_SOURCE,
    )


async def test_coiled_setup_service_uses_strategy_b_variant_swap() -> None:
    runner = FakeRunner(rows=[_row("AAA", rank=1)])
    service = CoiledSetupCandidateService(runner)

    batch = await service.get_top_five()

    assert runner.last_call["swap_prefix"] == STRATEGY_B_VARIANT_PREFIX
    assert tuple(runner.last_call["swap_values"]) == STRATEGY_B_VARIANT_VALUES
    assert runner.last_call["strategy_source"] == COILED_STRATEGY_SOURCE
    assert isinstance(batch, CandidateBatch)
    assert batch.screener_status == "success"
    assert [row.ticker for row in batch.candidates] == ["AAA"]
    assert batch.candidates[0].event_signal is not None
    assert batch.candidates[0].event_signal.score == 100
    assert batch.candidates[0].event_signal.detail.startswith("Coiled setup:")
    assert batch.strategy_reports[0].strategy_source == COILED_STRATEGY_SOURCE


async def test_coiled_setup_service_returns_empty_batch_on_failure() -> None:
    runner = FakeRunner(error=RuntimeError("Finviz down"))
    service = CoiledSetupCandidateService(runner)

    batch = await service.get_top_five()

    assert isinstance(batch, CandidateBatch)
    assert batch.candidates == ()
    assert batch.screener_status == "empty"
    assert batch.strategy_reports[0].status == "empty"
    assert batch.strategy_reports[0].error == "Finviz down"


async def test_coiled_setup_service_truncates_to_limit() -> None:
    runner = FakeRunner(rows=[_row(f"T{i}", rank=i) for i in range(1, 8)])
    service = CoiledSetupCandidateService(runner)

    batch = await service.get_top_five(limit=3)

    assert len(batch.candidates) == 3


async def test_returns_candidate_batch_not_tuple() -> None:
    runner = FakeRunner(rows=[_row("AAA", rank=1)])
    service = CoiledSetupCandidateService(runner)

    batch = await service.get_top_five()

    assert isinstance(batch, CandidateBatch)
