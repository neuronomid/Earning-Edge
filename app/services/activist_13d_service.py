from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.scoring.contract import liquidity_quality
from app.scoring.types import (
    OptionContractInput,
    StrategyPermission,
    option_premium,
    spread_percent,
)
from app.services.candidate_models import (
    CandidateBatch,
    CandidateRecord,
    ScreenerStatus,
    StrategyEventSignal,
    StrategyRunStatus,
    StrategySource,
)
from app.services.market_data.types import MarketSnapshot
from app.services.market_hours import market_sessions_between
from app.services.sec import scoring as sec_scoring
from app.services.sec.activist_13d_parser import ActivistFiling, parse_filing
from app.services.sec.filings_client import FilingHeader, SECFilingsClient
from app.services.sec.scoring import EventScoreInputs, compose_event_score
from app.services.strategy_catalog import build_strategy_report

ACTIVIST_13D_STRATEGY_SOURCE: StrategySource = "activist_13d_followthrough"
_TIER1_LIMIT = 5
_ZERO = Decimal("0")
_TECH_SECTOR_TERMS = ("technology", "communication services")
_MAX_UNIVERSE_OPTION_SPREAD = Decimal("0.35")
_MIN_UNIVERSE_OPTION_LIQUIDITY = 45
_TIER3_MAX_ONE_DAY_MOVE = Decimal("0.10")
_TIER3_MAX_FIVE_DAY_MOVE = Decimal("0.25")
_EARNINGS_LOOKAHEAD_DAYS = 30


class MarketDataSource(Protocol):
    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot: ...


class OptionChainSource(Protocol):
    async def get_chain(
        self,
        ticker: str,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: StrategyPermission,
        earnings_date: date | None = None,
        today: date | None = None,
    ) -> tuple[OptionContractInput, ...]: ...


class EarningsDetailsSource(Protocol):
    async def get_candidate_details(
        self,
        ticker: str,
        *,
        window: tuple[date, date],
    ) -> CandidateRecord | None: ...


@dataclass(slots=True, frozen=True)
class SelectedActivistFiling:
    filing: ActivistFiling
    tier: int


@dataclass(slots=True, frozen=True)
class OptionLiquidityResult:
    score: Decimal
    best_quality: int
    best_spread: Decimal | None
    usable_contract_count: int


@dataclass(slots=True, frozen=True)
class EnrichedActivistRow:
    filing: ActivistFiling
    tier: int
    snapshot: MarketSnapshot | None
    event_score: Decimal
    event_components: tuple[tuple[str, Decimal], ...]
    option_liquidity: OptionLiquidityResult
    days_to_next_earnings: int | None


class Activist13DCandidateService:
    slug: StrategySource = ACTIVIST_13D_STRATEGY_SOURCE

    def __init__(
        self,
        client: SECFilingsClient,
        *,
        market_data: MarketDataSource | None = None,
        options_service: OptionChainSource | None = None,
        earnings_sources: tuple[EarningsDetailsSource, ...] = (),
        settings: Settings | None = None,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.market_data = market_data
        self.options_service = options_service
        self.earnings_sources = earnings_sources
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def get_top_five(
        self,
        *,
        limit: int = _TIER1_LIMIT,
        user_id: UUID | None = None,
    ) -> CandidateBatch:
        del user_id
        today = self.today_provider()
        try:
            tier1_headers = await self.client.fetch_recent_filings(
                form_type="SC 13D",
                lookback_days=_calendar_days_for_trading_lookback(
                    today,
                    self.settings.activist_13d_lookback_tier1_days,
                ),
            )
        except Exception as exc:
            self.logger.warning("activist_13d_fetch_tier1_failed", error=str(exc))
            return self._build_batch(
                (),
                raw_row_count=0,
                report_status="failed",
                error=str(exc),
                warning_text=_candidate_count_warning(0, limit),
            )

        tier1 = await self._parse_headers(tier1_headers)
        selected: list[SelectedActivistFiling] = [
            SelectedActivistFiling(filing=filing, tier=1) for filing in tier1
        ]

        if len(selected) < limit:
            try:
                tier2_headers = await self.client.fetch_recent_filings(
                    form_type="SC 13D/A",
                    lookback_days=_calendar_days_for_trading_lookback(
                        today,
                        self.settings.activist_13d_lookback_tier2_days,
                    ),
                )
            except Exception as exc:
                self.logger.warning("activist_13d_fetch_tier2_failed", error=str(exc))
                tier2_headers = ()
            tier2 = await self._parse_headers(tier2_headers)
            existing = {item.filing.accession for item in selected}
            for filing in tier2:
                if filing.accession in existing:
                    continue
                if not filing.is_substantive:
                    continue
                selected.append(SelectedActivistFiling(filing=filing, tier=2))

        if len(selected) < limit:
            try:
                tier3_headers = await self.client.fetch_recent_filings(
                    form_type="SC 13D",
                    lookback_days=_calendar_days_for_trading_lookback(
                        today,
                        self.settings.activist_13d_lookback_tier3_days,
                    ),
                )
            except Exception as exc:
                self.logger.warning("activist_13d_fetch_tier3_failed", error=str(exc))
                tier3_headers = ()
            tier3 = await self._parse_headers(tier3_headers)
            existing = {item.filing.accession for item in selected}
            for filing in tier3:
                if filing.accession in existing:
                    continue
                selected.append(SelectedActivistFiling(filing=filing, tier=3))

        raw_count = len(selected)
        if not selected:
            return self._build_batch(
                (),
                raw_row_count=0,
                report_status="empty",
                warning_text=_candidate_count_warning(0, limit),
            )

        enrichment_results = await asyncio.gather(
            *(self._enrich(item, today=today) for item in selected),
            return_exceptions=True,
        )
        enriched: list[EnrichedActivistRow] = []
        for item, result in zip(selected, enrichment_results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "activist_13d_enrichment_failed",
                    accession=item.filing.accession,
                    error=str(result),
                )
                continue
            if result is None:
                continue
            enriched.append(result)

        ranked = _top_unique_by_ticker(enriched, limit=limit)
        final_rows = tuple(self._record_for(row) for row in ranked)

        if not final_rows:
            return self._build_batch(
                (),
                raw_row_count=raw_count,
                report_status="empty",
                warning_text=_candidate_count_warning(0, limit),
            )

        screener_status: ScreenerStatus = "success" if len(final_rows) >= limit else "partial"
        return self._build_batch(
            final_rows,
            raw_row_count=raw_count,
            report_status="success",
            screener_status=screener_status,
            warning_text=(
                _candidate_count_warning(len(final_rows), limit)
                if len(final_rows) < limit
                else None
            ),
        )

    async def _parse_headers(self, headers: tuple[FilingHeader, ...]) -> tuple[ActivistFiling, ...]:
        results = await asyncio.gather(
            *(self._parse_header(header) for header in headers),
            return_exceptions=True,
        )
        parsed: list[ActivistFiling] = []
        for header, result in zip(headers, results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "activist_13d_parse_failed",
                    accession=header.accession,
                    error=str(result),
                )
                continue
            if result is None:
                continue
            parsed.append(result)
        return tuple(parsed)

    async def _parse_header(self, header: FilingHeader) -> ActivistFiling | None:
        ticker = header.subject_ticker
        if ticker is None:
            ticker = await self.client.resolve_ticker(header.cik)
        if ticker is None:
            self.logger.info("activist_13d_ticker_unresolved", accession=header.accession)
            return None
        document = await self.client.fetch_filing_document(
            header.accession,
            header.primary_doc,
            cik=header.cik,
        )
        if not document:
            return None
        return parse_filing(header, document, ticker=ticker)

    async def _enrich(
        self,
        selected: SelectedActivistFiling,
        *,
        today: date,
    ) -> EnrichedActivistRow | None:
        filing = selected.filing
        if filing.ticker is None:
            return None
        snapshot = await self._fetch_snapshot(filing.ticker)
        if snapshot is None:
            return None
        if not self._passes_universe(snapshot):
            return None
        option_liquidity = await self._option_liquidity(filing.ticker, today=today)
        if option_liquidity is None:
            return None
        if selected.tier == 3 and not _passes_tier3_survivor_gate(snapshot):
            return None
        next_earnings = await self._next_earnings_date(filing.ticker, today=today)
        days_to_next_earnings = (
            None if next_earnings is None else (next_earnings - today).days
        )
        inputs = EventScoreInputs(
            stake_percent=filing.stake_percent,
            active_intent=filing.item4_active_intent,
            filing_date=filing.filing_date,
            today=today,
            filer_name=filing.filer_name,
            rel_vol=snapshot.volume_vs_average_20d,
            price_confirmation_pct=snapshot.stock_returns.five_day,
            option_liquidity_score=option_liquidity.score,
            days_to_next_earnings=days_to_next_earnings,
            gap_exhaustion_pct=snapshot.stock_returns.one_day,
            is_technology_sector=_is_technology_sector(snapshot.sector),
        )
        return EnrichedActivistRow(
            filing=filing,
            tier=selected.tier,
            snapshot=snapshot,
            event_score=compose_event_score(inputs),
            event_components=_event_score_components(inputs),
            option_liquidity=option_liquidity,
            days_to_next_earnings=days_to_next_earnings,
        )

    async def _fetch_snapshot(self, ticker: str) -> MarketSnapshot | None:
        if self.market_data is None:
            return None
        try:
            return await self.market_data.fetch(ticker, alpha_vantage_api_key=None)
        except Exception as exc:
            self.logger.warning("activist_13d_market_data_failed", ticker=ticker, error=str(exc))
            return None

    async def _option_liquidity(
        self,
        ticker: str,
        *,
        today: date,
    ) -> OptionLiquidityResult | None:
        if self.options_service is None:
            self.logger.warning(
                "activist_13d_options_unavailable",
                ticker=ticker,
                error="options service is not configured",
            )
            return None
        try:
            contracts = await self.options_service.get_chain(
                ticker,
                alpaca_api_key=None,
                alpaca_api_secret=None,
                strategy_permission="long",
                earnings_date=None,
                today=today,
            )
        except Exception as exc:
            self.logger.warning("activist_13d_options_failed", ticker=ticker, error=str(exc))
            return None
        return _score_option_liquidity(contracts, today=today)

    async def _next_earnings_date(self, ticker: str, *, today: date) -> date | None:
        if not self.earnings_sources:
            return None
        window = (today, today + timedelta(days=_EARNINGS_LOOKAHEAD_DAYS))
        results = await asyncio.gather(
            *[
                source.get_candidate_details(ticker, window=window)
                for source in self.earnings_sources
            ],
            return_exceptions=True,
        )
        dates: list[date] = []
        for result in results:
            if isinstance(result, BaseException):
                self.logger.warning(
                    "activist_13d_earnings_lookup_failed",
                    ticker=ticker,
                    error=str(result),
                )
                continue
            if result is None or result.earnings_date is None:
                continue
            if result.earnings_date >= today:
                dates.append(result.earnings_date)
        return min(dates) if dates else None

    def _passes_universe(self, snapshot: MarketSnapshot) -> bool:
        if snapshot.current_price is None or snapshot.market_cap is None:
            return False
        if snapshot.current_price < self.settings.activist_13d_min_price_usd:
            return False
        if snapshot.market_cap < self.settings.activist_13d_min_market_cap_usd:
            return False
        if snapshot.average_volume_20d is None:
            return False
        try:
            if snapshot.average_volume_20d < Decimal(self.settings.activist_13d_min_avg_vol):
                return False
        except (InvalidOperation, ValueError):
            return False
        return True

    def _record_for(self, row: EnrichedActivistRow) -> CandidateRecord:
        filing = row.filing
        snapshot = row.snapshot
        assert filing.ticker is not None
        assert snapshot is not None

        stake_text = (
            f"{filing.stake_percent:.1f}" if filing.stake_percent is not None else "unknown"
        )
        filer_text = filing.filer_name or "an activist filer"
        detail = (
            f"Fresh {filing.form_type} from {filer_text}, {stake_text}% stake, "
            f"{'active intent' if filing.item4_active_intent else 'amendment'}"
        )
        event_signal = StrategyEventSignal(
            score=int(row.event_score),
            is_supportive=True,
            detail=f"{detail}; event score {row.event_score.quantize(Decimal('0.01'))}/100 "
            f"({_event_component_summary(row.event_components)})",
        )
        validation_notes = (
            f"SC_13D_ACCESSION={filing.accession}",
            f"SC_13D_URL={filing.primary_doc_url}",
            f"Activist 13D filer: {filer_text}",
            f"Activist 13D event score: {row.event_score.quantize(Decimal('0.01'))}",
            f"Activist 13D tier: {row.tier}",
            "Activist 13D option liquidity score: "
            f"{row.option_liquidity.score.quantize(Decimal('0.01'))}",
            f"Activist 13D option liquidity quality: {row.option_liquidity.best_quality}",
            f"Activist 13D option usable contracts: {row.option_liquidity.usable_contract_count}",
            f"Activist 13D days to next earnings: {row.days_to_next_earnings}",
            *_event_component_notes(row.event_components),
        )
        return CandidateRecord(
            ticker=filing.ticker.upper(),
            company_name=snapshot.company_name or filing.filer_name,
            market_cap=snapshot.market_cap,
            earnings_date=None,
            current_price=snapshot.current_price,
            earnings_date_verified=False,
            screener_rank=None,
            daily_change_percent=snapshot.stock_returns.one_day,
            volume=snapshot.latest_volume,
            sector=snapshot.sector,
            sources=("sec_edgar",),
            validation_notes=validation_notes,
            strategy_source=ACTIVIST_13D_STRATEGY_SOURCE,
            event_signal=event_signal,
        )

    def _build_batch(
        self,
        rows: tuple[CandidateRecord, ...],
        *,
        raw_row_count: int,
        report_status: StrategyRunStatus,
        screener_status: ScreenerStatus | None = None,
        error: str | None = None,
        warning_text: str | None = None,
    ) -> CandidateBatch:
        resolved_status: ScreenerStatus = (
            screener_status if screener_status is not None else ("success" if rows else "empty")
        )
        return CandidateBatch(
            candidates=rows,
            screener_status=resolved_status,
            fallback_used=False,
            warning_text=warning_text,
            strategy_reports=(
                build_strategy_report(
                    ACTIVIST_13D_STRATEGY_SOURCE,
                    status=report_status,
                    raw_row_count=raw_row_count,
                    candidate_count=len(rows),
                    finviz_candidate_count=0,
                    backup_candidate_count=len(rows),
                    error=error,
                    warning_text=warning_text,
                ),
            ),
        )


def _is_technology_sector(sector: str | None) -> bool:
    if sector is None:
        return False
    lowered = sector.lower()
    return any(term in lowered for term in _TECH_SECTOR_TERMS)


def _calendar_days_for_trading_lookback(today: date, trading_days: int) -> int:
    if trading_days <= 0:
        return 0
    start = today - timedelta(days=max(trading_days * 3, trading_days + 7))
    sessions = tuple(
        session.session_date
        for session in market_sessions_between(start, today)
        if session.session_date <= today
    )
    if len(sessions) >= trading_days:
        start_date = sessions[-trading_days]
    else:
        start_date = today - timedelta(days=trading_days)
    return max((today - start_date).days, trading_days)


def _score_option_liquidity(
    contracts: tuple[OptionContractInput, ...],
    *,
    today: date,
) -> OptionLiquidityResult | None:
    usable: list[tuple[int, Decimal | None]] = []
    for contract in contracts:
        if contract.option_type != "call" or contract.position_side != "long":
            continue
        if contract.expiry <= today or contract.expiry > today + timedelta(days=45):
            continue
        if contract.is_stale or not contract.is_tradable:
            continue
        if option_premium(contract) is None:
            continue
        spread = spread_percent(contract)
        if spread is None or spread > _MAX_UNIVERSE_OPTION_SPREAD:
            continue
        if (contract.open_interest or 0) == 0 and (contract.volume or 0) == 0:
            continue
        usable.append((liquidity_quality(contract), spread))

    if not usable:
        return None

    best_quality, best_spread = max(usable, key=lambda item: item[0])
    if best_quality < _MIN_UNIVERSE_OPTION_LIQUIDITY:
        return None
    score = min(Decimal("5"), Decimal(best_quality) / Decimal("20"))
    return OptionLiquidityResult(
        score=score,
        best_quality=best_quality,
        best_spread=best_spread,
        usable_contract_count=len(usable),
    )


def _passes_tier3_survivor_gate(snapshot: MarketSnapshot) -> bool:
    one_day = snapshot.stock_returns.one_day
    five_day = snapshot.stock_returns.five_day
    if one_day is not None and one_day > _TIER3_MAX_ONE_DAY_MOVE:
        return False
    if five_day is not None and five_day > _TIER3_MAX_FIVE_DAY_MOVE:
        return False
    return True


def _top_unique_by_ticker(
    rows: list[EnrichedActivistRow],
    *,
    limit: int,
) -> list[EnrichedActivistRow]:
    ranked: list[EnrichedActivistRow] = []
    seen: set[str] = set()
    for row in sorted(rows, key=lambda item: item.event_score, reverse=True):
        ticker = (row.filing.ticker or "").upper()
        if ticker in seen:
            continue
        seen.add(ticker)
        ranked.append(row)
        if len(ranked) >= limit:
            break
    return ranked


def _event_score_components(
    inputs: EventScoreInputs,
) -> tuple[tuple[str, Decimal], ...]:
    return (
        ("event_recency_score", sec_scoring.recency_score(inputs.filing_date, inputs.today)),
        ("stake_percent_score", sec_scoring.stake_size_score(inputs.stake_percent)),
        ("activist_intent_score", sec_scoring.active_intent_score(inputs.active_intent)),
        ("filing_quality_score", sec_scoring.filer_quality_score(inputs.filer_name)),
        ("relative_volume_score", sec_scoring.rel_vol_score(inputs.rel_vol)),
        (
            "price_confirmation_score",
            sec_scoring.price_confirmation_score(inputs.price_confirmation_pct),
        ),
        (
            "option_liquidity_score",
            sec_scoring.option_liquidity_score(inputs.option_liquidity_score),
        ),
        (
            "earnings_collision_penalty",
            sec_scoring.earnings_collision_penalty(inputs.days_to_next_earnings),
        ),
        (
            "gap_exhaustion_penalty",
            sec_scoring.gap_exhaustion_penalty(inputs.gap_exhaustion_pct),
        ),
        (
            "tech_concentration_penalty",
            sec_scoring.tech_concentration_penalty(inputs.is_technology_sector),
        ),
    )


def _event_component_summary(components: tuple[tuple[str, Decimal], ...]) -> str:
    wanted = {
        "event_recency_score",
        "stake_percent_score",
        "activist_intent_score",
        "filing_quality_score",
        "option_liquidity_score",
        "earnings_collision_penalty",
    }
    return ", ".join(
        f"{name}={value.quantize(Decimal('0.01'))}"
        for name, value in components
        if name in wanted
    )


def _event_component_notes(
    components: tuple[tuple[str, Decimal], ...],
) -> tuple[str, ...]:
    return tuple(
        f"Activist 13D {name}: {value.quantize(Decimal('0.01'))}"
        for name, value in components
    )


def _candidate_count_warning(count: int, limit: int) -> str:
    if count == 0:
        return (
            "⚠️ Strategy E found no qualified activist 13D candidates this scan after "
            "SEC, market, earnings, and options-liquidity checks."
        )
    return (
        f"⚠️ Strategy E found only {count} of {limit} qualified activist 13D candidates "
        "this scan; no lower-quality symbols were backfilled."
    )


def get_activist_13d_candidate_service(
    *,
    client: SECFilingsClient | None = None,
    market_data: MarketDataSource | None = None,
) -> Activist13DCandidateService:
    from app.services.earnings_calendar.finnhub_source import FinnhubEarningsSource
    from app.services.earnings_calendar.yfinance_source import YFinanceEarningsSource
    from app.services.market_data.service import get_market_data_service
    from app.services.options import get_options_service
    from app.services.run_lock import get_redis_client
    from app.services.sec.filings_client import CacheClient

    settings = get_settings()
    resolved_market_data = market_data or get_market_data_service()
    resolved_client = client or SECFilingsClient(
        user_agent=settings.activist_13d_user_agent,
        throttle_rps=settings.activist_13d_throttle_rps,
        cache=cast(CacheClient, get_redis_client()),
        cache_ttl_seconds=settings.activist_13d_filing_cache_ttl_seconds,
    )
    return Activist13DCandidateService(
        resolved_client,
        market_data=resolved_market_data,
        options_service=get_options_service(),
        earnings_sources=(
            YFinanceEarningsSource(),
            FinnhubEarningsSource(api_key=settings.finnhub_api_key),
        ),
        settings=settings,
    )
