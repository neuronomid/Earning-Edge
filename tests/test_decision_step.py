from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.core.config import Settings
from app.llm.schemas import ChosenContract, StructuredDecision
from app.llm.types import LLMAuthenticationError
from app.pipeline.steps.decide import (
    HeuristicDecisionStep,
    LLMDecisionStep,
    build_decision_input,
    get_default_decision_step,
    resolve_selected_contract,
)
from app.pipeline.types import PipelineCandidate
from app.scoring.types import (
    CandidateContext,
    CandidateEvaluation,
    ContractScoreResult,
    DataConfidenceResult,
    DirectionResult,
    HardVeto,
    OptionContractInput,
    StrategySelection,
    UserContext,
)
from app.services.candidate_models import CandidateRecord, StrategyEventSignal
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsBrief, NewsBundle

pytestmark = pytest.mark.asyncio


class StubRouter:
    def __init__(
        self,
        *,
        decision: StructuredDecision | None = None,
        error: Exception | None = None,
        heavy_model: str = "claude-opus-4.7-thinking",
    ) -> None:
        self._decision = decision
        self._error = error
        self.heavy_model = heavy_model

    async def decide(self, **kwargs) -> StructuredDecision:
        del kwargs
        if self._error is not None:
            raise self._error
        assert self._decision is not None
        return self._decision


async def test_llm_decision_step_accepts_valid_contract_from_visible_candidates() -> None:
    candidate = _candidate("MCD", chosen_index=0)
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="MCD",
                chosen_contract=ChosenContract(
                    ticker="MCD",
                    option_type="put",
                    position_side="long",
                    strike=Decimal("265"),
                    expiry=date(2026, 5, 15),
                    rationale="Slightly cheaper while still close to the current price.",
                ),
                confidence_band="standard",
                reasoning="MCD had the clearest bearish setup with a liquid put chain.",
                key_evidence=["Relative strength rolled over.", "Put volume stayed active."],
                key_concerns=["Earnings reaction could reverse quickly."],
                watchlist_tickers=[],
            )
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert result.trace.engine == "llm"
    assert result.trace.heavy_model_used == "claude-opus-4.7-thinking"
    assert result.decision.chosen_contract is not None
    assert result.decision.chosen_contract.strike == Decimal("265")
    matched = resolve_selected_contract(candidate, result.decision.chosen_contract)
    assert matched is not None
    assert matched.contract.strike == Decimal("265")
    # final_score is deterministic — combine_scores(direction=74, contract=74) = 74
    assert result.decision.final_score == 74
    assert result.decision.contract_score == 74


async def test_llm_decision_step_falls_back_when_model_selects_unknown_contract() -> None:
    candidate = _candidate("MCD", chosen_index=0)
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="MCD",
                chosen_contract=ChosenContract(
                    ticker="MCD",
                    option_type="put",
                    position_side="long",
                    strike=Decimal("250"),
                    expiry=date(2026, 5, 15),
                    rationale="Not actually in the visible chain.",
                ),
                confidence_band="standard",
                reasoning="This should fail validation.",
                key_evidence=["Relative strength rolled over.", "Put volume stayed active."],
                key_concerns=["Earnings reaction could reverse quickly."],
                watchlist_tickers=[],
            )
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert result.trace.engine == "heuristic_fallback"
    assert result.decision.chosen_contract is not None
    assert result.decision.chosen_contract.strike == Decimal("270")
    assert "failed" in result.trace.notes[0].lower()


async def test_llm_decision_step_returns_no_trade_on_authentication_error() -> None:
    candidate = _candidate("MCD", chosen_index=0)
    step = LLMDecisionStep(
        router=StubRouter(
            error=LLMAuthenticationError("OpenRouter rejected the API key."),
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-bad",
    )

    assert result.trace.engine == "llm_blocked"
    assert result.trace.heavy_model_used is None
    assert result.decision.action == "no_trade"
    assert "OpenRouter key" in result.decision.reasoning
    assert result.decision.key_concerns == ["OpenRouter rejected the API key."]


async def test_llm_decision_step_falls_back_when_model_selects_non_viable_visible_contract(
) -> None:
    candidate = _candidate(
        "MCD",
        chosen_index=0,
        rejected_indexes={1: "Bid/ask spread is extremely wide."},
    )
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="MCD",
                chosen_contract=ChosenContract(
                    ticker="MCD",
                    option_type="put",
                    position_side="long",
                    strike=Decimal("265"),
                    expiry=date(2026, 5, 15),
                    rationale="Still visible in the chain, but it was rejected by scoring.",
                ),
                confidence_band="standard",
                reasoning="This should fail validation.",
                key_evidence=["Relative strength rolled over."],
                key_concerns=["Spread is too wide."],
                watchlist_tickers=[],
            )
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert result.trace.engine == "heuristic_fallback"
    assert result.decision.chosen_contract is not None
    assert result.decision.chosen_contract.strike == Decimal("270")


async def test_llm_decision_step_downgrades_action_when_model_escalates_watchlist_to_recommend(
) -> None:
    # Structural: direction=74, contract=54 → combine = (74*0.45 + 54*0.55) ≈ 63 → watchlist
    candidate = _candidate(
        "MCD",
        chosen_index=0,
        final_score=63,
        action="watchlist",
        contract_scores=(54, 50),
    )
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="MCD",
                chosen_contract=ChosenContract(
                    ticker="MCD",
                    option_type="put",
                    position_side="long",
                    strike=Decimal("270"),
                    expiry=date(2026, 5, 15),
                    rationale="The model tried to promote a weaker setup.",
                ),
                confidence_band="standard",
                reasoning="The scorer only allows watchlist for this contract.",
                key_evidence=["Relative strength rolled over."],
                key_concerns=["Contract score stayed average."],
                watchlist_tickers=[],
            )
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert result.trace.engine == "llm"
    assert result.decision.action == "watchlist"
    assert result.decision.confidence_band == "watchlist"
    assert result.decision.chosen_ticker == "MCD"
    assert result.decision.chosen_contract is not None
    assert result.decision.chosen_contract.strike == Decimal("270")
    # final_score is structural: combine_scores(74, 54) = 63
    assert result.decision.final_score == 63


async def test_llm_decision_step_accepts_conservative_watchlist_on_recommend_quality_setup(
) -> None:
    # Structural says recommend (72), but LLM picks watchlist for news reasons.
    # The conservative call wins on action; the displayed final_score remains
    # the deterministic structural number.
    candidate = _candidate(
        "MCD",
        chosen_index=0,
        final_score=72,
        action="recommend",
        contract_scores=(70, 66),
    )
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="watchlist",
                chosen_ticker="MCD",
                chosen_contract=ChosenContract(
                    ticker="MCD",
                    option_type="put",
                    position_side="long",
                    strike=Decimal("270"),
                    expiry=date(2026, 5, 15),
                    rationale="Catalyst quality is too thin for a full recommendation.",
                ),
                direction_tier="bullish",
                confidence_band="watchlist",
                reasoning="The setup is structurally sound, but conviction is not high enough.",
                key_evidence=["Relative strength rolled over."],
                key_concerns=["Catalyst coverage is sparse."],
                watchlist_tickers=[],
            )
        )
    )

    result = await step.execute(
        [candidate],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert result.trace.engine == "llm"
    assert result.decision.action == "watchlist"
    assert result.decision.confidence_band == "watchlist"
    assert result.decision.direction_tier == "bullish"
    # Structural: combine_scores(74, 70) = 72
    assert result.decision.contract_score == 70
    assert result.decision.final_score == 72


async def test_default_decision_step_uses_heuristic_in_tests_and_llm_elsewhere() -> None:
    test_settings = Settings(app_env="test", app_encryption_key="x" * 44)
    dev_settings = Settings(app_env="development", app_encryption_key="x" * 44)

    assert isinstance(get_default_decision_step(settings=test_settings), HeuristicDecisionStep)
    assert isinstance(get_default_decision_step(settings=dev_settings), LLMDecisionStep)


async def test_build_decision_input_includes_strategy_source_and_event_signal_detail() -> None:
    signal = StrategyEventSignal(
        score=91,
        is_supportive=True,
        detail="Sector RS: top-decile sector and stock momentum.",
    )
    base = _candidate("XLF", chosen_index=0)
    candidate = replace(
        base,
        record=replace(
            base.record,
            strategy_source="sector_relative_strength",
            event_signal=signal,
        ),
        context=replace(
            base.context,
            strategy_source="sector_relative_strength",
            event_signal=signal,
        ),
    )

    decision_input = build_decision_input([candidate], _user_context())
    bundle = decision_input.candidates[0]

    assert bundle.strategy_source == "sector_relative_strength"
    assert bundle.event_signal_detail == signal.detail


def _candidate(
    ticker: str,
    *,
    chosen_index: int,
    final_score: int = 76,
    action: str = "recommend",
    contract_scores: tuple[int, int] = (76, 74),
    rejected_indexes: dict[int, str] | None = None,
) -> PipelineCandidate:
    rejected_indexes = rejected_indexes or {}
    contracts = (
        _contract_result(
            ticker,
            strike="270",
            score=contract_scores[0],
            rejection_reason=rejected_indexes.get(0),
        ),
        _contract_result(
            ticker,
            strike="265",
            score=contract_scores[1],
            rejection_reason=rejected_indexes.get(1),
        ),
    )
    chosen = contracts[chosen_index]
    return PipelineCandidate(
        record=CandidateRecord(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            market_cap=Decimal("250000000000"),
            earnings_date=date(2026, 5, 8),
            current_price=Decimal("267"),
            screener_rank=1,
            sector="Consumer Defensive",
        ),
        context=CandidateContext(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            earnings_date=date(2026, 5, 8),
            earnings_timing="AMC",
            market_snapshot=_market_snapshot(ticker),
            news_brief=_news_bundle(ticker).brief,
            option_chain=tuple(contract.contract for contract in contracts),
        ),
        evaluation=CandidateEvaluation(
            ticker=ticker,
            direction=DirectionResult(
                classification="bearish",
                bias=Decimal("-0.62"),
                score=74,
                factors=(),
                reasons=(f"{ticker} underperformed its peers into earnings.",),
            ),
            confidence=DataConfidenceResult(
                score=84,
                label="good",
                blockers=(),
                notes=("Fixture data used for decision-step tests.",),
            ),
            strategy_selection=StrategySelection(
                allowed_strategies=("long_put",),
                preferred_order=("long_put",),
                reason="Fixture order.",
            ),
            considered_contracts=contracts,
            chosen_contract=chosen,
            final_score=final_score,
            action=action,  # type: ignore[arg-type]
            reasons=(f"{ticker} had the cleanest bearish setup.",),
        ),
        news_bundle=_news_bundle(ticker),
        sizing=None,
    )


def _contract_result(
    ticker: str,
    *,
    strike: str,
    score: int,
    rejection_reason: str | None = None,
) -> ContractScoreResult:
    contract = OptionContractInput(
        ticker=ticker,
        option_type="put",
        position_side="long",
        strike=Decimal(strike),
        expiry=date(2026, 5, 15),
        bid=Decimal("4.20"),
        ask=Decimal("4.60"),
        mid=Decimal("4.40"),
        volume=180,
        open_interest=420,
        implied_volatility=Decimal("0.38"),
        delta=Decimal("-0.48"),
        source="alpaca",
    )
    return ContractScoreResult(
        strategy=contract.strategy,
        contract=contract,
        base_score=score,
        score=0 if rejection_reason is not None else score,
        factors=(),
        penalties=(),
        vetoes=()
        if rejection_reason is None
        else (HardVeto("fixture_rejection", rejection_reason),),
        breakeven=Decimal(strike) - Decimal("4.60"),
        breakeven_move_percent=Decimal("0.05"),
        liquidity_score=82,
        expiry_days_after_earnings=7,
        reasons=("Liquid near-the-money put.",),
    )


def _market_snapshot(ticker: str) -> MarketSnapshot:
    returns = ReturnMetrics(
        one_day=Decimal("-0.01"),
        five_day=Decimal("-0.03"),
        twenty_day=Decimal("-0.06"),
        fifty_day=Decimal("-0.04"),
    )
    return MarketSnapshot(
        ticker=ticker,
        as_of_date=date(2026, 5, 1),
        company_name=f"{ticker} Corp.",
        sector="Consumer Defensive",
        sector_etf="XLP",
        market_cap=Decimal("250000000000"),
        current_price=Decimal("267"),
        latest_volume=1000000,
        average_volume_20d=Decimal("900000"),
        volume_vs_average_20d=Decimal("1.11"),
        stock_returns=returns,
        spy_returns=ReturnMetrics(
            one_day=Decimal("0.002"),
            five_day=Decimal("0.01"),
            twenty_day=Decimal("0.03"),
            fifty_day=Decimal("0.05"),
        ),
        qqq_returns=ReturnMetrics(
            one_day=Decimal("0.001"),
            five_day=Decimal("0.015"),
            twenty_day=Decimal("0.04"),
            fifty_day=Decimal("0.06"),
        ),
        sector_returns=ReturnMetrics(
            one_day=Decimal("0.001"),
            five_day=Decimal("0.004"),
            twenty_day=Decimal("0.02"),
            fifty_day=Decimal("0.03"),
        ),
        relative_strength_vs_spy=Decimal("-0.04"),
        relative_strength_vs_qqq=Decimal("-0.05"),
        relative_strength_vs_sector=Decimal("-0.03"),
        av_news_sentiment=None,
        price_source="fixture",
        overview_source="fixture",
        sources=("fixture",),
    )


def _news_bundle(ticker: str) -> NewsBundle:
    return NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        generated_at=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            neutral_contextual_evidence=["Staples peers held up better."],
            key_uncertainty="Guidance can still reset the setup.",
            summary=f"{ticker} saw softer traffic commentary going into earnings.",
            key_facts=[f"{ticker} traffic ran below internal plan over the past month."],
        ),
        used_ir_fallback=False,
        used_llm_summary=False,
    )


def _user_context() -> UserContext:
    return UserContext(
        account_size=Decimal("10000"),
        risk_profile="Balanced",
        strategy_permission="long_and_short",
        max_contracts=2,
    )
