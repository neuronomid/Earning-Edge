from __future__ import annotations

import asyncio
import io
from collections.abc import Callable, Mapping, Sequence
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.repositories.open_position_repo import OpenPositionRepository
from app.db.session import get_sessionmaker
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    ScreenerStatus,
    StrategyEventSignal,
    StrategyRunStatus,
    StrategySource,
)
from app.services.finviz.runner import FinvizQueryRunner
from app.services.finviz.strategies import (
    STRATEGY_C_BASE,
    STRATEGY_C_EARNINGS_PREFIX,
    STRATEGY_C_EARNINGS_VALUES,
)
from app.services.market_data.service import get_market_data_service
from app.services.market_data.types import MarketSnapshot
from app.services.strategy_catalog import build_strategy_report

PEAD_STRATEGY_SOURCE: StrategySource = "pead_continuation"
_PEAD_FINVIZ_LIMIT = 20
_EXCLUDED_SECTOR_TERMS = ("technology", "communication services")
_ZERO = Decimal("0")
_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class MarketDataSource(Protocol):
    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot: ...


class PEADSurpriseSource(Protocol):
    name: str

    async def get_earnings_event(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None: ...


class OpenCatalystPositionSource(Protocol):
    async def active_catalyst_tickers(self, *, as_of: date) -> frozenset[str]: ...


@dataclass(slots=True, frozen=True)
class PEADEarningsEvent:
    surprise_pct: Decimal
    announcement_date: date | None
    source: str


@dataclass(slots=True, frozen=True)
class PEADEnrichedRow:
    record: CandidateRecord
    surprise_pct: Decimal
    day1_change_pct: Decimal
    announcement_date: date | None
    score: Decimal


class PEADCandidateService:
    slug: StrategySource = PEAD_STRATEGY_SOURCE

    def __init__(
        self,
        runner: FinvizQueryRunner,
        *,
        market_data: MarketDataSource | None = None,
        surprise_sources: Sequence[PEADSurpriseSource] | None = None,
        open_positions: OpenCatalystPositionSource | None = None,
        settings: Settings | None = None,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.runner = runner
        self.settings = settings or get_settings()
        self.market_data = market_data or get_market_data_service()
        self.surprise_sources = tuple(
            surprise_sources
            or (
                YFinancePEADSurpriseSource(),
                FinnhubPEADSurpriseSource(api_key=self.settings.finnhub_api_key),
                AlphaVantagePEADSurpriseSource(api_key=self.settings.alpha_vantage_api_key),
            )
        )
        self.open_positions = open_positions or _NoOpenCatalystPositionSource()
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
        try:
            rows = await self.runner.run_with_swap(
                STRATEGY_C_BASE,
                swap_prefix=STRATEGY_C_EARNINGS_PREFIX,
                swap_values=STRATEGY_C_EARNINGS_VALUES,
                limit=_PEAD_FINVIZ_LIMIT,
                strategy_source=PEAD_STRATEGY_SOURCE,
            )
        except Exception as exc:
            self.logger.warning("pead_finviz_failed", error=str(exc))
            return self._build_batch((), raw_row_count=0, report_status="empty", error=str(exc))

        if not rows:
            return self._build_batch((), raw_row_count=0, report_status="empty")

        active_catalyst_tickers = await self._active_catalyst_tickers()
        enriched_results = await asyncio.gather(
            *(self._enrich(row) for row in rows),
            return_exceptions=True,
        )

        enriched: list[PEADEnrichedRow] = []
        for row, result in zip(rows, enriched_results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "pead_row_enrichment_failed",
                    ticker=row.ticker,
                    error=str(result),
                )
                continue
            if result is None:
                continue
            if result.record.ticker.upper() in active_catalyst_tickers:
                self.logger.info(
                    "pead_skipped_open_catalyst_position",
                    ticker=result.record.ticker,
                )
                continue
            enriched.append(result)

        ranked = sorted(
            enriched,
            key=lambda item: (item.score, _rank_sort_value(item.record)),
            reverse=True,
        )
        final_rows = tuple(item.record for item in ranked[:limit])
        if not final_rows:
            return self._build_batch((), raw_row_count=len(rows), report_status="empty")
        return self._build_batch(
            final_rows,
            raw_row_count=len(rows),
            report_status="success",
            screener_status="success" if len(final_rows) >= limit else "partial",
        )

    async def _enrich(self, row: CandidateRecord) -> PEADEnrichedRow | None:
        event = await self._compute_surprise(row.ticker)
        if event is None:
            self.logger.info("pead_rejected_no_surprise_data", ticker=row.ticker)
            return None

        snapshot = await self._fetch_market_snapshot_if_needed(row)
        sector = row.sector or (None if snapshot is None else snapshot.sector)
        market_cap = row.market_cap or (None if snapshot is None else snapshot.market_cap)
        current_price = row.current_price or (None if snapshot is None else snapshot.current_price)
        day1_change = _day1_change_pct(row, snapshot)

        rejection = self._post_filter(
            surprise_pct=event.surprise_pct,
            day1_change_pct=day1_change,
            sector=sector,
            market_cap=market_cap,
            announcement_date=event.announcement_date,
        )
        if rejection is not None:
            self.logger.info("pead_row_rejected", ticker=row.ticker, reason=rejection)
            return None

        assert day1_change is not None
        assert sector is not None
        assert market_cap is not None
        score = self._score_c(
            surprise_pct=event.surprise_pct,
            day1_change_pct=day1_change,
            sector=sector,
        )
        event_signal = _event_signal(
            surprise_pct=event.surprise_pct,
            day1_change_pct=day1_change,
            settings=self.settings,
        )
        record = replace(
            row,
            sector=sector,
            market_cap=market_cap,
            current_price=current_price,
            earnings_date=event.announcement_date,
            earnings_date_verified=event.announcement_date is not None,
            validation_notes=tuple(
                dict.fromkeys(
                    (
                        *row.validation_notes,
                        f"PEAD surprise source: {event.source}",
                        f"PEAD composite score: {score.quantize(Decimal('0.0001'))}",
                    )
                )
            ),
            strategy_source=PEAD_STRATEGY_SOURCE,
            event_signal=event_signal,
        )
        return PEADEnrichedRow(
            record=record,
            surprise_pct=event.surprise_pct,
            day1_change_pct=day1_change,
            announcement_date=event.announcement_date,
            score=score,
        )

    async def _compute_surprise(self, ticker: str) -> PEADEarningsEvent | None:
        as_of = self.today_provider()
        for source in self.surprise_sources:
            try:
                event = await source.get_earnings_event(ticker, as_of=as_of)
            except Exception as exc:
                self.logger.warning(
                    "pead_surprise_source_failed",
                    ticker=ticker,
                    source=source.name,
                    error=str(exc),
                )
                continue
            if event is not None:
                return event
        return None

    async def _fetch_market_snapshot_if_needed(
        self,
        row: CandidateRecord,
    ) -> MarketSnapshot | None:
        if (
            row.sector is not None
            and row.market_cap is not None
            and row.daily_change_percent is not None
        ):
            return None
        try:
            return await self.market_data.fetch(row.ticker, alpha_vantage_api_key=None)
        except Exception as exc:
            self.logger.warning("pead_market_data_failed", ticker=row.ticker, error=str(exc))
            return None

    async def _active_catalyst_tickers(self) -> frozenset[str]:
        try:
            return await self.open_positions.active_catalyst_tickers(as_of=self.today_provider())
        except Exception as exc:
            self.logger.warning("pead_open_position_lookup_failed", error=str(exc))
            return frozenset()

    def _post_filter(
        self,
        *,
        surprise_pct: Decimal,
        day1_change_pct: Decimal | None,
        sector: str | None,
        market_cap: Decimal | None,
        announcement_date: date | None,
    ) -> str | None:
        if surprise_pct < self.settings.pead_min_surprise_pct:
            return "surprise below threshold"
        if day1_change_pct is None:
            return "day-1 reaction unavailable"
        if day1_change_pct < self.settings.pead_min_day1_reaction:
            return "day-1 reaction below threshold"
        if sector is None:
            return "sector unavailable"
        if _is_excluded_sector(sector):
            return "sector excluded"
        if market_cap is None:
            return "market cap unavailable"
        if market_cap < self.settings.pead_min_market_cap_usd:
            return "market cap below PEAD range"
        if market_cap > self.settings.pead_max_market_cap_usd:
            return "market cap above PEAD range"
        today = self.today_provider()
        if announcement_date == today:
            return "same-day earnings announcement"
        if announcement_date is not None and announcement_date > today:
            return "future earnings announcement"
        return None

    def _score_c(
        self,
        *,
        surprise_pct: Decimal,
        day1_change_pct: Decimal,
        sector: str,
    ) -> Decimal:
        non_tech_bonus = _ZERO if _is_excluded_sector(sector) else _ONE
        return (
            (surprise_pct / self.settings.pead_min_surprise_pct) * Decimal("0.50")
            + (day1_change_pct / self.settings.pead_min_day1_reaction) * Decimal("0.30")
            + non_tech_bonus * Decimal("0.20")
        )

    def _build_batch(
        self,
        rows: tuple[CandidateRecord, ...],
        *,
        raw_row_count: int,
        report_status: StrategyRunStatus,
        screener_status: ScreenerStatus | None = None,
        error: str | None = None,
    ) -> CandidateBatch:
        status = screener_status or ("success" if rows else "empty")
        return CandidateBatch(
            candidates=rows,
            screener_status=status,
            fallback_used=False,
            strategy_reports=(
                build_strategy_report(
                    PEAD_STRATEGY_SOURCE,
                    status=report_status,
                    raw_row_count=raw_row_count,
                    candidate_count=len(rows),
                    finviz_candidate_count=len(rows),
                    backup_candidate_count=0,
                    error=error,
                ),
            ),
        )


class YFinancePEADSurpriseSource:
    name = "yfinance"

    async def get_earnings_event(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None:
        return await asyncio.to_thread(self._get_earnings_event_sync, ticker, as_of=as_of)

    def _get_earnings_event_sync(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None:
        import yfinance as yf  # type: ignore[import-untyped]

        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            ticker_client = yf.Ticker(ticker)
            get_earnings_history = getattr(ticker_client, "get_earnings_history", None)
            payload = get_earnings_history() if callable(get_earnings_history) else None
        return _latest_event_from_payload(payload, as_of=as_of, source=self.name)


class FinnhubPEADSurpriseSource:
    BASE_URL = "https://finnhub.io/api/v1"
    name = "finnhub"

    def __init__(
        self,
        api_key: str = "",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client

    async def get_earnings_event(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None:
        if not self.api_key.strip():
            return None
        params = {"symbol": ticker.upper(), "token": self.api_key.strip()}
        if self.client is not None:
            payload = await self._request_json(self.client, "/stock/earnings", params=params)
        else:
            async with httpx.AsyncClient(base_url=self.BASE_URL, timeout=20.0) as client:
                payload = await self._request_json(client, "/stock/earnings", params=params)
        return _latest_event_from_payload(payload, as_of=as_of, source=self.name)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str],
    ) -> Any:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()


class AlphaVantagePEADSurpriseSource:
    URL = "https://www.alphavantage.co/query"
    name = "alphavantage"

    def __init__(
        self,
        api_key: str = "",
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.client = client

    async def get_earnings_event(
        self,
        ticker: str,
        *,
        as_of: date,
    ) -> PEADEarningsEvent | None:
        if not self.api_key.strip():
            return None
        params = {
            "function": "EARNINGS",
            "symbol": ticker.upper(),
            "apikey": self.api_key.strip(),
        }
        if self.client is not None:
            payload = await self._request_json(self.client, params=params)
        else:
            async with httpx.AsyncClient(timeout=20.0) as client:
                payload = await self._request_json(client, params=params)
        return _latest_event_from_payload(payload, as_of=as_of, source=self.name)

    async def _request_json(
        self,
        client: httpx.AsyncClient,
        *,
        params: dict[str, str],
    ) -> Any:
        response = await client.get(self.URL, params=params)
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, Mapping) and any(key in payload for key in ("Note", "Information")):
            return None
        return payload


class _NoOpenCatalystPositionSource:
    async def active_catalyst_tickers(self, *, as_of: date) -> frozenset[str]:
        del as_of
        return frozenset()


class DatabaseOpenCatalystPositionSource:
    def __init__(
        self,
        sessionmaker: Callable[[], Any] | None = None,
        *,
        lookback_days: int = 7,
    ) -> None:
        self.sessionmaker = sessionmaker or get_sessionmaker()
        self.lookback_days = lookback_days

    async def active_catalyst_tickers(self, *, as_of: date) -> frozenset[str]:
        cutoff = as_of - timedelta(days=self.lookback_days)
        async with self.sessionmaker() as session:
            rows = await OpenPositionRepository(session).list_active_with_recommendations()
        return frozenset(
            recommendation.ticker.upper()
            for position, recommendation in rows
            if recommendation.strategy_source == "catalyst_confluence"
            and position.entry_at.date() >= cutoff
        )


def _day1_change_pct(
    row: CandidateRecord,
    snapshot: MarketSnapshot | None,
) -> Decimal | None:
    raw = row.daily_change_percent
    if raw is None and snapshot is not None:
        raw = snapshot.stock_returns.one_day
    return _normalize_ratio(raw)


def _event_signal(
    *,
    surprise_pct: Decimal,
    day1_change_pct: Decimal,
    settings: Settings,
) -> StrategyEventSignal:
    raw_score = min(
        Decimal("100"),
        (surprise_pct / settings.pead_min_surprise_pct) * Decimal("50")
        + (day1_change_pct / settings.pead_min_day1_reaction) * Decimal("50"),
    )
    return StrategyEventSignal(
        score=int(raw_score),
        is_supportive=True,
        detail=f"Earnings surprise {surprise_pct:.1%}, day-1 reaction {day1_change_pct:+.1%}",
    )


def _latest_event_from_payload(
    payload: Any,
    *,
    as_of: date,
    source: str,
) -> PEADEarningsEvent | None:
    events: list[PEADEarningsEvent] = []
    for row, fallback_date in _iter_payload_rows(payload):
        announcement_date = _event_date(row, fallback_date=fallback_date)
        if announcement_date is not None and announcement_date > as_of:
            continue
        surprise = _surprise_pct(row)
        if surprise is None:
            continue
        events.append(
            PEADEarningsEvent(
                surprise_pct=surprise,
                announcement_date=announcement_date,
                source=source,
            )
        )
    if not events:
        return None
    return max(events, key=lambda event: event.announcement_date or date.min)


def _iter_payload_rows(payload: Any) -> list[tuple[Mapping[str, Any], date | None]]:
    if payload is None:
        return []

    iterrows = getattr(payload, "iterrows", None)
    if callable(iterrows):
        rows: list[tuple[Mapping[str, Any], date | None]] = []
        for index, row in iterrows():
            rows.append((_coerce_mapping(row), _to_date(index)))
        return rows

    if isinstance(payload, Mapping):
        for key in (
            "quarterlyEarnings",
            "earnings",
            "earningsCalendar",
            "earningsHistory",
            "history",
        ):
            nested = payload.get(key)
            if isinstance(nested, list):
                return [(_coerce_mapping(item), None) for item in nested]
        return [(payload, None)]

    if isinstance(payload, list):
        return [(_coerce_mapping(item), None) for item in payload]

    return []


def _surprise_pct(row: Mapping[str, Any]) -> Decimal | None:
    for key in (
        "surprisePercent",
        "surprisePercentage",
        "surprise_percentage",
        "Surprise(%)",
        "Surprise %",
        "EPS Surprise",
    ):
        value = _normalize_ratio(_to_decimal(row.get(key)))
        if value is not None:
            return value

    actual = _first_decimal(
        row,
        (
            "actual",
            "epsActual",
            "reportedEPS",
            "Reported EPS",
            "Reported_EPS",
        ),
    )
    estimate = _first_decimal(
        row,
        (
            "estimate",
            "epsEstimate",
            "estimatedEPS",
            "EPS Estimate",
            "Estimated_EPS",
        ),
    )
    if actual is None or estimate in {None, _ZERO}:
        return None
    assert estimate is not None
    return (actual - estimate) / abs(estimate)


def _event_date(row: Mapping[str, Any], *, fallback_date: date | None) -> date | None:
    for key in (
        "date",
        "period",
        "reportedDate",
        "reportDate",
        "earningsDate",
        "Earnings Date",
        "fiscalDateEnding",
    ):
        parsed = _to_date(row.get(key))
        if parsed is not None:
            return parsed
    return fallback_date


def _first_decimal(row: Mapping[str, Any], keys: tuple[str, ...]) -> Decimal | None:
    for key in keys:
        value = _to_decimal(row.get(key))
        if value is not None:
            return value
    return None


def _coerce_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            mapped = to_dict()
        except Exception:
            return {}
        if isinstance(mapped, Mapping):
            return mapped
    return {}


def _to_decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _to_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _normalize_ratio(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    if abs(value) >= _ONE:
        return value / _HUNDRED
    return value


def _is_excluded_sector(sector: str) -> bool:
    normalized = sector.strip().lower()
    return any(term in normalized for term in _EXCLUDED_SECTOR_TERMS)


def _rank_sort_value(row: CandidateRecord) -> Decimal:
    if row.screener_rank is None:
        return Decimal("-10000")
    return Decimal(-row.screener_rank)


def get_pead_candidate_service(runner: FinvizQueryRunner) -> PEADCandidateService:
    return PEADCandidateService(
        runner,
        market_data=get_market_data_service(),
        open_positions=DatabaseOpenCatalystPositionSource(),
    )
