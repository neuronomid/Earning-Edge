from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    ScreenerStatus,
    StrategyEventSignal,
    StrategyRunStatus,
    StrategySource,
)
from app.services.finviz.query import FinvizQuery
from app.services.finviz.runner import FinvizQueryRunner
from app.services.finviz.strategies import STRATEGY_D_SECTOR_PREFIX, build_strategy_d_query
from app.services.strategy_catalog import build_strategy_report

SECTOR_RS_STRATEGY_SOURCE: StrategySource = "sector_relative_strength"

_NON_TECH_SECTORS: tuple[tuple[str, str], ...] = (
    ("XLE", "sec_energy"),
    ("XLF", "sec_financial"),
    ("XLI", "sec_industrials"),
    ("XLV", "sec_healthcare"),
    ("XLU", "sec_utilities"),
    ("XLP", "sec_consumerdefensive"),
    ("XLY", "sec_consumercyclical"),
    ("XLB", "sec_basicmaterials"),
    ("XLRE", "sec_realestate"),
)
_EXCLUDED_ETFS = frozenset({"XLK", "XLC"})
_FOUR_WEEK_LOOKBACK_SESSIONS = 21
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class SectorPriceSource(Protocol):
    async def fetch_closes(self, etfs: Sequence[str]) -> Mapping[str, tuple[Decimal, ...]]: ...


@dataclass(slots=True, frozen=True)
class RankedSector:
    etf: str
    sector_filter: str
    perf_4w: Decimal
    above_sma: bool


@dataclass(slots=True, frozen=True)
class ScreenedSectorRow:
    record: CandidateRecord
    sector: RankedSector
    stock_rank: int
    sector_row_count: int


@dataclass(slots=True, frozen=True)
class SectorScreenResult:
    sector: RankedSector
    query: FinvizQuery
    rows: tuple[ScreenedSectorRow, ...]
    error: str | None = None


class SectorRelativeStrengthService:
    slug: StrategySource = SECTOR_RS_STRATEGY_SOURCE

    def __init__(
        self,
        runner: FinvizQueryRunner,
        *,
        price_source: SectorPriceSource | None = None,
        settings: Settings | None = None,
        logger: Any | None = None,
    ) -> None:
        self.runner = runner
        self.price_source = price_source or YFinanceSectorPriceSource()
        self.settings = settings or get_settings()
        self.logger = logger or get_logger(__name__)

    async def get_top_five(
        self,
        *,
        limit: int = 5,
        user_id: UUID | None = None,
    ) -> CandidateBatch:
        del user_id
        try:
            ranked_sectors = await self._rank_sectors()
        except Exception as exc:
            self.logger.warning("sector_rs_yfinance_failed", error=str(exc))
            return self._empty_batch("yfinance unavailable", error=str(exc))

        if not ranked_sectors:
            return self._empty_batch("yfinance unavailable")

        top_sector = ranked_sectors[0]
        if not self._regime_gate(top_sector.above_sma, top_sector.perf_4w):
            return self._empty_batch("regime gate blocked")

        screen_results: list[SectorScreenResult] = []
        top_result = await self._screen_sector(top_sector, limit=limit)
        screen_results.append(top_result)
        screened_rows = list(top_result.rows)

        if len(screened_rows) < limit:
            second_sector = next(
                (
                    sector
                    for sector in ranked_sectors[1:]
                    if self._regime_gate(sector.above_sma, sector.perf_4w)
                ),
                None,
            )
            if second_sector is not None:
                second_result = await self._screen_sector(
                    second_sector,
                    limit=limit - len(screened_rows),
                )
                screen_results.append(second_result)
                screened_rows.extend(second_result.rows)

        ranked_rows = sorted(
            screened_rows,
            key=lambda row: (
                self._score_d(row),
                row.sector.perf_4w,
                -row.stock_rank,
                row.record.ticker,
            ),
            reverse=True,
        )[:limit]
        final_rows = self._with_event_signals(ranked_rows, ranked_sectors)

        if not final_rows:
            return self._build_batch(
                (),
                raw_row_count=sum(len(result.rows) for result in screen_results),
                report_status="empty",
                screener_status="empty",
                screen_results=tuple(screen_results),
                error=_join_errors(screen_results),
            )

        screener_status: ScreenerStatus = "success" if len(final_rows) >= limit else "partial"
        return self._build_batch(
            final_rows,
            raw_row_count=sum(len(result.rows) for result in screen_results),
            report_status="success",
            screener_status=screener_status,
            screen_results=tuple(screen_results),
            error=_join_errors(screen_results),
        )

    async def _rank_sectors(self) -> tuple[RankedSector, ...]:
        sector_pairs = tuple(
            (etf, sector_filter)
            for etf, sector_filter in _NON_TECH_SECTORS
            if etf not in _EXCLUDED_ETFS
        )
        histories = await self.price_source.fetch_closes(tuple(etf for etf, _ in sector_pairs))
        ranked: list[RankedSector] = []
        for etf, sector_filter in sector_pairs:
            sector = self._rank_sector(etf, sector_filter, histories.get(etf, ()))
            if sector is not None:
                ranked.append(sector)
        return tuple(sorted(ranked, key=lambda sector: sector.perf_4w, reverse=True))

    def _rank_sector(
        self,
        etf: str,
        sector_filter: str,
        closes: Sequence[Decimal],
    ) -> RankedSector | None:
        if len(closes) < _FOUR_WEEK_LOOKBACK_SESSIONS:
            return None
        latest = closes[-1]
        lookback = closes[-_FOUR_WEEK_LOOKBACK_SESSIONS]
        if lookback == _ZERO:
            return None
        perf_4w = (latest / lookback) - _ONE
        sma_window = max(1, self.settings.sector_rs_sma_window)
        sma_values = tuple(closes[-sma_window:])
        sma = sum(sma_values, _ZERO) / Decimal(len(sma_values))
        return RankedSector(
            etf=etf,
            sector_filter=sector_filter,
            perf_4w=perf_4w,
            above_sma=latest >= sma,
        )

    def _regime_gate(self, above_sma: bool, perf_4w: Decimal) -> bool:
        return above_sma and perf_4w >= self.settings.sector_rs_min_4w_return

    async def _screen_sector(
        self,
        sector: RankedSector,
        *,
        limit: int,
    ) -> SectorScreenResult:
        query = build_strategy_d_query(sector.sector_filter)
        try:
            rows = await self.runner.run_with_swap(
                query,
                swap_prefix=STRATEGY_D_SECTOR_PREFIX,
                swap_values=(sector.sector_filter,),
                limit=limit,
                strategy_source=SECTOR_RS_STRATEGY_SOURCE,
            )
        except Exception as exc:
            self.logger.warning(
                "sector_rs_finviz_failed",
                etf=sector.etf,
                sector_filter=sector.sector_filter,
                error=str(exc),
            )
            return SectorScreenResult(sector=sector, query=query, rows=(), error=str(exc))

        row_count = len(rows)
        screened = tuple(
            ScreenedSectorRow(
                record=replace(
                    row,
                    strategy_source=SECTOR_RS_STRATEGY_SOURCE,
                    validation_notes=tuple(
                        dict.fromkeys(
                            (
                                *row.validation_notes,
                                f"Sector RS source: {sector.etf}",
                                f"Sector RS 4w return: {sector.perf_4w:.1%}",
                            )
                        )
                    ),
                ),
                sector=sector,
                stock_rank=row.screener_rank or index,
                sector_row_count=row_count,
            )
            for index, row in enumerate(rows[:limit], start=1)
        )
        return SectorScreenResult(sector=sector, query=query, rows=screened)

    def _score_d(self, row: ScreenedSectorRow) -> Decimal:
        sector_alignment_score = (
            Decimal("1.0") if row.sector.perf_4w > Decimal("0.05") else Decimal("0.5")
        )
        return _stock_percentile(row.stock_rank, row.sector_row_count) * Decimal(
            "0.60"
        ) + sector_alignment_score * Decimal("0.40")

    def _with_event_signals(
        self,
        rows: list[ScreenedSectorRow],
        ranked_sectors: tuple[RankedSector, ...],
    ) -> tuple[CandidateRecord, ...]:
        total_rows = len(rows)
        if total_rows == 0:
            return ()
        sector_positions = {
            sector.sector_filter: index for index, sector in enumerate(ranked_sectors, start=1)
        }
        sector_total = len(ranked_sectors)
        final_rows: list[CandidateRecord] = []
        for index, row in enumerate(rows, start=1):
            sector_rank = sector_positions[row.sector.sector_filter]
            sector_percentile = _visible_percentile(index=sector_rank, total=sector_total)
            stock_percentile = _visible_percentile(index=index, total=total_rows)
            raw_score = min(
                _HUNDRED,
                sector_percentile * Decimal("60") + stock_percentile * Decimal("40"),
            )
            event_signal = StrategyEventSignal(
                score=int(raw_score),
                is_supportive=True,
                detail=(
                    f"{row.sector.etf} sector {row.sector.perf_4w:+.1%} (4w), "
                    f"stock screen percentile {stock_percentile:.0%}"
                ),
            )
            final_rows.append(replace(row.record, event_signal=event_signal))
        return tuple(final_rows)

    def _empty_batch(
        self,
        reason: str,
        *,
        error: str | None = None,
    ) -> CandidateBatch:
        return self._build_batch(
            (),
            raw_row_count=0,
            report_status="empty",
            screener_status="empty",
            screen_results=(),
            report_warning=reason,
            error=error,
        )

    def _build_batch(
        self,
        rows: tuple[CandidateRecord, ...],
        *,
        raw_row_count: int,
        report_status: StrategyRunStatus,
        screener_status: ScreenerStatus,
        screen_results: tuple[SectorScreenResult, ...],
        report_warning: str | None = None,
        error: str | None = None,
    ) -> CandidateBatch:
        queries = tuple(result.query for result in screen_results)
        return CandidateBatch(
            candidates=rows,
            screener_status=screener_status,
            fallback_used=False,
            strategy_reports=(
                build_strategy_report(
                    SECTOR_RS_STRATEGY_SOURCE,
                    status=report_status,
                    raw_row_count=raw_row_count,
                    candidate_count=len(rows),
                    finviz_candidate_count=len(rows),
                    backup_candidate_count=0,
                    warning_text=report_warning,
                    error=error,
                    query_urls=tuple(query.to_url() for query in queries),
                    filter_codes=tuple(
                        dict.fromkeys(
                            filter_code for query in queries for filter_code in query.filters
                        )
                    ),
                ),
            ),
        )


class YFinanceSectorPriceSource:
    def __init__(self, *, period: str = "2mo", interval: str = "1d") -> None:
        self.period = period
        self.interval = interval

    async def fetch_closes(self, etfs: Sequence[str]) -> Mapping[str, tuple[Decimal, ...]]:
        return await asyncio.to_thread(self._fetch_closes_sync, tuple(etfs))

    def _fetch_closes_sync(self, etfs: tuple[str, ...]) -> Mapping[str, tuple[Decimal, ...]]:
        import yfinance as yf  # type: ignore[import-untyped]

        frame = yf.download(
            list(etfs),
            period=self.period,
            interval=self.interval,
            progress=False,
            auto_adjust=False,
        )
        return _extract_close_histories(frame, etfs)


def _extract_close_histories(
    frame: Any,
    etfs: Sequence[str],
) -> dict[str, tuple[Decimal, ...]]:
    return {etf: _extract_close_history(frame, etf) for etf in etfs}


def _extract_close_history(frame: Any, etf: str) -> tuple[Decimal, ...]:
    close_frame = _getitem_or_none(frame, "Close")
    if close_frame is not None:
        column = _column_or_none(close_frame, etf)
        if column is not None:
            return _series_to_decimals(column)
        return _series_to_decimals(close_frame)

    for key in ((etf, "Close"), ("Close", etf)):
        column = _getitem_or_none(frame, key)
        if column is not None:
            return _series_to_decimals(column)
    return ()


def _getitem_or_none(value: Any, key: Any) -> Any | None:
    try:
        return value[key]
    except Exception:
        return None


def _column_or_none(frame: Any, column: str) -> Any | None:
    get = getattr(frame, "get", None)
    if callable(get):
        try:
            value = get(column)
        except Exception:
            value = None
        if value is not None:
            return value
    return _getitem_or_none(frame, column)


def _series_to_decimals(series: Any) -> tuple[Decimal, ...]:
    dropna = getattr(series, "dropna", None)
    if callable(dropna):
        series = dropna()

    values: Any
    tolist = getattr(series, "tolist", None)
    if callable(tolist):
        values = tolist()
    else:
        try:
            values = list(series)
        except TypeError:
            values = [series]

    decimals: list[Decimal] = []
    for value in values:
        converted = _to_decimal(value)
        if converted is not None:
            decimals.append(converted)
    return tuple(decimals)


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        decimal = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not decimal.is_finite():
        return None
    return decimal


def _stock_percentile(rank: int, total: int) -> Decimal:
    return _visible_percentile(index=rank, total=total)


def _visible_percentile(*, index: int, total: int) -> Decimal:
    if total <= 0:
        return _ZERO
    clamped = max(1, min(index, total))
    return Decimal(total - clamped + 1) / Decimal(total)


def _join_errors(results: Sequence[SectorScreenResult]) -> str | None:
    errors = tuple(result.error for result in results if result.error)
    return "; ".join(errors) if errors else None


def get_sector_relative_strength_service(
    runner: FinvizQueryRunner,
) -> SectorRelativeStrengthService:
    return SectorRelativeStrengthService(runner)
