from __future__ import annotations

from collections.abc import Callable
from datetime import date

from app.services.candidate_models import CandidateRecord
from app.services.tradingview.browser import (
    TradingViewBrowserClient,
    TradingViewTableSnapshot,
)
from app.services.tradingview.parser import parse_candidate_table


class TradingViewExtractorError(RuntimeError):
    """Raised when every supported TradingView extraction path failed."""


class TradingViewVisionFallbackError(TradingViewExtractorError):
    """Raised when the vision fallback would be required before Phase 7 is ready."""


class TradingViewExtractor:
    def __init__(
        self,
        browser: TradingViewBrowserClient,
        *,
        today_provider: Callable[[], date] | None = None,
    ) -> None:
        self.browser = browser
        self.today_provider = today_provider or date.today

    async def get_top_five(self, *, limit: int = 5) -> list[CandidateRecord]:
        snapshot = await self.browser.capture_table_snapshot(limit=limit)
        rows = self._from_accessibility(snapshot, limit=limit)
        if len(rows) >= limit:
            return rows[:limit]

        rows = self._from_html(snapshot, limit=limit)
        if len(rows) >= limit:
            return rows[:limit]

        raise TradingViewVisionFallbackError(
            "TradingView extraction reached the vision fallback, but that path stays stubbed "
            "until the Phase 7 Gemini route exists."
        )

    def _from_accessibility(
        self,
        snapshot: TradingViewTableSnapshot,
        *,
        limit: int,
    ) -> list[CandidateRecord]:
        rows = [row for row in snapshot.accessible_rows if row.ticker != ""]
        return rows[:limit]

    def _from_html(
        self,
        snapshot: TradingViewTableSnapshot,
        *,
        limit: int,
    ) -> list[CandidateRecord]:
        if snapshot.table_html is None:
            return []
        return parse_candidate_table(
            snapshot.table_html,
            today=self.today_provider(),
            limit=limit,
        )
