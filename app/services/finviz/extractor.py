from __future__ import annotations

from app.services.candidate_models import CandidateRecord
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.query import FinvizQuery


class FinvizExtractorError(RuntimeError):
    """Raised when Finviz extraction failed."""


class FinvizExtractor:
    def __init__(self, browser: FinvizBrowserClient) -> None:
        self.browser = browser

    async def get_top_five(
        self,
        query: FinvizQuery,
        *,
        limit: int = 5,
    ) -> list[CandidateRecord]:
        rows = await self.browser.capture_snapshot(query, limit=limit)
        if not rows:
            raise FinvizExtractorError("Finviz returned no candidate rows")
        return rows[:limit]
