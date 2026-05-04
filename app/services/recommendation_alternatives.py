from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.db.repositories.candidate_repo import CandidateRepository
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.pipeline.orchestrator import PipelineOrchestrator, get_pipeline_orchestrator
from app.pipeline.types import PipelineOutcome
from app.services.candidate_models import CandidateBatch, CandidateRecord


@dataclass(slots=True, frozen=True)
class AlternativeRecommendationResult:
    status: Literal["recommendation", "no_trade", "exhausted"]
    recommendation: Recommendation | None = None
    outcome: PipelineOutcome | None = None
    run: WorkflowRun | None = None
    reused_existing: bool = False


class AlternativeRecommendationService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        orchestrator: PipelineOrchestrator | None = None,
    ) -> None:
        self.session = session
        self.orchestrator = orchestrator or get_pipeline_orchestrator()
        self.recommendations = RecommendationRepository(session)
        self.runs = WorkflowRunRepository(session)
        self.candidates = CandidateRepository(session)

    async def get_next_alternative(
        self,
        *,
        cursor: Recommendation,
        user: User,
    ) -> AlternativeRecommendationResult:
        existing = await self.recommendations.get_child_for_parent(cursor.id)
        run = await self.runs.get(cursor.run_id)
        if run is None:
            raise LookupError(f"Workflow run {cursor.run_id} was not found")

        if existing is not None:
            return AlternativeRecommendationResult(
                status="recommendation",
                recommendation=existing,
                run=run,
                reused_existing=True,
            )

        excluded_tickers = await self._lineage_tickers(cursor)
        batch = await self._remaining_candidate_batch(run, excluded_tickers)
        if not batch.candidates:
            return AlternativeRecommendationResult(status="exhausted", run=run)

        outcome = await self.orchestrator.evaluate_batch(batch, user)
        recommendation = await self.orchestrator.persist_recommendation(
            self.session,
            run,
            user,
            outcome,
            parent_recommendation_id=cursor.id,
            update_run=False,
        )
        if recommendation is None:
            return AlternativeRecommendationResult(
                status="no_trade",
                outcome=outcome,
                run=run,
            )
        return AlternativeRecommendationResult(
            status="recommendation",
            recommendation=recommendation,
            outcome=outcome,
            run=run,
        )

    async def _lineage_tickers(self, cursor: Recommendation) -> set[str]:
        tickers: set[str] = set()
        seen_ids = set()
        current: Recommendation | None = cursor
        while current is not None and current.id not in seen_ids:
            seen_ids.add(current.id)
            tickers.add(current.ticker)
            if current.parent_recommendation_id is None:
                break
            current = await self.recommendations.get(current.parent_recommendation_id)
        return tickers

    async def _remaining_candidate_batch(
        self,
        run: WorkflowRun,
        excluded_tickers: set[str],
    ) -> CandidateBatch:
        rows = await self.candidates.list_for_run(run.id)
        cards = _candidate_cards_by_ticker(run.candidate_cards_json)
        order = _ticker_order(run, cards)

        records: list[CandidateRecord] = []
        for row in rows:
            if row.ticker in excluded_tickers:
                continue
            card = cards.get(row.ticker)
            records.append(_candidate_record_from_stored(row, card))

        records.sort(
            key=lambda record: (
                _sort_position(record.ticker, cards, order),
                record.ticker,
            )
        )
        return CandidateBatch(
            candidates=tuple(records),
            screener_status=_run_summary_value(run.run_summary_json, "screener_status", run.screener_status)
            or "success",
            fallback_used=bool(_run_summary_value(run.run_summary_json, "fallback_used", False)),
            warning_text=_run_summary_value(run.run_summary_json, "warning_text", None),
        )


def _candidate_record_from_stored(row, card: dict[str, Any] | None) -> CandidateRecord:
    company_name = row.company_name if row.company_name else _card_str(card, "company_name")
    earnings_date = row.earnings_date if row.earnings_date is not None else _card_date(card, "earnings_date")
    return CandidateRecord(
        ticker=row.ticker,
        company_name=company_name,
        market_cap=row.market_cap,
        earnings_date=earnings_date,
        current_price=row.current_price,
        earnings_date_verified=_card_bool(card, "earnings_date_verified", True),
        screener_rank=_card_int(card, "screener_rank"),
        sources=_card_tuple(card, "data_sources_used", default=("stored_run",)),
        validation_notes=_card_tuple(card, "validation_notes", default=()),
    )


def _candidate_cards_by_ticker(
    candidate_cards_json: list[dict[str, Any]] | None,
) -> dict[str, dict[str, Any]]:
    cards = candidate_cards_json or []
    return {
        str(card["ticker"]): card
        for card in cards
        if isinstance(card, dict) and card.get("ticker")
    }


def _ticker_order(
    run: WorkflowRun,
    cards: dict[str, dict[str, Any]],
) -> dict[str, int]:
    order: dict[str, int] = {}
    screener_tickers = _run_summary_value(run.run_summary_json, "screener_tickers", ())
    if isinstance(screener_tickers, list):
        for index, ticker in enumerate(screener_tickers):
            order[str(ticker)] = index
    for ticker, card in cards.items():
        rank = _card_int(card, "screener_rank")
        if rank is None:
            continue
        order[ticker] = min(order.get(ticker, rank - 1), rank - 1)
    return order


def _sort_position(
    ticker: str,
    cards: dict[str, dict[str, Any]],
    order: dict[str, int],
) -> int:
    if ticker in order:
        return order[ticker]
    rank = _card_int(cards.get(ticker), "screener_rank")
    if rank is not None:
        return rank - 1
    score = _card_int(cards.get(ticker), "final_opportunity_score")
    if score is not None:
        return 10_000 - score
    return 1_000_000


def _card_str(card: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(card, dict):
        return None
    value = card.get(key)
    return None if value is None else str(value)


def _card_bool(card: dict[str, Any] | None, key: str, default: bool) -> bool:
    if not isinstance(card, dict):
        return default
    value = card.get(key)
    return default if value is None else bool(value)


def _card_int(card: dict[str, Any] | None, key: str) -> int | None:
    if not isinstance(card, dict):
        return None
    value = card.get(key)
    if value is None:
        return None
    return int(value)


def _card_tuple(
    card: dict[str, Any] | None,
    key: str,
    *,
    default: tuple[str, ...],
) -> tuple[str, ...]:
    if not isinstance(card, dict):
        return default
    value = card.get(key)
    if not isinstance(value, list):
        return default
    return tuple(str(item) for item in value)


def _card_date(card: dict[str, Any] | None, key: str) -> date | None:
    if not isinstance(card, dict):
        return None
    value = card.get(key)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _run_summary_value(summary: dict[str, Any] | None, key: str, default: Any) -> Any:
    if not isinstance(summary, dict):
        return default
    return summary.get(key, default)
