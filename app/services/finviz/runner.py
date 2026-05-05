from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import replace

from app.core.logging import get_logger
from app.services.candidate_models import CandidateRecord, StrategySource
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.cache import FinvizScreenerCache
from app.services.finviz.query import FinvizQuery


class FinvizAllVariantsFailedError(RuntimeError):
    """Raised when every Finviz query variant fails to load."""


class FinvizQueryRunner:
    def __init__(
        self,
        browser: FinvizBrowserClient,
        *,
        cache: FinvizScreenerCache | None = None,
        max_concurrency: int = 2,
        logger=None,
    ) -> None:
        self.browser = browser
        self.cache = cache
        self.semaphore = asyncio.Semaphore(max_concurrency)
        self.logger = logger or get_logger(__name__)

    async def run_with_swap(
        self,
        base: FinvizQuery,
        *,
        swap_prefix: str,
        swap_values: Sequence[str],
        limit: int,
        strategy_source: StrategySource,
    ) -> list[CandidateRecord]:
        queries = [
            base.with_filter_replaced(swap_prefix, value) for value in swap_values
        ]
        results = await asyncio.gather(
            *[
                self._run_single(query, limit=limit, strategy_source=strategy_source)
                for query in queries
            ],
            return_exceptions=True,
        )
        flattened: list[CandidateRecord] = []
        had_success = False
        failures: list[BaseException] = []
        for query, result in zip(queries, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "finviz_runner_variant_failed",
                    strategy_source=strategy_source,
                    url=query.to_url(),
                    error=str(result),
                )
                failures.append(result)
                continue
            had_success = True
            flattened.extend(result)
        if failures and not had_success:
            raise FinvizAllVariantsFailedError(
                f"All Finviz variants failed for {strategy_source}."
            ) from failures[0]
        return self._merge_and_rank(flattened, limit=limit, strategy_source=strategy_source)

    async def _run_single(
        self,
        query: FinvizQuery,
        *,
        limit: int,
        strategy_source: StrategySource,
    ) -> list[CandidateRecord]:
        if self.cache is not None:
            cached = await self.cache.load(strategy_source, query)
            if cached is not None:
                self.logger.info(
                    "finviz_runner_cache_hit",
                    strategy_source=strategy_source,
                    hash=query.stable_hash(),
                )
                return cached
        async with self.semaphore:
            rows = await self.browser.capture_snapshot(query, limit=limit)
        if self.cache is not None:
            await self.cache.store(strategy_source, query, rows)
        return rows

    @staticmethod
    def _merge_and_rank(
        rows: list[CandidateRecord],
        *,
        limit: int,
        strategy_source: StrategySource,
    ) -> list[CandidateRecord]:
        best_by_ticker: dict[str, CandidateRecord] = {}
        for row in rows:
            ticker = row.ticker.upper()
            existing = best_by_ticker.get(ticker)
            if existing is None or _rank_value(row) < _rank_value(existing):
                best_by_ticker[ticker] = row
        merged = sorted(best_by_ticker.values(), key=_rank_value)
        result: list[CandidateRecord] = []
        for new_rank, row in enumerate(merged[:limit], start=1):
            result.append(
                replace(row, screener_rank=new_rank, strategy_source=strategy_source)
            )
        return result


def _rank_value(row: CandidateRecord) -> int:
    return row.screener_rank if row.screener_rank is not None else 10_000
