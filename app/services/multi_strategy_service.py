from __future__ import annotations

import asyncio
from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.candidate_models import CandidateBatch, CandidateRecord, ScreenerStatus
from app.services.candidate_service import CandidateService
from app.services.coiled_setup_service import CoiledSetupCandidateService
from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource
from app.services.earnings_calendar.yfinance_source import YFinanceEarningsSource
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.cache import FinvizScreenerCache
from app.services.finviz.runner import FinvizQueryRunner
from app.services.run_lock import get_redis_client

CATALYST_ONLY_WARNING = (
    "⚠️ Coiled-setup screen returned no candidates this scan — showing catalyst-driven setups only."
)
COILED_ONLY_WARNING = (
    "⚠️ Catalyst screen returned no setups this scan — showing structure-driven candidates only."
)
BOTH_FAILED_WARNING = "⚠️ Both screening strategies failed to return candidates."


class MultiStrategyCandidateService:
    def __init__(
        self,
        catalyst: CandidateService,
        coiled: CoiledSetupCandidateService,
        *,
        logger=None,
    ) -> None:
        self.catalyst = catalyst
        self.coiled = coiled
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self) -> CandidateBatch:
        return await self.get_candidates()

    async def get_candidates(self) -> CandidateBatch:
        a_result, b_result = await asyncio.gather(
            self.catalyst.get_top_five(),
            self.coiled.get_top_five(),
            return_exceptions=True,
        )

        a_batch: CandidateBatch | None = None
        a_rows: list[CandidateRecord] = []
        if isinstance(a_result, CandidateBatch):
            a_batch = a_result
            a_rows = list(a_result.candidates)
        elif isinstance(a_result, BaseException):
            self.logger.warning(
                "multi_strategy_catalyst_failed", error=str(a_result)
            )

        b_rows: list[CandidateRecord] = []
        if isinstance(b_result, tuple):
            b_rows = list(b_result)
        elif isinstance(b_result, BaseException):
            self.logger.warning(
                "multi_strategy_coiled_failed", error=str(b_result)
            )

        merged = _merge_dedupe(a_rows, b_rows)

        screener_status: ScreenerStatus
        warning_text: str | None
        if a_rows and b_rows:
            screener_status = "success"
            warning_text = None
        elif a_rows:
            screener_status = "partial"
            warning_text = CATALYST_ONLY_WARNING
        elif b_rows:
            screener_status = "partial"
            warning_text = COILED_ONLY_WARNING
        else:
            screener_status = "failed"
            warning_text = BOTH_FAILED_WARNING

        fallback_used = a_batch.fallback_used if a_batch is not None else False
        if a_batch is not None and a_batch.warning_text and warning_text is None:
            warning_text = a_batch.warning_text

        self.logger.info(
            "multi_strategy_merged",
            catalyst_count=len(a_rows),
            coiled_count=len(b_rows),
            merged_count=len(merged),
            screener_status=screener_status,
        )

        return CandidateBatch(
            candidates=tuple(merged),
            screener_status=screener_status,
            fallback_used=fallback_used,
            warning_text=warning_text,
        )


def _merge_dedupe(
    catalyst_rows: list[CandidateRecord],
    coiled_rows: list[CandidateRecord],
) -> list[CandidateRecord]:
    seen: set[str] = set()
    merged: list[CandidateRecord] = []
    for row in (*catalyst_rows, *coiled_rows):
        ticker = row.ticker.upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        merged.append(row)
    return merged


@lru_cache(maxsize=1)
def get_multi_strategy_service() -> MultiStrategyCandidateService:
    settings = get_settings()
    browser = FinvizBrowserClient(
        headless=settings.finviz_headless,
        timeout_ms=settings.finviz_timeout_ms,
    )
    cache = FinvizScreenerCache(
        get_redis_client(),
        ttl_seconds=settings.finviz_query_cache_ttl_seconds,
    )
    runner = FinvizQueryRunner(browser, cache=cache)
    catalyst = CandidateService(
        runner,
        sources=(
            YFinanceEarningsSource(),
            FinnhubEarningsSource(api_key=settings.finnhub_api_key),
        ),
    )
    coiled = CoiledSetupCandidateService(runner)
    return MultiStrategyCandidateService(catalyst, coiled)
