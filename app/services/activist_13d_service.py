from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol, cast
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
from app.services.market_data.types import MarketSnapshot
from app.services.sec.activist_13d_parser import ActivistFiling, parse_filing
from app.services.sec.filings_client import FilingHeader, SECFilingsClient
from app.services.sec.scoring import EventScoreInputs, compose_event_score
from app.services.strategy_catalog import build_strategy_report

ACTIVIST_13D_STRATEGY_SOURCE: StrategySource = "activist_13d_followthrough"
_TIER1_LIMIT = 5
_ZERO = Decimal("0")
_TECH_SECTOR_TERMS = ("technology", "communication services")


class MarketDataSource(Protocol):
    async def fetch(
        self,
        ticker: str,
        *,
        alpha_vantage_api_key: str | None = None,
        refresh: bool = False,
    ) -> MarketSnapshot: ...


@dataclass(slots=True, frozen=True)
class EnrichedActivistRow:
    filing: ActivistFiling
    snapshot: MarketSnapshot | None
    event_score: Decimal


class Activist13DCandidateService:
    slug: StrategySource = ACTIVIST_13D_STRATEGY_SOURCE

    def __init__(
        self,
        client: SECFilingsClient,
        *,
        market_data: MarketDataSource | None = None,
        settings: Settings | None = None,
        today_provider: Callable[[], date] | None = None,
        logger: Any | None = None,
    ) -> None:
        self.client = client
        self.settings = settings or get_settings()
        self.market_data = market_data
        self.today_provider = today_provider or date.today
        self.logger = logger or get_logger(__name__)

    async def get_top_five(
        self,
        *,
        limit: int = _TIER1_LIMIT,
        user_id: UUID | None = None,
    ) -> CandidateBatch:
        del user_id
        try:
            tier1_headers = await self.client.fetch_recent_filings(
                form_type="SC 13D",
                lookback_days=self.settings.activist_13d_lookback_tier1_days,
            )
        except Exception as exc:
            self.logger.warning("activist_13d_fetch_tier1_failed", error=str(exc))
            return self._build_batch((), raw_row_count=0, report_status="failed", error=str(exc))

        tier1 = await self._parse_headers(tier1_headers)
        all_filings: list[ActivistFiling] = list(tier1)

        if len(all_filings) < limit:
            try:
                tier2_headers = await self.client.fetch_recent_filings(
                    form_type="SC 13D/A",
                    lookback_days=self.settings.activist_13d_lookback_tier2_days,
                )
            except Exception as exc:
                self.logger.warning("activist_13d_fetch_tier2_failed", error=str(exc))
                tier2_headers = ()
            tier2 = await self._parse_headers(tier2_headers)
            existing = {filing.accession for filing in all_filings}
            for filing in tier2:
                if filing.accession in existing:
                    continue
                if not filing.is_substantive:
                    continue
                all_filings.append(filing)

        if len(all_filings) < limit:
            try:
                tier3_headers = await self.client.fetch_recent_filings(
                    form_type="SC 13D",
                    lookback_days=self.settings.activist_13d_lookback_tier3_days,
                )
            except Exception as exc:
                self.logger.warning("activist_13d_fetch_tier3_failed", error=str(exc))
                tier3_headers = ()
            tier3 = await self._parse_headers(tier3_headers)
            existing = {filing.accession for filing in all_filings}
            for filing in tier3:
                if filing.accession in existing:
                    continue
                all_filings.append(filing)

        raw_count = len(all_filings)
        if not all_filings:
            return self._build_batch((), raw_row_count=0, report_status="empty")

        enrichment_results = await asyncio.gather(
            *(self._enrich(filing) for filing in all_filings),
            return_exceptions=True,
        )
        enriched: list[EnrichedActivistRow] = []
        for filing, result in zip(all_filings, enrichment_results, strict=True):
            if isinstance(result, BaseException):
                self.logger.warning(
                    "activist_13d_enrichment_failed",
                    accession=filing.accession,
                    error=str(result),
                )
                continue
            if result is None:
                continue
            enriched.append(result)

        ranked = sorted(enriched, key=lambda row: row.event_score, reverse=True)[:limit]
        final_rows = tuple(self._record_for(row) for row in ranked)

        if not final_rows:
            return self._build_batch((), raw_row_count=raw_count, report_status="empty")

        screener_status: ScreenerStatus = "success" if len(final_rows) >= limit else "partial"
        return self._build_batch(
            final_rows,
            raw_row_count=raw_count,
            report_status="success",
            screener_status=screener_status,
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

    async def _enrich(self, filing: ActivistFiling) -> EnrichedActivistRow | None:
        if filing.ticker is None:
            return None
        snapshot = await self._fetch_snapshot(filing.ticker)
        if snapshot is None:
            return None
        if not self._passes_universe(snapshot):
            return None
        # TODO(v2): option_liquidity_score should be derived from the real options
        # chain (OI, spread, volume bands) once it is wired through the activist arm;
        # days_to_next_earnings should come from the earnings calendar so the
        # earnings_collision_penalty fires within 5 days of a print.
        inputs = EventScoreInputs(
            stake_percent=filing.stake_percent,
            active_intent=filing.item4_active_intent,
            filing_date=filing.filing_date,
            today=self.today_provider(),
            filer_name=filing.filer_name,
            rel_vol=snapshot.volume_vs_average_20d,
            price_confirmation_pct=snapshot.stock_returns.five_day,
            option_liquidity_score=Decimal("3"),
            days_to_next_earnings=None,
            gap_exhaustion_pct=snapshot.stock_returns.one_day,
            is_technology_sector=_is_technology_sector(snapshot.sector),
        )
        return EnrichedActivistRow(
            filing=filing,
            snapshot=snapshot,
            event_score=compose_event_score(inputs),
        )

    async def _fetch_snapshot(self, ticker: str) -> MarketSnapshot | None:
        if self.market_data is None:
            return None
        try:
            return await self.market_data.fetch(ticker, alpha_vantage_api_key=None)
        except Exception as exc:
            self.logger.warning("activist_13d_market_data_failed", ticker=ticker, error=str(exc))
            return None

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
            detail=detail,
        )
        validation_notes = (
            f"SC_13D_ACCESSION={filing.accession}",
            f"SC_13D_URL={filing.primary_doc_url}",
            f"Activist 13D filer: {filer_text}",
            f"Activist 13D event score: {row.event_score.quantize(Decimal('0.01'))}",
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
    ) -> CandidateBatch:
        resolved_status: ScreenerStatus = (
            screener_status if screener_status is not None else ("success" if rows else "empty")
        )
        return CandidateBatch(
            candidates=rows,
            screener_status=resolved_status,
            fallback_used=False,
            strategy_reports=(
                build_strategy_report(
                    ACTIVIST_13D_STRATEGY_SOURCE,
                    status=report_status,
                    raw_row_count=raw_row_count,
                    candidate_count=len(rows),
                    finviz_candidate_count=0,
                    backup_candidate_count=len(rows),
                    error=error,
                ),
            ),
        )


def _is_technology_sector(sector: str | None) -> bool:
    if sector is None:
        return False
    lowered = sector.lower()
    return any(term in lowered for term in _TECH_SECTOR_TERMS)


def get_activist_13d_candidate_service(
    *,
    client: SECFilingsClient | None = None,
    market_data: MarketDataSource | None = None,
) -> Activist13DCandidateService:
    from app.services.market_data.service import get_market_data_service
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
        settings=settings,
    )
