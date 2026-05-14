from __future__ import annotations

import asyncio
from functools import lru_cache
from typing import Any, Protocol, cast

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.activist_13d_service import get_activist_13d_candidate_service
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    ScreenerStatus,
    StrategyRunReport,
    StrategyRunStatus,
    StrategySource,
)
from app.services.candidate_service import CATALYST_STRATEGY_SOURCE, CandidateService
from app.services.coiled_setup_service import COILED_STRATEGY_SOURCE, CoiledSetupCandidateService
from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource
from app.services.earnings_calendar.yfinance_source import YFinanceEarningsSource
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.cache import CacheClient, FinvizScreenerCache
from app.services.finviz.runner import FinvizQueryRunner
from app.services.pead_service import get_pead_candidate_service
from app.services.run_lock import get_redis_client
from app.services.sector_relative_strength_service import get_sector_relative_strength_service
from app.services.strategy_catalog import build_strategy_report

CATALYST_ONLY_WARNING = (
    "⚠️ Coiled-setup screen returned no candidates this scan — showing catalyst-driven setups only."
)
COILED_ONLY_WARNING = (
    "⚠️ Catalyst screen returned no setups this scan — showing structure-driven candidates only."
)
BOTH_FAILED_WARNING = "⚠️ Both screening strategies failed to return candidates."
COILED_FAILED_WARNING = (
    "⚠️ Coiled-setup screen failed this scan — showing catalyst-driven candidates only."
)
CATALYST_FAILED_WARNING = (
    "⚠️ Catalyst screen failed this scan — showing structure-driven candidates only."
)


class ArmRunner(Protocol):
    slug: StrategySource

    async def get_top_five(self, *, limit: int = 5) -> CandidateBatch: ...


class _ArmOutcome:
    def __init__(
        self,
        *,
        slug: StrategySource,
        rows: list[CandidateRecord],
        report_status: StrategyRunStatus,
        failed: bool = False,
    ) -> None:
        self.slug = slug
        self.rows = rows
        self.report_status = report_status
        self.failed = failed


class MultiStrategyCandidateService:
    def __init__(
        self,
        arms: tuple[ArmRunner, ...],
        *,
        logger: Any | None = None,
    ) -> None:
        self.arms = arms
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self) -> CandidateBatch:
        return await self.get_candidates()

    async def get_candidates(self) -> CandidateBatch:
        results = await asyncio.gather(
            *(arm.get_top_five() for arm in self.arms),
            return_exceptions=True,
        )

        strategy_reports: list[StrategyRunReport] = []
        outcomes: dict[StrategySource, _ArmOutcome] = {}
        rows_by_arm: list[tuple[StrategySource, list[CandidateRecord]]] = []
        fallback_used = False
        fallback_warning: str | None = None

        for arm, result in zip(self.arms, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "multi_strategy_arm_failed",
                    strategy_source=arm.slug,
                    error=str(result),
                )
                report = build_strategy_report(
                    arm.slug,
                    status="failed",
                    raw_row_count=0,
                    candidate_count=0,
                    error=str(result),
                )
                strategy_reports.append(report)
                outcomes[arm.slug] = _ArmOutcome(
                    slug=arm.slug,
                    rows=[],
                    report_status="failed",
                    failed=True,
                )
                rows_by_arm.append((arm.slug, []))
                continue

            rows = list(result.candidates)
            rows_by_arm.append((arm.slug, rows))
            fallback_used = fallback_used or result.fallback_used
            if result.warning_text and fallback_warning is None:
                fallback_warning = result.warning_text

            arm_reports = tuple(
                report for report in result.strategy_reports if report.strategy_source == arm.slug
            )
            if arm_reports:
                strategy_reports.extend(arm_reports)
                report_status = arm_reports[-1].status
            else:
                report_status = _report_status_from_batch(result, rows)
                strategy_reports.append(
                    _build_default_report(
                        arm.slug,
                        rows=tuple(rows),
                        status=report_status,
                        fallback_used=result.fallback_used,
                        warning_text=result.warning_text,
                    )
                )

            outcomes[arm.slug] = _ArmOutcome(
                slug=arm.slug,
                rows=rows,
                report_status=report_status,
                failed=False,
            )

        merged = _merge_dedupe(rows_by_arm)

        screener_status: ScreenerStatus
        if not merged:
            screener_status = "failed"
        elif any(outcome.report_status in {"empty", "failed"} for outcome in outcomes.values()):
            screener_status = "partial"
        else:
            screener_status = "success"

        warning_text = _resolve_warning(
            outcomes=outcomes,
            total_rows=len(merged),
            fallback_warning=fallback_warning,
        )

        self.logger.info(
            "multi_strategy_merged",
            strategy_counts={slug: len(rows) for slug, rows in rows_by_arm},
            merged_count=len(merged),
            screener_status=screener_status,
        )

        return CandidateBatch(
            candidates=tuple(merged),
            screener_status=screener_status,
            fallback_used=fallback_used,
            warning_text=warning_text,
            strategy_reports=tuple(strategy_reports),
        )


def _merge_dedupe(
    rows_by_arm: list[tuple[StrategySource, list[CandidateRecord]]],
) -> list[CandidateRecord]:
    seen: set[str] = set()
    merged: list[CandidateRecord] = []
    for _, rows in rows_by_arm:
        for row in rows:
            ticker = row.ticker.upper()
            if ticker in seen:
                continue
            seen.add(ticker)
            merged.append(row)
    return merged


def _report_status_from_batch(
    batch: CandidateBatch,
    rows: list[CandidateRecord],
) -> StrategyRunStatus:
    if batch.screener_status == "empty":
        return "empty"
    if batch.screener_status == "failed":
        return "fallback" if rows and batch.fallback_used else "failed"
    return "success" if rows else "empty"


def _build_default_report(
    slug: StrategySource,
    *,
    rows: tuple[CandidateRecord, ...],
    status: StrategyRunStatus,
    fallback_used: bool,
    warning_text: str | None,
) -> StrategyRunReport:
    return build_strategy_report(
        slug,
        status=status,
        raw_row_count=len(rows),
        candidate_count=len(rows),
        finviz_candidate_count=sum(1 for row in rows if "finviz" in row.sources),
        backup_candidate_count=sum(1 for row in rows if "finviz" not in row.sources),
        fallback_used=fallback_used,
        warning_text=warning_text,
    )


def _resolve_warning(
    *,
    outcomes: dict[StrategySource, _ArmOutcome],
    total_rows: int,
    fallback_warning: str | None,
) -> str | None:
    catalyst = outcomes.get(CATALYST_STRATEGY_SOURCE)
    coiled = outcomes.get(COILED_STRATEGY_SOURCE)
    catalyst_rows = [] if catalyst is None else catalyst.rows
    coiled_rows = [] if coiled is None else coiled.rows
    non_legacy_rows = [
        row
        for slug, outcome in outcomes.items()
        if slug not in {CATALYST_STRATEGY_SOURCE, COILED_STRATEGY_SOURCE}
        for row in outcome.rows
    ]

    if total_rows == 0:
        return BOTH_FAILED_WARNING
    if catalyst_rows and not coiled_rows and not non_legacy_rows:
        coiled_failed = coiled is not None and coiled.failed
        return COILED_FAILED_WARNING if coiled_failed else CATALYST_ONLY_WARNING
    if coiled_rows and not catalyst_rows and not non_legacy_rows:
        catalyst_failed = catalyst is not None and catalyst.failed
        return CATALYST_FAILED_WARNING if catalyst_failed else COILED_ONLY_WARNING
    return fallback_warning


@lru_cache(maxsize=1)
def get_multi_strategy_service() -> MultiStrategyCandidateService:
    settings = get_settings()
    browser = FinvizBrowserClient(
        headless=settings.finviz_headless,
        timeout_ms=settings.finviz_timeout_ms,
    )
    cache = FinvizScreenerCache(
        cast(CacheClient, get_redis_client()),
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
    pead = get_pead_candidate_service(runner)
    sector_rs = get_sector_relative_strength_service(runner)
    activist_13d = get_activist_13d_candidate_service()
    return MultiStrategyCandidateService(
        (
            catalyst,
            pead,
            coiled,
            sector_rs,
            activist_13d,
        )
    )
