from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Sequence
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource
from app.services.earnings_calendar.reconciler import (
    CandidateReconciler,
    CandidateValidationError,
)
from app.services.earnings_calendar.yfinance_source import YFinanceEarningsSource
from app.services.finviz.browser import FinvizBrowserClient
from app.services.finviz.runner import FinvizQueryRunner
from app.services.finviz.strategies import (
    STRATEGY_A_BASE,
    STRATEGY_A_EARNINGS_PREFIX,
    STRATEGY_A_EARNINGS_VALUES,
)
from app.services.strategy_catalog import build_strategy_report

CATALYST_STRATEGY_SOURCE = "catalyst_confluence"

FINVIZ_FALLBACK_WARNING = (
    "⚠️ Finviz did not load correctly, so I used backup earnings data for this scan."
)
FINVIZ_INFERRED_DATE_NOTE = "earnings date inferred from Finviz catalyst-window screener"
FINVIZ_CONFLICT_NOTE = (
    "backup earnings date conflicted with Finviz catalyst-window screener; "
    "kept visible screener row"
)


class CandidateSelectionError(RuntimeError):
    """Raised when phase-4 candidate selection cannot yield usable rows."""


class CandidateDataSource(Protocol):
    async def get_candidate_details(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None: ...

    async def list_upcoming_candidates(
        self,
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]: ...


class CandidateService:
    def __init__(
        self,
        runner: FinvizQueryRunner,
        *,
        sources: Sequence[CandidateDataSource],
        reconciler: CandidateReconciler | None = None,
        today_provider: Callable[[], date] | None = None,
        logger=None,
    ) -> None:
        self.runner = runner
        self.sources = tuple(sources)
        self.reconciler = reconciler or CandidateReconciler()
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self) -> CandidateBatch:
        window = next_week_window(self.today_provider())

        try:
            extracted = await self.runner.run_with_swap(
                STRATEGY_A_BASE,
                swap_prefix=STRATEGY_A_EARNINGS_PREFIX,
                swap_values=STRATEGY_A_EARNINGS_VALUES,
                limit=5,
                strategy_source=CATALYST_STRATEGY_SOURCE,
            )
            if not extracted:
                raise CandidateSelectionError(
                    "Strategy A returned no rows from Finviz"
                )
            self.logger.info(
                "candidate_service_finviz_rows_extracted",
                window_start=window[0].isoformat(),
                window_end=window[1].isoformat(),
                tickers=[row.ticker for row in extracted],
            )
        except Exception as exc:
            backup_rows = await self._load_backup_candidates(window=window, limit=5)
            validated = await self._validate_rows(backup_rows, window=window, limit=5)
            self.logger.warning(
                "candidate_service_finviz_failed",
                error=str(exc),
                backup_tickers=[row.ticker for row in validated[:5]],
            )
            final_rows = tuple(
                replace(row, strategy_source=CATALYST_STRATEGY_SOURCE)
                for row in validated[:5]
            )
            warning_text = FINVIZ_FALLBACK_WARNING if final_rows else None
            return CandidateBatch(
                candidates=final_rows,
                screener_status="failed",
                fallback_used=bool(final_rows),
                warning_text=warning_text,
                strategy_reports=(
                    build_strategy_report(
                        CATALYST_STRATEGY_SOURCE,
                        status="fallback" if final_rows else "failed",
                        raw_row_count=0,
                        candidate_count=len(final_rows),
                        finviz_candidate_count=_finviz_candidate_count(final_rows),
                        backup_candidate_count=_backup_candidate_count(final_rows),
                        fallback_used=bool(final_rows),
                        warning_text=warning_text,
                        error=str(exc),
                    ),
                ),
            )

        validated = await self._validate_rows(extracted, window=window, limit=5)
        if not validated:
            raise CandidateSelectionError(
                "Finviz produced no validated candidates"
            )
        self.logger.info(
            "candidate_service_candidates_selected",
            screener_tickers=[row.ticker for row in extracted],
            final_tickers=[row.ticker for row in validated[:5]],
            inferred_tickers=[
                row.ticker for row in validated[:5] if not row.earnings_date_verified
            ],
            fallback_used=any("finviz" not in row.sources for row in validated[:5]),
        )
        final_rows = tuple(
            replace(row, strategy_source=CATALYST_STRATEGY_SOURCE)
            for row in validated[:5]
        )
        fallback_used = any("finviz" not in row.sources for row in final_rows)
        return CandidateBatch(
            candidates=final_rows,
            screener_status="success" if len(final_rows) >= 5 else "partial",
            fallback_used=fallback_used,
            warning_text=None,
            strategy_reports=(
                build_strategy_report(
                    CATALYST_STRATEGY_SOURCE,
                    status="success",
                    raw_row_count=len(extracted),
                    candidate_count=len(final_rows),
                    finviz_candidate_count=_finviz_candidate_count(final_rows),
                    backup_candidate_count=_backup_candidate_count(final_rows),
                    fallback_used=fallback_used,
                ),
            ),
        )

    async def _validate_rows(
        self,
        rows: Sequence[CandidateRecord],
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]:
        validated: list[CandidateRecord] = []
        seen: set[str] = set()

        for row in rows:
            ticker = row.ticker.upper()
            if ticker in seen:
                continue
            candidate = await self._validate_row(row, window=window)
            if candidate is not None:
                validated.append(candidate)
                seen.add(candidate.ticker)
            if len(validated) >= limit:
                return validated[:limit]

        remaining = max(limit - len(validated), 0)
        if remaining == 0:
            return validated[:limit]

        supplemental_limit = max(remaining * 2, remaining + 2)
        supplemental = await self._load_backup_candidates(
            window=window,
            limit=supplemental_limit,
        )
        for row in supplemental:
            ticker = row.ticker.upper()
            if ticker in seen:
                continue
            candidate = await self._validate_row(row, window=window)
            if candidate is not None:
                validated.append(candidate)
                seen.add(candidate.ticker)
            if len(validated) >= limit:
                break
        return validated[:limit]

    async def _validate_row(
        self,
        row: CandidateRecord,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None:
        source_tasks = []
        for source in self.sources:
            source_name = getattr(source, "name", None)
            if source_name is not None and source_name in row.sources:
                continue
            source_tasks.append(source.get_candidate_details(row.ticker, window=window))
        details = await asyncio.gather(
            *source_tasks,
            return_exceptions=True,
        )
        candidates = [item for item in details if isinstance(item, CandidateRecord)]
        is_finviz_row = "finviz" in row.sources
        try:
            reconciled = self.reconciler.reconcile(
                row,
                candidates,
                allow_unverified_earnings_date=is_finviz_row,
                fallback_earnings_date=window[0] if is_finviz_row else None,
                fallback_note=FINVIZ_INFERRED_DATE_NOTE if is_finviz_row else None,
            )
        except CandidateValidationError:
            return None
        if reconciled.earnings_date is None:
            return None
        if not _date_in_window(reconciled.earnings_date, window=window):
            if not is_finviz_row:
                return None
            return replace(
                reconciled,
                earnings_date=window[0],
                earnings_date_verified=False,
                validation_notes=tuple(
                    dict.fromkeys(
                        (*reconciled.validation_notes, FINVIZ_CONFLICT_NOTE)
                    )
                ),
            )
        return reconciled

    async def _load_backup_candidates(
        self,
        *,
        window: tuple[date, date],
        limit: int,
    ) -> list[CandidateRecord]:
        results = await asyncio.gather(
            *[
                source.list_upcoming_candidates(window=window, limit=limit)
                for source in self.sources
            ],
            return_exceptions=True,
        )

        grouped: dict[str, list[CandidateRecord]] = defaultdict(list)
        for result in results:
            if not isinstance(result, list):
                continue
            for record in result:
                grouped[record.ticker.upper()].append(record)

        merged: list[CandidateRecord] = []
        for records in grouped.values():
            try:
                merged.append(self.reconciler.reconcile(records[0], records[1:]))
            except CandidateValidationError:
                continue

        merged.sort(key=lambda item: item.market_cap or Decimal("0"), reverse=True)
        return merged[:limit]


def _finviz_candidate_count(rows: tuple[CandidateRecord, ...]) -> int:
    return sum(1 for row in rows if "finviz" in row.sources)


def _backup_candidate_count(rows: tuple[CandidateRecord, ...]) -> int:
    return sum(1 for row in rows if "finviz" not in row.sources)


def next_week_window(today: date) -> tuple[date, date]:
    days_until_monday = 7 - today.weekday()
    if days_until_monday <= 0:
        days_until_monday += 7
    start = today + timedelta(days=days_until_monday)
    end = start + timedelta(days=6)
    return start, end


def _date_in_window(value: date, *, window: tuple[date, date]) -> bool:
    return window[0] <= value <= window[1]


@lru_cache(maxsize=1)
def get_candidate_service() -> CandidateService:
    settings = get_settings()
    browser = FinvizBrowserClient(
        headless=settings.finviz_headless,
        timeout_ms=settings.finviz_timeout_ms,
    )
    runner = FinvizQueryRunner(browser)
    return CandidateService(
        runner,
        sources=(
            YFinanceEarningsSource(),
            FinnhubEarningsSource(api_key=settings.finnhub_api_key),
        ),
    )


async def get_top_five() -> CandidateBatch:
    return await get_candidate_service().get_top_five()
