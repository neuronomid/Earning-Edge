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
from app.services.finviz.extractor import FinvizExtractor

FINVIZ_FALLBACK_WARNING = (
    "⚠️ Finviz did not load correctly, so I used backup earnings data for this scan."
)
FINVIZ_INFERRED_DATE_NOTE = "earnings date inferred from Finviz next-week screener"
FINVIZ_CONFLICT_NOTE = (
    "backup earnings date conflicted with Finviz next-week screener; kept visible screener row"
)


class CandidateSelectionError(RuntimeError):
    """Raised when phase-4 candidate selection cannot yield five usable rows."""


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
        extractor: FinvizExtractor,
        *,
        sources: Sequence[CandidateDataSource],
        reconciler: CandidateReconciler | None = None,
        today_provider: Callable[[], date] | None = None,
        logger=None,
    ) -> None:
        self.extractor = extractor
        self.sources = tuple(sources)
        self.reconciler = reconciler or CandidateReconciler()
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self) -> CandidateBatch:
        window = next_week_window(self.today_provider())

        try:
            extracted = await self.extractor.get_top_five(limit=5)
            self.logger.info(
                "candidate_service_finviz_rows_extracted",
                window_start=window[0].isoformat(),
                window_end=window[1].isoformat(),
                tickers=[row.ticker for row in extracted],
            )
        except Exception as exc:
            backup_rows = await self._load_backup_candidates(window=window, limit=5)
            if len(backup_rows) < 5:
                raise CandidateSelectionError(
                    "Finviz extraction failed and backup earnings candidates were not enough"
                ) from exc
            validated = await self._validate_rows(backup_rows, window=window, limit=5)
            if len(validated) < 5:
                raise CandidateSelectionError(
                    "Backup earnings sources did not produce five validated candidates"
                ) from exc
            self.logger.warning(
                "candidate_service_finviz_failed",
                error=str(exc),
                backup_tickers=[row.ticker for row in validated[:5]],
            )
            return CandidateBatch(
                candidates=tuple(validated[:5]),
                screener_status="failed",
                fallback_used=True,
                warning_text=FINVIZ_FALLBACK_WARNING,
            )

        validated = await self._validate_rows(extracted, window=window, limit=5)
        if len(validated) < 5:
            raise CandidateSelectionError(
                "Finviz produced fewer than five validated candidates"
            )
        self.logger.info(
            "candidate_service_candidates_selected",
            screener_tickers=[row.ticker for row in extracted],
            final_tickers=[row.ticker for row in validated[:5]],
            inferred_tickers=[
                row.ticker for row in validated[:5] if not row.earnings_date_verified
            ],
            fallback_used=False,
        )
        return CandidateBatch(
            candidates=tuple(validated[:5]),
            screener_status="success",
            fallback_used=False,
            warning_text=None,
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

        supplemental = await self._load_backup_candidates(window=window, limit=limit * 2)
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
        details = await asyncio.gather(
            *[
                source.get_candidate_details(row.ticker, window=window)
                for source in self.sources
            ],
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
    extractor = FinvizExtractor(browser)
    return CandidateService(
        extractor,
        sources=(
            YFinanceEarningsSource(),
            FinnhubEarningsSource(api_key=settings.finnhub_api_key),
        ),
    )


async def get_top_five() -> CandidateBatch:
    return await get_candidate_service().get_top_five()
