from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any
from uuid import UUID

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.pipeline.types import PipelineCandidate, PipelineOutcome
from app.scoring.types import ContractScoreResult

ZERO = Decimal("0")


@dataclass(slots=True, frozen=True)
class RunArtifacts:
    run_summary: dict[str, Any]
    candidate_cards: list[dict[str, Any]]
    option_contracts: list[dict[str, Any]]
    recommendation_card: dict[str, Any]
    telegram_message: str


class LoggingService:
    def __init__(
        self,
        *,
        archive_root: Path | str | None = None,
        settings: Settings | None = None,
        logger: Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if archive_root is None and self.settings.app_env != "test":
            archive_root = Path("var/runs")
        self.archive_root = None if archive_root is None else Path(archive_root)
        self.logger = logger or get_logger(__name__)

    def capture_run(
        self,
        *,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
        recommendation: Recommendation | None,
        telegram_message: str,
    ) -> RunArtifacts:
        artifacts = self.build_run_artifacts(
            run=run,
            user=user,
            outcome=outcome,
            recommendation=recommendation,
            telegram_message=telegram_message,
        )
        run.run_summary_json = artifacts.run_summary
        run.candidate_cards_json = artifacts.candidate_cards
        run.option_contracts_json = artifacts.option_contracts
        run.recommendation_card_json = artifacts.recommendation_card
        run.telegram_message_text = artifacts.telegram_message
        self._archive(run.id, artifacts)
        self.logger.info(
            "run_artifacts_captured",
            run_id=str(run.id),
            candidate_count=len(artifacts.candidate_cards),
            contract_count=len(artifacts.option_contracts),
        )
        return artifacts

    def build_run_artifacts(
        self,
        *,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
        recommendation: Recommendation | None,
        telegram_message: str,
    ) -> RunArtifacts:
        ranked_candidates = _rank_candidates(outcome.candidates)
        selected = outcome.selected
        selected_ticker = selected.record.ticker if selected is not None else None
        selected_contract_score = outcome.final_contract
        top_candidate = ranked_candidates[0] if ranked_candidates else None

        candidate_cards = [
            _candidate_card(
                candidate=item,
                selected_ticker=selected_ticker,
                top_candidate_ticker=None if top_candidate is None else top_candidate.record.ticker,
                final_action=outcome.decision.action,
                final_reasoning=outcome.decision.reasoning,
            )
            for item in ranked_candidates
        ]
        option_contracts = [
            _contract_card(candidate=item, contract=contract)
            for item in ranked_candidates
            for contract in item.evaluation.considered_contracts
        ]
        rejected_alternatives = [
            {
                "ticker": card["ticker"],
                "best_strategy": card["best_strategy"],
                "final_opportunity_score": card["final_opportunity_score"],
                "reason": card["reason_selected_or_rejected"],
            }
            for card in candidate_cards
            if card["ticker"] != selected_ticker
        ][:3]
        selected_contract = (
            None
            if selected_contract_score is None
            else _selected_contract_fields(selected_contract_score)
        )
        confidence_score = (
            recommendation.confidence_score
            if recommendation is not None
            else outcome.decision.final_score
            if outcome.decision.final_score is not None
            else 0 if top_candidate is None else top_candidate.evaluation.final_score
        )
        data_confidence = (
            selected.evaluation.confidence.score
            if selected is not None
            else 0 if top_candidate is None else top_candidate.evaluation.confidence.score
        )
        recommendation_card = {
            "card_id": str(recommendation.id) if recommendation is not None else str(run.id),
            "user_id": str(user.id),
            "run_id": str(run.id),
            "timestamp": _dt(
                run.finished_at or recommendation_timestamp(recommendation) or run.started_at
            ),
            "trigger_type": run.trigger_type,
            "selected_ticker": selected_ticker,
            "selected_company": None if selected is None else selected.context.company_name,
            "selected_strategy": _selected_strategy(
                selected_contract_score,
                outcome.decision.action,
            ),
            "selected_contract": selected_contract,
            "selected_contract_rationale": (
                None
                if outcome.decision.chosen_contract is None
                else outcome.decision.chosen_contract.rationale
            ),
            "suggested_entry": (
                None if recommendation is None else _decimal(recommendation.suggested_entry)
            ),
            "suggested_quantity": (
                0 if recommendation is None else recommendation.suggested_quantity
            ),
            "confidence_score": confidence_score,
            "risk_profile": user.risk_profile,
            "account_size_snapshot": _decimal(user.account_size),
            "account_risk_percent": (
                None
                if recommendation is None
                else _decimal(recommendation.account_risk_percent)
            ),
            "risk_level": None if recommendation is None else recommendation.risk_level,
            "estimated_max_loss": (
                None if recommendation is None else recommendation.estimated_max_loss
            ),
            "earnings_date": None if selected is None else _date(selected.context.earnings_date),
            "earnings_timing": "unknown" if selected is None else selected.context.earnings_timing,
            "key_evidence": list(outcome.decision.key_evidence),
            "key_concerns": list(outcome.decision.key_concerns),
            "rejected_alternatives": rejected_alternatives,
            "data_confidence": data_confidence,
            "decision_engine": outcome.decision_trace.engine,
            "decision_engine_notes": list(outcome.decision_trace.notes),
            "model_used_heavy": _heavy_model_used(outcome),
            "model_used_light": _light_model_used(outcome, self.settings),
            "decision_action": outcome.decision.action,
            "decision_reasoning": outcome.decision.reasoning,
            "watchlist_tickers": list(outcome.decision.watchlist_tickers),
            "warning_text": outcome.batch.warning_text,
            "telegram_message": telegram_message,
            "telegram_message_id": (
                None if recommendation is None else recommendation.telegram_message_id
            ),
            "created_at": _dt(
                recommendation_timestamp(recommendation) or run.finished_at or run.started_at
            ),
        }
        run_summary = {
            "run_id": str(run.id),
            "user_id": str(user.id),
            "trigger_type": run.trigger_type,
            "status": run.status,
            "started_at": _dt(run.started_at),
            "finished_at": _dt(run.finished_at),
            "screener_status": run.screener_status,
            "fallback_used": outcome.batch.fallback_used,
            "warning_text": outcome.batch.warning_text,
            "screener_tickers": [record.ticker for record in outcome.batch.candidates],
            "selected_candidate_count": len(outcome.candidates),
            "final_recommendation_id": None if recommendation is None else str(recommendation.id),
            "selected_ticker": selected_ticker,
            "decision_action": outcome.decision.action,
            "decision_engine": outcome.decision_trace.engine,
            "decision_engine_notes": list(outcome.decision_trace.notes),
            "model_used_heavy": _heavy_model_used(outcome),
            "model_used_light": _light_model_used(outcome, self.settings),
            "contracts_considered_count": len(option_contracts),
            "rejected_contract_count": sum(
                1 for contract in option_contracts if not contract["passed_hard_filters"]
            ),
            "error_message": run.error_message,
        }
        return RunArtifacts(
            run_summary=run_summary,
            candidate_cards=candidate_cards,
            option_contracts=option_contracts,
            recommendation_card=recommendation_card,
            telegram_message=telegram_message,
        )

    def _archive(self, run_id: UUID, artifacts: RunArtifacts) -> None:
        if self.archive_root is None:
            return
        run_dir = self.archive_root / str(run_id)
        try:
            run_dir.mkdir(parents=True, exist_ok=True)
            _write_json(run_dir / "run_summary.json", artifacts.run_summary)
            _write_json(run_dir / "candidate_cards.json", artifacts.candidate_cards)
            _write_json(run_dir / "option_contracts.json", artifacts.option_contracts)
            _write_json(run_dir / "recommendation_card.json", artifacts.recommendation_card)
            (run_dir / "telegram_message.txt").write_text(
                artifacts.telegram_message,
                encoding="utf-8",
            )
        except OSError as exc:
            self.logger.warning("run_artifact_archive_failed", run_id=str(run_id), error=str(exc))


@lru_cache(maxsize=1)
def get_logging_service() -> LoggingService:
    return LoggingService()


def recommendation_timestamp(recommendation: Recommendation | None) -> datetime | None:
    if recommendation is None:
        return None
    return recommendation.created_at


def _rank_candidates(candidates: tuple[PipelineCandidate, ...]) -> list[PipelineCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.record.market_cap or ZERO,
        ),
        reverse=True,
    )


def _candidate_card(
    *,
    candidate: PipelineCandidate,
    selected_ticker: str | None,
    top_candidate_ticker: str | None,
    final_action: str,
    final_reasoning: str,
) -> dict[str, Any]:
    best_contract = _best_contract(candidate)
    return {
        "ticker": candidate.record.ticker,
        "screener_rank": candidate.record.screener_rank,
        "company_name": candidate.context.company_name,
        "market_cap": _decimal(
            candidate.record.market_cap or candidate.context.market_snapshot.market_cap
        ),
        "earnings_date": _date(candidate.context.earnings_date),
        "earnings_date_verified": candidate.context.verified_earnings_date,
        "direction_classification": candidate.evaluation.direction.classification,
        "candidate_direction_score": candidate.evaluation.direction.score,
        "best_contract_score": None if best_contract is None else best_contract.score,
        "final_opportunity_score": candidate.evaluation.final_score,
        "best_strategy": None if best_contract is None else best_contract.strategy,
        "best_contract": (
            None if best_contract is None else _selected_contract_fields(best_contract)
        ),
        "reason_selected_or_rejected": _reason_selected_or_rejected(
            candidate=candidate,
            selected_ticker=selected_ticker,
            top_candidate_ticker=top_candidate_ticker,
            final_action=final_action,
            final_reasoning=final_reasoning,
        ),
        "data_sources_used": _data_sources(candidate),
        "missing_data_fields": _missing_data_fields(candidate),
        "validation_notes": list(candidate.record.validation_notes),
    }


def _reason_selected_or_rejected(
    *,
    candidate: PipelineCandidate,
    selected_ticker: str | None,
    top_candidate_ticker: str | None,
    final_action: str,
    final_reasoning: str,
) -> str:
    reason_tail = next(
        iter(candidate.evaluation.reasons),
        "No additional scoring note was stored.",
    )
    if candidate.record.ticker == selected_ticker:
        if final_action == "watchlist":
            return f"Selected as the top watchlist setup. {final_reasoning}"
        return f"Selected for the final recommendation. {final_reasoning}"
    if candidate.record.ticker == top_candidate_ticker and final_action == "no_trade":
        return f"Strongest setup of the run, but it still failed the final trade bar. {reason_tail}"
    if candidate.evaluation.chosen_contract is None:
        return f"Rejected because no viable contract cleared the hard filters. {reason_tail}"
    if candidate.evaluation.action == "watchlist":
        return f"Rejected in favor of a stronger setup after ranking. {reason_tail}"
    return f"Rejected because the final opportunity score stayed too weak. {reason_tail}"


def _contract_card(
    *,
    candidate: PipelineCandidate,
    contract: ContractScoreResult,
) -> dict[str, Any]:
    return {
        "ticker": contract.contract.ticker,
        "candidate_ticker": candidate.record.ticker,
        "option_type": contract.contract.option_type,
        "position_side": contract.contract.position_side,
        "strike": _decimal(contract.contract.strike),
        "expiry": _date(contract.contract.expiry),
        "bid": _decimal(contract.contract.bid),
        "ask": _decimal(contract.contract.ask),
        "mid": _decimal(contract.contract.mid),
        "volume": contract.contract.volume,
        "open_interest": contract.contract.open_interest,
        "implied_volatility": _decimal(contract.contract.implied_volatility),
        "delta": _decimal(contract.contract.delta),
        "breakeven": _decimal(contract.breakeven),
        "spread_percent": _decimal(contract_spread_percent(contract)),
        "liquidity_score": contract.liquidity_score,
        "contract_score": contract.score,
        "passed_hard_filters": not contract.vetoes,
        "rejection_reason": (
            None if not contract.vetoes else "; ".join(v.reason for v in contract.vetoes)
        ),
    }


def contract_spread_percent(contract: ContractScoreResult) -> Decimal | None:
    raw = contract.contract.ask
    if raw is None or contract.contract.bid is None:
        return None
    mid = contract.contract.mid
    if mid is None or mid <= ZERO:
        return None
    return ((raw - contract.contract.bid) / mid) * Decimal("100")


def _best_contract(candidate: PipelineCandidate) -> ContractScoreResult | None:
    if candidate.evaluation.chosen_contract is not None:
        return candidate.evaluation.chosen_contract
    if candidate.evaluation.considered_contracts:
        return candidate.evaluation.considered_contracts[0]
    return None


def _selected_contract_fields(contract: ContractScoreResult) -> dict[str, Any]:
    return {
        "strike": _decimal(contract.contract.strike),
        "expiry": _date(contract.contract.expiry),
        "option_type": contract.contract.option_type,
        "position_side": contract.contract.position_side,
    }


def _selected_strategy(contract: ContractScoreResult | None, final_action: str) -> str:
    if contract is None or final_action == "no_trade":
        return "No trade"
    return _title_strategy(contract.strategy)


def _title_strategy(strategy: str) -> str:
    return strategy.replace("_", " ").capitalize()


def _data_sources(candidate: PipelineCandidate) -> list[str]:
    ordered: list[str] = []
    for value in candidate.record.sources:
        if value not in ordered:
            ordered.append(value)
    for value in candidate.context.market_snapshot.sources:
        if value not in ordered:
            ordered.append(value)
    for item in candidate.news_bundle.search_results:
        if item.source and item.source not in ordered:
            ordered.append(item.source)
    for item in candidate.news_bundle.articles:
        if item.source and item.source not in ordered:
            ordered.append(item.source)
    for contract in candidate.context.option_chain:
        if contract.source and contract.source not in ordered:
            ordered.append(contract.source)
    return ordered


def _missing_data_fields(candidate: PipelineCandidate) -> list[str]:
    missing: list[str] = []
    snapshot = candidate.context.market_snapshot
    if not candidate.context.identity_verified:
        missing.append("company_name")
    if not candidate.context.verified_earnings_date:
        missing.append("earnings_date")
    if candidate.record.market_cap is None and snapshot.market_cap is None:
        missing.append("market_cap")
    if candidate.record.current_price is None and snapshot.current_price is None:
        missing.append("current_price")
    if candidate.context.earnings_timing == "unknown":
        missing.append("earnings_timing")
    if not candidate.context.option_chain:
        missing.append("option_chain")
    if not candidate.news_bundle.articles:
        missing.append("news_articles")
    return missing


def _heavy_model_used(outcome: PipelineOutcome) -> str | None:
    return outcome.decision_trace.heavy_model_used


def _light_model_used(outcome: PipelineOutcome, settings: Settings) -> str | None:
    for candidate in outcome.candidates:
        bundle = candidate.news_bundle
        if bundle.used_llm_summary and bundle.articles:
            return settings.lightweight_model
    return None


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _dt(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _write_json(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
