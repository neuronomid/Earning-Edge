from __future__ import annotations

import os

import pytest

from app.services.candidate_service import get_top_five

pytestmark = pytest.mark.asyncio


async def test_live_browser_get_top_five() -> None:
    if os.getenv("RUN_LIVE_BROWSER") != "1":
        pytest.skip("Set RUN_LIVE_BROWSER=1 to exercise the live TradingView browser flow")

    batch = await get_top_five()

    assert batch.tradingview_status in {"success", "failed"}
    assert len(batch.candidates) == 5
    assert all(candidate.ticker for candidate in batch.candidates)
    assert all(candidate.earnings_date is not None for candidate in batch.candidates)
    assert all(candidate.current_price is not None for candidate in batch.candidates)
