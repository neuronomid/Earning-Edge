from __future__ import annotations

import os

import pytest

from app.services.candidate_service import get_candidate_service, get_top_five
from app.services.finviz.strategies import (
    STRATEGY_A_BASE,
    STRATEGY_A_EARNINGS_PREFIX,
    STRATEGY_A_EARNINGS_VALUES,
)

pytestmark = pytest.mark.asyncio


async def test_live_browser_get_top_five() -> None:
    if os.getenv("RUN_LIVE_BROWSER") != "1":
        pytest.skip("Set RUN_LIVE_BROWSER=1 to exercise the live Finviz browser flow")

    raw_rows = await get_candidate_service().runner.run_with_swap(
        STRATEGY_A_BASE,
        swap_prefix=STRATEGY_A_EARNINGS_PREFIX,
        swap_values=STRATEGY_A_EARNINGS_VALUES,
        limit=5,
        strategy_source="catalyst_confluence",
    )
    batch = await get_top_five()

    assert batch.screener_status in {"success", "failed"}
    assert len(batch.candidates) == 5
    assert len(raw_rows) >= 1
    assert all(candidate.ticker for candidate in batch.candidates)
    assert all(candidate.earnings_date is not None for candidate in batch.candidates)
    assert all(candidate.current_price is not None for candidate in batch.candidates)
