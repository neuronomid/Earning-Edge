from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.pipeline.types import PipelineCandidate, PipelineOutcome
from app.scoring.types import ContractScoreResult, option_mid
from app.services.candidate_models import CandidateBatch


@dataclass(slots=True, frozen=True)
class QAArtifactMetadata:
    run_id: UUID
    lane: str
    reference_dt_utc: datetime
    reference_trading_date: date | None
    qa_user_id: str
    qa_user_chat_id: str


@dataclass(slots=True, frozen=True)
class QAInputSnapshot:
    account_size: Decimal
    risk_profile: str
    timezone_label: str
    timezone_iana: str
    broker: str
    strategy_permission: str
    max_contracts: int
    openrouter_key_present: bool
    alpha_vantage_key_present: bool
    alpaca_key_present: bool
    alpaca_secret_present: bool


class QAExportService:
    def __init__(self, *, results_root: Path | str) -> None:
        self.results_root = Path(results_root)

    def export_run(
        self,
        *,
        run: WorkflowRun,
        user: User,
        outcome: PipelineOutcome,
        recommendation: Recommendation | None,
        decision_candidates: list[PipelineCandidate],
        metadata: QAArtifactMetadata,
        inputs: QAInputSnapshot,
    ) -> dict[str, Path]:
        self.results_root.mkdir(parents=True, exist_ok=True)
        finalists = {item.record.ticker for item in decision_candidates}
        selected_contract = outcome.final_contract
        ordered = _rank_candidates(outcome.candidates)
        paths = {
            "inputs": self._path("inputs"),
            "strategies": self._path("strategies"),
            "candidates": self._path("candidates"),
            "market": self._path("market"),
            "news_summary": self._path("news_summary"),
            "news_articles": self._path("news_articles"),
            "scoring": self._path("scoring"),
            "scoring_factors": self._path("scoring_factors"),
            "options": self._path("options"),
            "decision": self._path("decision"),
            "final_option": self._path("final_option"),
            "final_target_option": self._path("final_target_option"),
        }

        self._write_inputs(paths["inputs"], metadata=metadata, inputs=inputs)
        self._write_strategies(
            paths["strategies"], metadata=metadata, batch=outcome.batch
        )
        self._write_candidates(
            paths["candidates"],
            metadata=metadata,
            batch=outcome.batch,
            candidates=ordered,
            finalists=finalists,
        )
        self._write_market(
            paths["market"], metadata=metadata, candidates=ordered, finalists=finalists
        )
        self._write_news_summary(
            paths["news_summary"], metadata=metadata, candidates=ordered, finalists=finalists
        )
        self._write_news_articles(
            paths["news_articles"], metadata=metadata, candidates=ordered, finalists=finalists
        )
        self._write_scoring(
            paths["scoring"], metadata=metadata, candidates=ordered, finalists=finalists
        )
        self._write_scoring_factors(
            paths["scoring_factors"],
            metadata=metadata,
            candidates=ordered,
            finalists=finalists,
        )
        self._write_options(
            paths["options"],
            metadata=metadata,
            candidates=ordered,
            finalists=finalists,
            selected_contract=selected_contract,
        )
        self._write_decision(
            paths["decision"],
            metadata=metadata,
            run=run,
            outcome=outcome,
            decision_candidates=decision_candidates,
            selected_contract=selected_contract,
        )
        self._write_final_option(
            paths["final_option"],
            metadata=metadata,
            user=user,
            recommendation=recommendation,
            outcome=outcome,
        )
        self._write_final_target_option(
            paths["final_target_option"],
            metadata=metadata,
            outcome=outcome,
        )
        return paths

    def _path(self, stem: str) -> Path:
        return self.results_root / f"{stem}.csv"

    def _write_inputs(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        inputs: QAInputSnapshot,
    ) -> None:
        self._write_csv(
            path,
            [
                {
                    **_base_row(metadata),
                    "account_size": _dec(inputs.account_size),
                    "risk_profile": inputs.risk_profile,
                    "timezone_label": inputs.timezone_label,
                    "timezone_iana": inputs.timezone_iana,
                    "broker": inputs.broker,
                    "strategy_permission": inputs.strategy_permission,
                    "max_contracts": str(inputs.max_contracts),
                    "openrouter_key_present": _yesno(inputs.openrouter_key_present),
                    "alpha_vantage_key_present": _yesno(inputs.alpha_vantage_key_present),
                    "alpaca_key_present": _yesno(inputs.alpaca_key_present),
                    "alpaca_secret_present": _yesno(inputs.alpaca_secret_present),
                }
            ],
        )

    def _write_strategies(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        batch: CandidateBatch,
    ) -> None:
        rows = []
        for report in batch.strategy_reports:
            rows.append(
                {
                    **_base_row(metadata),
                    "strategy_source": report.strategy_source,
                    "strategy_label": report.strategy_label,
                    "status": report.status,
                    "provider": report.provider,
                    "raw_row_count": str(report.raw_row_count),
                    "candidate_count": str(report.candidate_count),
                    "finviz_candidate_count": str(report.finviz_candidate_count),
                    "backup_candidate_count": str(report.backup_candidate_count),
                    "fallback_used": _yesno(report.fallback_used),
                    "query_urls": " | ".join(report.query_urls),
                    "filter_codes": " | ".join(report.filter_codes),
                    "criteria_summary": report.criteria_summary or "",
                    "sort_summary": report.sort_summary or "",
                    "warning_text": report.warning_text or "",
                    "error": report.error or "",
                }
            )
        self._write_csv(path, rows)

    def _write_candidates(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        batch: CandidateBatch,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for rank, item in enumerate(candidates, start=1):
            chosen = item.evaluation.chosen_contract
            rows.append(
                {
                    **_base_row(metadata),
                    "combined_rank": str(rank),
                    "ticker": item.record.ticker,
                    "company_name": item.context.company_name,
                    "strategy_source": item.record.strategy_source or "",
                    "screener_rank": _int(item.record.screener_rank),
                    "finalist": _yesno(item.record.ticker in finalists),
                    "current_price": _dec(item.context.market_snapshot.current_price),
                    "earnings_date": _date(item.context.earnings_date),
                    "direction": item.evaluation.direction.classification,
                    "direction_score": str(item.evaluation.direction.score),
                    "data_confidence_score": str(item.evaluation.confidence.score),
                    "final_opportunity_score": str(item.evaluation.final_score),
                    "best_strategy": "" if chosen is None else chosen.strategy,
                    "candidate_action": item.evaluation.action,
                    "candidate_sources": " | ".join(item.record.sources),
                    "warning_text": batch.warning_text or "",
                    "calculation_errors": " | ".join(item.context.calculation_errors),
                }
            )
        self._write_csv(path, rows)

    def _write_market(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for item in candidates:
            snapshot = item.context.market_snapshot
            rows.append(
                {
                    **_base_row(metadata),
                    "ticker": item.record.ticker,
                    "finalist": _yesno(item.record.ticker in finalists),
                    "company_name": snapshot.company_name or item.context.company_name,
                    "as_of_date": _date(snapshot.as_of_date),
                    "sector": snapshot.sector or "",
                    "sector_etf": snapshot.sector_etf or "",
                    "market_cap": _dec(snapshot.market_cap),
                    "current_price": _dec(snapshot.current_price),
                    "latest_volume": _int(snapshot.latest_volume),
                    "average_volume_20d": _dec(snapshot.average_volume_20d),
                    "volume_vs_average_20d": _dec(snapshot.volume_vs_average_20d),
                    "stock_return_1d": _dec(snapshot.stock_returns.one_day),
                    "stock_return_5d": _dec(snapshot.stock_returns.five_day),
                    "stock_return_20d": _dec(snapshot.stock_returns.twenty_day),
                    "stock_return_50d": _dec(snapshot.stock_returns.fifty_day),
                    "relative_strength_vs_spy": _dec(snapshot.relative_strength_vs_spy),
                    "relative_strength_vs_qqq": _dec(snapshot.relative_strength_vs_qqq),
                    "relative_strength_vs_sector": _dec(snapshot.relative_strength_vs_sector),
                    "price_source": snapshot.price_source,
                    "overview_source": snapshot.overview_source,
                    "sources": " | ".join(snapshot.sources),
                    "confidence_adjustment": str(snapshot.confidence_adjustment),
                    "confidence_notes": " | ".join(
                        note.detail for note in snapshot.confidence_notes
                    ),
                }
            )
        self._write_csv(path, rows)

    def _write_news_summary(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for item in candidates:
            bundle = item.news_bundle
            brief = bundle.brief
            rows.append(
                {
                    **_base_row(metadata),
                    "ticker": item.record.ticker,
                    "finalist": _yesno(item.record.ticker in finalists),
                    "article_count": str(len(bundle.articles)),
                    "news_coverage": bundle.news_coverage,
                    "stale_news": _yesno(bundle.stale_news),
                    "brief_status": bundle.brief_status,
                    "used_llm_summary": _yesno(bundle.used_llm_summary),
                    "summary": brief.summary,
                    "key_facts": " | ".join(brief.key_facts),
                    "named_actions": " | ".join(brief.named_actions),
                    "quoted_statements": " | ".join(brief.quoted_statements),
                    "neutral_contextual_evidence": " | ".join(
                        brief.neutral_contextual_evidence
                    ),
                    "key_uncertainty": brief.key_uncertainty,
                }
            )
        self._write_csv(path, rows)

    def _write_news_articles(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for item in candidates:
            for article in item.news_bundle.articles:
                rows.append(
                    {
                        **_base_row(metadata),
                        "ticker": item.record.ticker,
                        "finalist": _yesno(item.record.ticker in finalists),
                        "title": article.title,
                        "url": article.url,
                        "source": article.source or "",
                        "published_at": _datetime(article.published_at),
                        "is_ir_fallback": _yesno(article.is_ir_fallback),
                        "snippet": article.snippet,
                    }
                )
        self._write_csv(path, rows)

    def _write_scoring(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for item in candidates:
            chosen = item.evaluation.chosen_contract
            rows.append(
                {
                    **_base_row(metadata),
                    "ticker": item.record.ticker,
                    "finalist": _yesno(item.record.ticker in finalists),
                    "direction_classification": item.evaluation.direction.classification,
                    "direction_bias": str(item.evaluation.direction.bias),
                    "direction_score": str(item.evaluation.direction.score),
                    "data_confidence_score": str(item.evaluation.confidence.score),
                    "data_confidence_label": item.evaluation.confidence.label,
                    "final_opportunity_score": str(item.evaluation.final_score),
                    "candidate_action": item.evaluation.action,
                    "best_strategy": "" if chosen is None else chosen.strategy,
                    "chosen_contract_score": "" if chosen is None else str(chosen.score),
                    "confidence_blockers": " | ".join(item.evaluation.confidence.blockers),
                    "confidence_notes": " | ".join(item.evaluation.confidence.notes),
                    "evaluation_reasons": " | ".join(item.evaluation.reasons),
                    "calculation_errors": " | ".join(item.context.calculation_errors),
                }
            )
        self._write_csv(path, rows)

    def _write_scoring_factors(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
    ) -> None:
        rows = []
        for item in candidates:
            for factor in item.evaluation.direction.factors:
                rows.append(
                    {
                        **_base_row(metadata),
                        "ticker": item.record.ticker,
                        "finalist": _yesno(item.record.ticker in finalists),
                        "factor_name": factor.name,
                        "factor_score": str(factor.score),
                        "factor_weight": str(factor.weight),
                        "factor_detail": factor.detail,
                    }
                )
        self._write_csv(path, rows)

    def _write_options(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        candidates: list[PipelineCandidate],
        finalists: set[str],
        selected_contract: ContractScoreResult | None,
    ) -> None:
        rows = []
        for item in candidates:
            for contract in item.evaluation.considered_contracts:
                rows.append(
                    {
                        **_base_row(metadata),
                        "ticker": item.record.ticker,
                        "finalist": _yesno(item.record.ticker in finalists),
                        "selected_contract": _yesno(
                            _contract_matches(contract, selected_contract)
                        ),
                        "strategy": contract.strategy,
                        "option_type": contract.contract.option_type,
                        "position_side": contract.contract.position_side,
                        "strike": _dec(contract.contract.strike),
                        "expiry": _date(contract.contract.expiry),
                        "bid": _dec(contract.contract.bid),
                        "ask": _dec(contract.contract.ask),
                        "mid": _dec(option_mid(contract.contract)),
                        "volume": _int(contract.contract.volume),
                        "open_interest": _int(contract.contract.open_interest),
                        "implied_volatility": _dec(contract.contract.implied_volatility),
                        "delta": _dec(contract.contract.delta),
                        "gamma": _dec(contract.contract.gamma),
                        "theta": _dec(contract.contract.theta),
                        "vega": _dec(contract.contract.vega),
                        "liquidity_score": str(contract.liquidity_score),
                        "contract_score": str(contract.score),
                        "is_viable": _yesno(contract.is_viable),
                        "vetoes": " | ".join(veto.reason for veto in contract.vetoes),
                        "reasons": " | ".join(contract.reasons),
                        "target_method": ""
                        if contract.exit_target is None
                        else contract.exit_target.target_method,
                        "target_stock_price": ""
                        if contract.exit_target is None
                        else _dec(contract.exit_target.target_stock_price),
                        "target_option_price": ""
                        if contract.exit_target is None
                        else _dec(contract.exit_target.target_option_price),
                        "stop_loss_option_price": ""
                        if contract.exit_target is None
                        else _dec(contract.exit_target.stop_loss_option_price),
                        "exit_by_date": ""
                        if contract.exit_target is None
                        else _date(contract.exit_target.exit_by_date),
                    }
                )
        self._write_csv(path, rows)

    def _write_decision(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        run: WorkflowRun,
        outcome: PipelineOutcome,
        decision_candidates: list[PipelineCandidate],
        selected_contract: ContractScoreResult | None,
    ) -> None:
        decision = outcome.decision
        rows = [
            {
                **_base_row(metadata),
                "run_status": run.status,
                "decision_engine": outcome.decision_trace.engine,
                "heavy_model_used": outcome.decision_trace.heavy_model_used or "",
                "trace_notes": " | ".join(outcome.decision_trace.notes),
                "decision_action": decision.action,
                "chosen_ticker": decision.chosen_ticker or "",
                "chosen_contract_option_type": ""
                if decision.chosen_contract is None
                else decision.chosen_contract.option_type,
                "chosen_contract_position_side": ""
                if decision.chosen_contract is None
                else decision.chosen_contract.position_side,
                "chosen_contract_strike": ""
                if decision.chosen_contract is None
                else _dec(decision.chosen_contract.strike),
                "chosen_contract_expiry": ""
                if decision.chosen_contract is None
                else _date(decision.chosen_contract.expiry),
                "direction_score": _int(decision.direction_score),
                "contract_score": _int(decision.contract_score),
                "final_score": _int(decision.final_score),
                "reasoning": decision.reasoning,
                "key_evidence": " | ".join(decision.key_evidence),
                "key_concerns": " | ".join(decision.key_concerns),
                "watchlist_tickers": " | ".join(decision.watchlist_tickers),
                "decision_finalists": " | ".join(
                    item.record.ticker for item in decision_candidates
                ),
                "selected_contract_strategy": ""
                if selected_contract is None
                else selected_contract.strategy,
                "selected_contract_score": ""
                if selected_contract is None
                else str(selected_contract.score),
            }
        ]
        self._write_csv(path, rows)

    def _write_final_option(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        user: User,
        recommendation: Recommendation | None,
        outcome: PipelineOutcome,
    ) -> None:
        selected_contract = outcome.final_contract
        selected = outcome.selected
        if recommendation is None or selected is None or selected_contract is None:
            rows = [
                {
                    **_base_row(metadata),
                    "ticker": "",
                    "company_name": "",
                    "strategy": "",
                    "option_type": "",
                    "position_side": "",
                    "strike": "",
                    "expiry": "",
                    "entry_price": "",
                    "quantity": "",
                    "estimated_max_loss": "",
                    "confidence_score": _int(outcome.decision.final_score),
                    "decision_action": outcome.decision.action,
                    "reasoning": outcome.decision.reasoning,
                    "account_size": _dec(user.account_size),
                    "risk_profile": user.risk_profile,
                    "broker": user.broker,
                    "timezone": user.timezone_label,
                    "strategy_permission": user.strategy_permission,
                }
            ]
        else:
            rows = [
                {
                    **_base_row(metadata),
                    "ticker": recommendation.ticker,
                    "company_name": recommendation.company_name,
                    "strategy": recommendation.strategy,
                    "option_type": recommendation.option_type,
                    "position_side": recommendation.position_side,
                    "strike": _dec(recommendation.strike),
                    "expiry": _date(recommendation.expiry),
                    "entry_price": _dec(recommendation.suggested_entry),
                    "quantity": str(recommendation.suggested_quantity),
                    "estimated_max_loss": recommendation.estimated_max_loss,
                    "confidence_score": str(recommendation.confidence_score),
                    "decision_action": outcome.decision.action,
                    "reasoning": outcome.decision.reasoning,
                    "account_size": _dec(user.account_size),
                    "risk_profile": user.risk_profile,
                    "broker": user.broker,
                    "timezone": user.timezone_label,
                    "strategy_permission": user.strategy_permission,
                }
            ]
        self._write_csv(path, rows)

    def _write_final_target_option(
        self,
        path: Path,
        *,
        metadata: QAArtifactMetadata,
        outcome: PipelineOutcome,
    ) -> None:
        selected = outcome.selected
        selected_contract = outcome.final_contract
        if selected is None or selected_contract is None or selected_contract.exit_target is None:
            rows = [{**_base_row(metadata), "ticker": "", "strategy": ""}]
        else:
            target = selected_contract.exit_target
            rows = [
                {
                    **_base_row(metadata),
                    "ticker": selected.record.ticker,
                    "strategy": selected_contract.strategy,
                    "target_method": target.target_method,
                    "target_stock_price": _dec(target.target_stock_price),
                    "target_option_price": _dec(target.target_option_price),
                    "target_gain_percent": _dec(target.target_gain_percent),
                    "stop_loss_option_price": _dec(target.stop_loss_option_price),
                    "exit_by_date": _date(target.exit_by_date),
                    "expected_holding_days": str(target.expected_holding_days),
                    "delta": _dec(selected_contract.contract.delta),
                    "gamma": _dec(selected_contract.contract.gamma),
                    "theta": _dec(selected_contract.contract.theta),
                    "vega": _dec(selected_contract.contract.vega),
                    "implied_volatility": _dec(
                        selected_contract.contract.implied_volatility
                    ),
                }
            ]
        self._write_csv(path, rows)

    def _write_csv(self, path: Path, rows: list[dict[str, str]]) -> None:
        fieldnames = _fieldnames(rows)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})


def _base_row(metadata: QAArtifactMetadata) -> dict[str, str]:
    return {
        "run_id": str(metadata.run_id),
        "lane": metadata.lane,
        "reference_dt_utc": _datetime(metadata.reference_dt_utc),
        "reference_trading_date": _date(metadata.reference_trading_date),
        "qa_user_id": metadata.qa_user_id,
        "qa_user_chat_id": metadata.qa_user_chat_id,
    }


def _rank_candidates(candidates: tuple[PipelineCandidate, ...]) -> list[PipelineCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.evaluation.direction.score,
        ),
        reverse=True,
    )


def _fieldnames(rows: list[dict[str, str]]) -> list[str]:
    if not rows:
        return list(_base_row_placeholder())
    ordered = list(rows[0].keys())
    seen = set(ordered)
    for row in rows[1:]:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


def _base_row_placeholder() -> dict[str, str]:
    return {
        "run_id": "",
        "lane": "",
        "reference_dt_utc": "",
        "reference_trading_date": "",
        "qa_user_id": "",
        "qa_user_chat_id": "",
    }


def _yesno(value: bool) -> str:
    return "true" if value else "false"


def _dec(value: Decimal | None) -> str:
    return "" if value is None else format(value, "f")


def _int(value: int | None) -> str:
    return "" if value is None else str(value)


def _date(value: date | None) -> str:
    return "" if value is None else value.isoformat()


def _datetime(value: datetime | None) -> str:
    return "" if value is None else value.isoformat()


def _contract_matches(
    left: ContractScoreResult | None,
    right: ContractScoreResult | None,
) -> bool:
    if left is None or right is None:
        return False
    return (
        left.contract.ticker == right.contract.ticker
        and left.contract.option_type == right.contract.option_type
        and left.contract.position_side == right.contract.position_side
        and left.contract.strike == right.contract.strike
        and left.contract.expiry == right.contract.expiry
    )
