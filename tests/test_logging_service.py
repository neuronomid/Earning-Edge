from __future__ import annotations

import getpass
import json
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

from app.core.config import Settings
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.db.models.workflow_run import WorkflowRun
from app.llm.schemas import ChosenContract, StructuredDecision
from app.pipeline.types import DecisionTrace, PipelineCandidate, PipelineOutcome
from app.scoring.types import (
    CandidateContext,
    CandidateEvaluation,
    ContractScoreResult,
    DataConfidenceResult,
    DirectionResult,
    HardVeto,
    OptionContractInput,
    StrategySelection,
)
from app.services.candidate_models import CandidateBatch, CandidateRecord
from app.services.logging_service import LoggingService
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsArticle, NewsBrief, NewsBundle
from app.services.sizing_types import SizingResult
from app.services.strategy_catalog import build_strategy_report
from tests.fixtures.balanced_25_pool import STRATEGIES


def test_logging_service_builds_complete_artifacts_and_archive(tmp_path) -> None:
    user_id = uuid4()
    run_id = uuid4()
    rec_id = uuid4()
    started_at = datetime(2026, 5, 1, 16, 0, tzinfo=UTC)
    finished_at = datetime(2026, 5, 1, 16, 5, tzinfo=UTC)
    created_at = datetime(2026, 5, 1, 16, 5, tzinfo=UTC)

    user = User(
        id=user_id,
        telegram_chat_id="12345",
        account_size=Decimal("20000.00"),
        risk_profile="Balanced",
        broker="IBKR",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=3,
        openrouter_api_key_encrypted="enc",
    )
    run = WorkflowRun(
        id=run_id,
        user_id=user_id,
        trigger_type="manual",
        status="success",
        started_at=started_at,
        finished_at=finished_at,
        screener_status="success",
        selected_candidate_count=2,
        final_recommendation_id=rec_id,
    )
    recommendation = Recommendation(
        id=rec_id,
        user_id=user_id,
        run_id=run_id,
        ticker="AMD",
        company_name="AMD Corp.",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        suggested_entry=Decimal("1.25"),
        suggested_quantity=2,
        estimated_max_loss="$125.00 max loss per contract",
        account_risk_percent=Decimal("2.0000"),
        confidence_score=82,
        risk_level="High",
        reasoning_summary="AMD had the strongest setup in the run.",
        key_evidence_json=["Momentum held up into earnings."],
        key_concerns_json=["IV crush remains a risk."],
        telegram_message_id="42",
        created_at=created_at,
    )

    selected = _candidate(
        ticker="AMD",
        current_price=Decimal("102"),
        contract_inputs=(
            _contract("AMD", strike="104", bid="1.10", ask="1.25"),
            _contract("AMD", strike="108", bid="0.30", ask="1.10"),
        ),
        final_score=82,
        confidence_score=88,
        chosen_index=0,
        rejected_indexes={1: "Bid/ask spread is extremely wide."},
        action="recommend",
    )
    rejected = _candidate(
        ticker="AAPL",
        current_price=Decimal("190"),
        contract_inputs=(_contract("AAPL", strike="195", bid="1.15", ask="1.35"),),
        final_score=64,
        confidence_score=74,
        chosen_index=0,
        rejected_indexes={},
        action="watchlist",
    )
    outcome = PipelineOutcome(
        batch=CandidateBatch(
            candidates=(selected.record, rejected.record),
            screener_status="success",
            fallback_used=False,
            warning_text=None,
        ),
        decision=StructuredDecision(
            action="recommend",
            chosen_ticker="AMD",
            chosen_contract=ChosenContract(
                ticker="AMD",
                option_type="call",
                position_side="long",
                strike=Decimal("104"),
                expiry=date(2026, 5, 16),
                rationale="Highest combined score.",
            ),
            contract_score=84,
            final_score=82,
            reasoning="AMD had the cleanest mix of trend, liquidity, and confidence.",
            key_evidence=[
                "Relative strength stayed positive.",
                "Best contract cleared liquidity screens.",
            ],
            key_concerns=["IV crush remains a risk."],
            watchlist_tickers=["AMD", "AAPL"],
        ),
        candidates=(selected, rejected),
        selected=selected,
    )

    service = LoggingService(archive_root=tmp_path / "runs")
    artifacts = service.capture_run(
        run=run,
        user=user,
        outcome=outcome,
        recommendation=recommendation,
        telegram_message="Earnings Options Signal",
    )

    recommendation_keys = {
        "card_id",
        "user_id",
        "run_id",
        "timestamp",
        "trigger_type",
        "selected_ticker",
        "selected_company",
        "selected_strategy",
        "selected_contract",
        "suggested_quantity",
        "confidence_score",
        "risk_profile",
        "account_size_snapshot",
        "earnings_date",
        "earnings_timing",
        "key_evidence",
        "key_concerns",
        "rejected_alternatives",
        "data_confidence",
        "decision_engine",
        "model_used_heavy",
        "model_used_light",
        "telegram_message",
        "created_at",
    }
    candidate_keys = {
        "ticker",
        "screener_rank",
        "company_name",
        "current_price",
        "sector",
        "market_cap",
        "earnings_date",
        "earnings_date_verified",
        "data_confidence_score",
        "direction_classification",
        "candidate_direction_score",
        "best_contract_score",
        "final_opportunity_score",
        "best_strategy",
        "strategy_source",
        "candidate_sources",
        "candidate_origin",
        "best_contract",
        "selected_contract",
        "selected_contract_matches_best_scored",
        "reason_selected_or_rejected",
        "data_sources_used",
        "missing_data_fields",
        "validation_notes",
    }
    contract_keys = {
        "ticker",
        "option_type",
        "position_side",
        "strike",
        "expiry",
        "bid",
        "ask",
        "mid",
        "volume",
        "open_interest",
        "implied_volatility",
        "delta",
        "breakeven",
        "spread_percent",
        "liquidity_score",
        "contract_score",
        "passed_hard_filters",
        "rejection_reason",
    }

    assert recommendation_keys.issubset(artifacts.recommendation_card.keys())
    assert candidate_keys.issubset(artifacts.candidate_cards[0].keys())
    assert contract_keys.issubset(artifacts.option_contracts[0].keys())
    assert artifacts.recommendation_card["selected_strategy"] == "Long call"
    assert artifacts.recommendation_card["data_confidence"] == 88
    assert artifacts.recommendation_card["decision_engine"] == "heuristic"
    assert artifacts.recommendation_card["model_used_heavy"] is None
    assert artifacts.recommendation_card["model_used_light"] is None
    assert artifacts.run_summary["screener_tickers"] == ["AMD", "AAPL"]
    assert artifacts.run_summary["decision_engine"] == "heuristic"
    rejected_contracts = [
        contract for contract in artifacts.option_contracts if not contract["passed_hard_filters"]
    ]
    assert len(rejected_contracts) == 1
    assert rejected_contracts[0]["rejection_reason"] == "Bid/ask spread is extremely wide."
    assert run.recommendation_card_json == artifacts.recommendation_card

    archive_dir = tmp_path / "runs" / str(run_id)
    archived_summary = json.loads((archive_dir / "run_summary.json").read_text(encoding="utf-8"))
    assert archived_summary["run_id"] == str(run_id)
    assert len(json.loads((archive_dir / "candidate_cards.json").read_text(encoding="utf-8"))) == 2
    assert len(json.loads((archive_dir / "option_contracts.json").read_text(encoding="utf-8"))) == 3
    assert (
        json.loads((archive_dir / "recommendation_card.json").read_text(encoding="utf-8"))[
            "selected_ticker"
        ]
        == "AMD"
    )
    assert (archive_dir / "telegram_message.txt").read_text(encoding="utf-8") == (
        "Earnings Options Signal"
    )
    results_dir = tmp_path / "results"
    username = getpass.getuser().strip().lower().replace(" ", "_")
    assert sorted(path.name for path in results_dir.glob("*.csv")) == [
        f"{username}_combined_2026-05-01.csv",
        f"{username}_strategy_a_2026-05-01.csv",
        f"{username}_strategy_b_2026-05-01.csv",
        f"{username}_strategy_c_2026-05-01.csv",
        f"{username}_strategy_d_2026-05-01.csv",
        f"{username}_strategy_e_2026-05-01.csv",
    ]


def test_logging_service_records_actual_model_usage(tmp_path) -> None:
    user_id = uuid4()
    run_id = uuid4()
    rec_id = uuid4()
    created_at = datetime(2026, 5, 1, 16, 5, tzinfo=UTC)

    user = User(
        id=user_id,
        telegram_chat_id="12345",
        account_size=Decimal("20000.00"),
        risk_profile="Balanced",
        broker="IBKR",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=3,
        openrouter_api_key_encrypted="enc",
    )
    run = WorkflowRun(
        id=run_id,
        user_id=user_id,
        trigger_type="manual",
        status="success",
        started_at=created_at,
        finished_at=created_at,
        screener_status="success",
        selected_candidate_count=1,
        final_recommendation_id=rec_id,
    )
    recommendation = Recommendation(
        id=rec_id,
        user_id=user_id,
        run_id=run_id,
        ticker="AMD",
        company_name="AMD Corp.",
        strategy="long_call",
        option_type="call",
        position_side="long",
        strike=Decimal("104.00"),
        expiry=date(2026, 5, 16),
        suggested_entry=Decimal("1.25"),
        suggested_quantity=2,
        estimated_max_loss="$125.00 max loss per contract",
        account_risk_percent=Decimal("2.0000"),
        confidence_score=82,
        risk_level="High",
        reasoning_summary="AMD had the strongest setup in the run.",
        key_evidence_json=["Momentum held up into earnings."],
        key_concerns_json=["IV crush remains a risk."],
        telegram_message_id="42",
        created_at=created_at,
    )
    candidate = _candidate(
        ticker="AMD",
        current_price=Decimal("102"),
        contract_inputs=(_contract("AMD", strike="104", bid="1.10", ask="1.25"),),
        final_score=82,
        confidence_score=88,
        chosen_index=0,
        rejected_indexes={},
        action="recommend",
    )
    candidate = replace(
        candidate,
        news_bundle=candidate.news_bundle.model_copy(
            update={
                "used_llm_summary": True,
                "articles": (
                    NewsArticle(
                        title="AMD beats expectations",
                        url="https://example.com/amd",
                        snippet="AMD earnings beat",
                        content="AMD reported strong quarterly results.",
                        source="example.com",
                    ),
                ),
            }
        ),
    )
    outcome = PipelineOutcome(
        batch=CandidateBatch(
            candidates=(candidate.record,),
            screener_status="success",
            fallback_used=False,
            warning_text=None,
        ),
        decision=StructuredDecision(
            action="recommend",
            chosen_ticker="AMD",
            chosen_contract=ChosenContract(
                ticker="AMD",
                option_type="call",
                position_side="long",
                strike=Decimal("104"),
                expiry=date(2026, 5, 16),
                rationale="Highest combined score.",
            ),
            contract_score=84,
            final_score=82,
            reasoning="AMD had the cleanest mix of trend, liquidity, and confidence.",
            key_evidence=["Relative strength stayed positive."],
            key_concerns=["IV crush remains a risk."],
            watchlist_tickers=["AMD"],
        ),
        candidates=(candidate,),
        selected=candidate,
        decision_trace=DecisionTrace(
            engine="llm",
            heavy_model_used="claude-opus-4.7-thinking",
        ),
    )

    service = LoggingService(
        archive_root=tmp_path / "runs",
        settings=Settings(
            app_encryption_key="x" * 44,
            market_analysis_model="claude-opus-4.7-thinking",
            lightweight_model="google/gemini-3.1-pro-preview",
        ),
    )
    artifacts = service.build_run_artifacts(
        run=run,
        user=user,
        outcome=outcome,
        recommendation=recommendation,
        telegram_message="Earnings Options Signal",
    )

    assert artifacts.recommendation_card["decision_engine"] == "llm"
    assert artifacts.recommendation_card["model_used_heavy"] == "claude-opus-4.7-thinking"
    assert artifacts.recommendation_card["model_used_light"] == "google/gemini-3.1-pro-preview"
    assert artifacts.run_summary["model_used_heavy"] == "claude-opus-4.7-thinking"
    assert artifacts.run_summary["model_used_light"] == "google/gemini-3.1-pro-preview"


def _candidate(
    *,
    ticker: str,
    current_price: Decimal,
    contract_inputs: tuple[OptionContractInput, ...],
    final_score: int,
    confidence_score: int,
    chosen_index: int | None,
    rejected_indexes: dict[int, str],
    action: str,
    direction_score: int = 80,
) -> PipelineCandidate:
    considered: list[ContractScoreResult] = []
    chosen: ContractScoreResult | None = None
    for index, contract in enumerate(contract_inputs):
        rejection = rejected_indexes.get(index)
        result = ContractScoreResult(
            strategy=contract.strategy,
            contract=contract,
            base_score=84 if rejection is None else 55,
            score=84 if rejection is None else 0,
            factors=(),
            penalties=(),
            vetoes=() if rejection is None else (HardVeto("rejected", rejection),),
            breakeven=Decimal("105.25"),
            breakeven_move_percent=Decimal("0.03"),
            liquidity_score=82 if rejection is None else 25,
            expiry_days_after_earnings=7,
            reasons=(f"{ticker} contract {'won' if rejection is None else 'failed'} scoring.",),
        )
        considered.append(result)
        if chosen_index == index:
            chosen = result

    record = CandidateRecord(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        market_cap=Decimal("900"),
        earnings_date=date(2026, 5, 8),
        current_price=current_price,
        sector="Technology",
        sources=("fixture",),
    )
    snapshot = MarketSnapshot(
        ticker=ticker,
        as_of_date=date(2026, 5, 1),
        company_name=f"{ticker} Corp.",
        sector="Technology",
        sector_etf="XLK",
        market_cap=Decimal("900"),
        current_price=current_price,
        latest_volume=1_000_000,
        average_volume_20d=Decimal("900000"),
        volume_vs_average_20d=Decimal("1.10"),
        stock_returns=ReturnMetrics(
            one_day=Decimal("0.01"),
            five_day=Decimal("0.04"),
            twenty_day=Decimal("0.07"),
            fifty_day=Decimal("0.10"),
        ),
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.003"),
            five_day=Decimal("0.01"),
            twenty_day=Decimal("0.03"),
            fifty_day=Decimal("0.05"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.004"),
            five_day=Decimal("0.015"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.002"),
            five_day=Decimal("0.02"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        relative_strength_vs_spy=Decimal("0.03"),
        relative_strength_vs_qqq=Decimal("0.02"),
        relative_strength_vs_sector=Decimal("0.01"),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
        confidence_adjustment=0,
        confidence_notes=(),
    )
    bundle = NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        generated_at=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            neutral_contextual_evidence=["Sector demand stayed firm."],
            key_uncertainty="Guidance tone still matters.",
            summary=f"{ticker} held its trend into earnings.",
            key_facts=[f"{ticker} momentum stayed constructive over the past month."],
        ),
        used_ir_fallback=False,
    )
    evaluation = CandidateEvaluation(
        ticker=ticker,
        direction=DirectionResult(
            classification="bullish",
            bias=Decimal("0.70"),
            score=direction_score,
            factors=(),
            reasons=(f"{ticker} momentum stayed constructive.",),
        ),
        confidence=DataConfidenceResult(
            score=confidence_score,
            label="good",
            blockers=(),
            notes=("Pricing came from fixture data.",),
        ),
        strategy_selection=StrategySelection(
            allowed_strategies=tuple(contract.strategy for contract in contract_inputs),
            preferred_order=tuple(contract.strategy for contract in contract_inputs),
            reason="Fixture order.",
        ),
        considered_contracts=tuple(considered),
        chosen_contract=chosen,
        final_score=final_score,
        action=action,  # type: ignore[arg-type]
        reasons=(f"{ticker} kept the cleanest contract.",),
    )
    return PipelineCandidate(
        record=record,
        context=CandidateContext(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            earnings_date=date(2026, 5, 8),
            earnings_timing="unknown",
            market_snapshot=snapshot,
            news_brief=bundle.brief,
            option_chain=contract_inputs,
            verified_earnings_date=True,
            identity_verified=True,
            expected_move_percent=None,
            previous_earnings_move_percent=None,
            source_conflicts=(),
            calculation_errors=(),
        ),
        evaluation=evaluation,
        news_bundle=bundle,
        sizing=SizingResult(
            quantity=2,
            max_loss_text="$125.00 max loss per contract",
            account_risk_pct=Decimal("0.02"),
            broker_verification_required=False,
            watch_only=False,
        ),
    )


def _contract(
    ticker: str,
    *,
    strike: str,
    bid: str,
    ask: str,
) -> OptionContractInput:
    return OptionContractInput(
        ticker=ticker,
        option_type="call",
        position_side="long",
        strike=Decimal(strike),
        expiry=date(2026, 5, 16),
        bid=Decimal(bid),
        ask=Decimal(ask),
        mid=(Decimal(bid) + Decimal(ask)) / Decimal("2"),
        volume=120,
        open_interest=320,
        implied_volatility=Decimal("0.44"),
        delta=Decimal("0.52"),
        source="fixture",
    )


def test_strategy_reports_persists_all_five_rows(tmp_path) -> None:
    """Phase 5: every five-strategy run must surface a row per arm in JSON output."""
    user_id = uuid4()
    run_id = uuid4()
    created_at = datetime(2026, 5, 1, 16, 5, tzinfo=UTC)
    user = User(
        id=user_id,
        telegram_chat_id="12345",
        account_size=Decimal("20000.00"),
        risk_profile="Balanced",
        broker="IBKR",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=3,
        openrouter_api_key_encrypted="enc",
    )
    run = WorkflowRun(
        id=run_id,
        user_id=user_id,
        trigger_type="manual",
        status="no_trade",
        started_at=created_at,
        finished_at=created_at,
        screener_status="success",
        selected_candidate_count=0,
    )
    reports = tuple(
        build_strategy_report(
            strategy,
            status="success",
            raw_row_count=5,
            candidate_count=5,
            finviz_candidate_count=0 if strategy == "activist_13d_followthrough" else 5,
            backup_candidate_count=5 if strategy == "activist_13d_followthrough" else 0,
        )
        for strategy in STRATEGIES
    )
    outcome = PipelineOutcome(
        batch=CandidateBatch(
            candidates=(),
            screener_status="success",
            fallback_used=False,
            warning_text=None,
            strategy_reports=reports,
        ),
        decision=StructuredDecision(
            action="no_trade",
            confidence_band="no_trade",
            reasoning="Balanced fixture run.",
            key_evidence=[],
            key_concerns=[],
            watchlist_tickers=[],
        ),
        candidates=(),
        selected=None,
    )

    service = LoggingService(archive_root=tmp_path / "runs")
    artifacts = service.capture_run(
        run=run,
        user=user,
        outcome=outcome,
        recommendation=None,
        telegram_message="No trade this scan.",
    )

    assert len(artifacts.run_summary["strategy_reports"]) == 5
    sources = [entry["strategy_source"] for entry in artifacts.run_summary["strategy_reports"]]
    assert set(sources) == set(STRATEGIES)
    assert len(artifacts.recommendation_card["strategy_reports"]) == 5
    persisted = run.run_summary_json
    assert persisted is not None
    assert [entry["strategy_source"] for entry in persisted["strategy_reports"]] == list(sources)
