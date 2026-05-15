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
    ExitTarget,
    HardVeto,
    OptionContractInput,
    OptionRealityCheck,
    StrategySelection,
    UserContext,
)
from app.services.candidate_models import CandidateRecord, StrategyEventSignal
from app.services.market_data.types import MarketSnapshot, ReturnMetrics
from app.services.news.types import NewsArticle, NewsBrief, NewsBundle

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


async def test_decision_payload_contains_exit_plan_and_reality_metrics() -> None:
    candidate = _candidate_with_reality_metrics()

    decision_input = build_decision_input([candidate], _user_context())
    bundle = decision_input.candidates[0]
    option = bundle.option_chain_candidates[0]

    assert decision_input.reference_trading_date == date(2026, 5, 14)
    assert option.dte_calendar == 8
    assert option.proposed_exit_by == date(2026, 5, 15)
    assert option.proposed_exit_is_trading_session is True
    assert option.expected_holding_trading_days == 1
    assert option.proposed_target_stock == Decimal("194.34")
    assert option.required_sigma_to_target == Decimal("0.75")
    assert option.approx_probability_touch_target == Decimal("0.4533")
    assert option.reality_check_flags == []


async def test_llm_cannot_claim_months_of_runway_for_7_dte_contract() -> None:
    candidate = _candidate_with_reality_metrics(dte_calendar=7)
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="The May 2026 195 call gives about 6 months of runway.",
                ),
                confidence_band="standard",
                reasoning="PM has momentum and this long-dated call has months of runway.",
                key_evidence=["6 months of runway."],
                key_concerns=[],
            )
        )
    )

    result = await step.execute([candidate], _user_context(), openrouter_api_key="sk-or-test")

    assert result.trace.engine == "heuristic_fallback"
    assert result.decision.action in {"recommend", "watchlist"}
    assert "failed" in result.trace.notes[0].lower()


async def test_watchlist_with_news_unavailable_gets_blackout_concern_injected() -> None:
    """If the LLM downgrades to watchlist while news_status=unavailable, the
    validator must ensure key_concerns names the news blackout so the audit
    trail explains the downgrade without relying on the freeform reasoning
    field. This guards against silent fail-closed behaviour the user can't
    see in the Telegram card."""
    candidate = _candidate_with_reality_metrics()
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="watchlist",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="Strong setup but liquidity is thin.",
                ),
                confidence_band="watchlist",
                reasoning="Wait for better news visibility before sizing.",
                key_evidence=["Sector tailwind holds."],
                # NOTE: deliberately omits any news-related concern.
                key_concerns=["Thin liquidity."],
            )
        )
    )

    result = await step.execute([candidate], _user_context(), openrouter_api_key="sk-or-test")

    assert result.decision.action == "watchlist"
    concerns_lc = " ".join(result.decision.key_concerns).lower()
    assert "news" in concerns_lc and "unavailable" in concerns_lc, (
        f"news-blackout concern missing from {result.decision.key_concerns!r}"
    )


async def test_watchlist_with_raw_extractive_news_does_not_inject_blackout_concern() -> None:
    """When the summarizer fell back to raw_extractive but real articles exist,
    news_status must be 'available' and the validator must NOT inject a
    blackout concern. This is the FLNC class of bug: a flaky summary model
    should not masquerade as a news blackout when the article evidence is in
    the bundle."""
    candidate = _candidate_with_reality_metrics()
    bundle = _news_bundle_with_articles(
        "PM", article_count=6, brief_status="raw_extractive"
    )
    candidate = replace(candidate, news_bundle=bundle)
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="watchlist",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="Setup is clean; staying watchlist for liquidity.",
                ),
                confidence_band="watchlist",
                reasoning="Wait for the spread to tighten before sizing.",
                key_evidence=["Trend intact."],
                key_concerns=["Spread is wide."],
            )
        )
    )

    result = await step.execute([candidate], _user_context(), openrouter_api_key="sk-or-test")

    assert result.decision.action == "watchlist"
    concerns_lc = " ".join(result.decision.key_concerns).lower()
    assert "news_status=unavailable" not in concerns_lc, (
        f"news-blackout concern was injected when articles are present: "
        f"{result.decision.key_concerns!r}"
    )
    assert "news service unavailable" not in concerns_lc, (
        f"news-blackout concern was injected when articles are present: "
        f"{result.decision.key_concerns!r}"
    )


async def test_watchlist_with_news_unavailable_preserves_existing_blackout_concern() -> None:
    """If the LLM already named the news blackout, the validator should not
    duplicate the concern."""
    candidate = _candidate_with_reality_metrics()
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="watchlist",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="Setup is clean but news is dark.",
                ),
                confidence_band="watchlist",
                reasoning="Holding off because we cannot independently verify the news.",
                key_evidence=["RS positive."],
                key_concerns=["news_status=unavailable — cannot confirm thesis."],
            )
        )
    )

    result = await step.execute([candidate], _user_context(), openrouter_api_key="sk-or-test")

    matching = [
        concern
        for concern in result.decision.key_concerns
        if (
            "news_status=unavailable" in concern.lower()
            or "news service unavailable" in concern.lower()
        )
    ]
    # exactly one — the user's own, not duplicated by the injector
    assert len(matching) == 1, result.decision.key_concerns


async def test_catalyst_pending_no_contract_ticker_lands_on_watchlist() -> None:
    """NVDA-style: real earnings catalyst inside 14 days, but every contract
    was killed by the deterministic filters. The validator's watchlist seed
    should keep that ticker visible even when the LLM omitted it."""
    catalyst_only = _catalyst_pending_candidate("NVDA")
    actionable = _candidate_with_reality_metrics()
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="watchlist",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="ATM call, sector tailwind.",
                ),
                confidence_band="watchlist",
                reasoning="Cleanest setup of the four candidates.",
                key_evidence=["XLP +4.4% (4w)."],
                key_concerns=["news_status=unavailable."],
                watchlist_tickers=[],  # LLM left every slot empty
            )
        )
    )

    result = await step.execute(
        [actionable, catalyst_only],
        _user_context(),
        openrouter_api_key="sk-or-test",
    )

    assert "NVDA" in result.decision.watchlist_tickers, (
        result.decision.watchlist_tickers,
    )


async def test_bundle_marks_catalyst_pending_no_tradeable_contract() -> None:
    """The LLM payload must surface the `catalyst_pending_no_tradeable_contract`
    flag so the model can include the ticker on its watchlist explicitly."""
    catalyst_only = _catalyst_pending_candidate("NVDA")
    decision_input = build_decision_input([catalyst_only], _user_context())
    bundle = decision_input.candidates[0]
    assert bundle.tradeable_contracts_available is False
    assert bundle.catalyst_pending_no_tradeable_contract is True


async def test_corrective_prompt_includes_targeted_hint_for_runway_violation() -> None:
    """The retry prompt should call the runway phrase out specifically so the
    second attempt does not silently repeat the same wording."""
    from app.pipeline.steps.decide import _build_corrective_prompt

    prompt = _build_corrective_prompt(
        base_prompt="<base prompt>",
        error_message=(
            "Heavy model described a contract with 7 calendar days to expiry as "
            "long-dated or months of runway."
        ),
        raw_response='{"reasoning":"6 months of runway"}',
    )
    assert "Targeted hint" in prompt
    assert "long-dated" in prompt.lower()
    assert "dte_calendar" in prompt


async def test_corrective_prompt_includes_targeted_hint_for_unknown_contract() -> None:
    from app.pipeline.steps.decide import _build_corrective_prompt

    prompt = _build_corrective_prompt(
        base_prompt="<base prompt>",
        error_message=(
            "Heavy model selected a contract that was not present in "
            "option_chain_candidates."
        ),
        raw_response=None,
    )
    assert "option_chain_candidates" in prompt
    assert "Targeted hint" in prompt


def _catalyst_pending_candidate(ticker: str) -> PipelineCandidate:
    """A finalist whose only contract was blocked by the deterministic gates,
    but whose earnings sits inside the next 14 days."""
    contract = OptionContractInput(
        ticker=ticker,
        option_type="put",
        position_side="short",
        strike=Decimal("235"),
        expiry=date(2026, 5, 15),
        bid=Decimal("0.50"),
        ask=Decimal("0.80"),
        mid=Decimal("0.65"),
        volume=10,
        open_interest=50,
        implied_volatility=Decimal("0.62"),
        delta=Decimal("-0.18"),
        source="fixture",
    )
    blocked = ContractScoreResult(
        strategy=contract.strategy,
        contract=contract,
        base_score=0,
        score=0,
        factors=(),
        penalties=(),
        vetoes=(HardVeto("invalid_exit_session", "Exit date is not a session."),),
        breakeven=None,
        breakeven_move_percent=None,
        liquidity_score=40,
        expiry_days_after_earnings=None,
        reasons=("Same-day exit, killed by reality gate.",),
    )
    bundle = NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        generated_at=datetime(2026, 5, 15, 0, 0, 0, tzinfo=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            neutral_contextual_evidence=[],
            key_uncertainty="news service unavailable",
        ),
        news_coverage="none",
        stale_news=True,
    )
    return PipelineCandidate(
        record=CandidateRecord(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            market_cap=Decimal("5000000000000"),
            earnings_date=date(2026, 5, 20),
            current_price=Decimal("235"),
            screener_rank=1,
            sector="Technology",
            strategy_source="catalyst_confluence",
        ),
        context=CandidateContext(
            ticker=ticker,
            company_name=f"{ticker} Corp.",
            earnings_date=date(2026, 5, 20),
            earnings_timing="AMC",
            market_snapshot=_market_snapshot(ticker),
            news_brief=bundle.brief,
            valuation_date=date(2026, 5, 14),
            option_chain=(contract,),
            strategy_source="catalyst_confluence",
        ),
        evaluation=CandidateEvaluation(
            ticker=ticker,
            direction=DirectionResult(
                classification="bullish",
                bias=Decimal("0.74"),
                score=72,
                factors=(),
                reasons=(f"{ticker} momentum is constructive.",),
            ),
            confidence=DataConfidenceResult(
                score=97,
                label="excellent",
                blockers=(),
                notes=(),
            ),
            strategy_selection=StrategySelection(
                allowed_strategies=("short_put",),
                preferred_order=("short_put",),
                reason="Fixture",
            ),
            considered_contracts=(blocked,),
            chosen_contract=None,
            final_score=0,
            action="no_trade",
            reasons=("All contracts blocked by reality gates.",),
        ),
        news_bundle=bundle,
        sizing=None,
    )


async def test_llm_selected_contract_with_p0_reality_flag_forces_no_trade() -> None:
    candidate = _candidate_with_reality_metrics(flags=("weekly_otm_no_catalyst",))
    step = LLMDecisionStep(
        router=StubRouter(
            decision=StructuredDecision(
                action="recommend",
                chosen_ticker="PM",
                chosen_contract=ChosenContract(
                    ticker="PM",
                    option_type="call",
                    position_side="long",
                    strike=Decimal("195"),
                    expiry=date(2026, 5, 22),
                    rationale="Momentum is strong.",
                ),
                confidence_band="standard",
                reasoning="Momentum is strong.",
                key_evidence=["Relative strength stayed positive."],
                key_concerns=[],
            )
        )
    )

    result = await step.execute([candidate], _user_context(), openrouter_api_key="sk-or-test")

    assert result.trace.engine == "llm"
    assert result.decision.action == "no_trade"
    assert result.decision.chosen_ticker is None
    assert "weekly_otm_no_catalyst" in result.decision.reasoning


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


def _candidate_with_reality_metrics(
    *,
    dte_calendar: int = 8,
    flags: tuple[str, ...] = (),
) -> PipelineCandidate:
    contract = OptionContractInput(
        ticker="PM",
        option_type="call",
        position_side="long",
        strike=Decimal("195"),
        expiry=date(2026, 5, 22),
        bid=Decimal("1.73"),
        ask=Decimal("1.98"),
        mid=Decimal("1.855"),
        volume=144,
        open_interest=300,
        implied_volatility=Decimal("0.2735"),
        delta=Decimal("0.359"),
        source="fixture",
    )
    exit_target = ExitTarget(
        target_stock_price=Decimal("194.34"),
        target_option_price=Decimal("2.38"),
        target_gain_percent=Decimal("20.20"),
        stop_loss_option_price=Decimal("0.99"),
        exit_by_date=date(2026, 5, 15),
        expected_holding_days=1,
        target_method="delta_fallback",
        expected_holding_trading_days=1,
        expected_holding_calendar_days=1,
        exit_is_trading_session=True,
        expected_move_to_exit_percent=Decimal("0.017229"),
    )
    reality = OptionRealityCheck(
        dte_calendar=dte_calendar,
        dte_trading_sessions=6,
        trading_days_to_exit=1,
        exit_is_trading_session=True,
        expected_move_to_exit_percent=Decimal("0.017229"),
        required_sigma_to_strike=Decimal("0.92"),
        required_sigma_to_breakeven=Decimal("1.55"),
        required_sigma_to_target=Decimal("0.75"),
        approx_probability_touch_target=Decimal("0.4533"),
        approx_probability_expire_itm=Decimal("0.3590"),
        theta_cost_to_exit=Decimal("0.1881"),
        has_named_catalyst_before_exit=False,
        flags=flags,
    )
    result = ContractScoreResult(
        strategy=contract.strategy,
        contract=contract,
        base_score=76,
        score=76,
        factors=(),
        penalties=(),
        vetoes=(),
        breakeven=Decimal("196.98"),
        breakeven_move_percent=Decimal("0.0267"),
        liquidity_score=82,
        expiry_days_after_earnings=None,
        reasons=("Fixture PM contract.",),
        exit_target=exit_target,
        reality_check=reality,
    )
    signal = StrategyEventSignal(
        score=75,
        is_supportive=True,
        detail="XLP sector +4.4% (4w), stock screen percentile 60%",
    )
    bundle = NewsBundle(
        ticker="PM",
        company_name="Philip Morris International",
        generated_at=datetime(2026, 5, 15, 0, 7, 46, tzinfo=UTC),
        search_results=(),
        articles=(),
        brief=NewsBrief(
            neutral_contextual_evidence=[],
            key_uncertainty="news service unavailable",
        ),
        news_coverage="none",
        stale_news=True,
    )
    return PipelineCandidate(
        record=CandidateRecord(
            ticker="PM",
            company_name="Philip Morris International",
            market_cap=Decimal("299030000000"),
            earnings_date=None,
            current_price=Decimal("191.86"),
            strategy_source="sector_relative_strength",
            event_signal=signal,
        ),
        context=CandidateContext(
            ticker="PM",
            company_name="Philip Morris International",
            earnings_date=None,
            earnings_timing="unknown",
            market_snapshot=MarketSnapshot(
                ticker="PM",
                as_of_date=date(2026, 5, 14),
                company_name="Philip Morris International",
                sector="Consumer Defensive",
                sector_etf="XLP",
                market_cap=Decimal("299030000000"),
                current_price=Decimal("191.86"),
                latest_volume=1000000,
                average_volume_20d=Decimal("900000"),
                volume_vs_average_20d=Decimal("1.11"),
                stock_returns=ReturnMetrics(
                    one_day=Decimal("0.021"),
                    five_day=Decimal("0.044"),
                    twenty_day=Decimal("0.080"),
                    fifty_day=Decimal("0.120"),
                ),
                spy_returns=ReturnMetrics(None, None, None, None),
                qqq_returns=ReturnMetrics(None, None, None, None),
                sector_returns=None,
                relative_strength_vs_spy=Decimal("0.034"),
                relative_strength_vs_qqq=Decimal("0.040"),
                relative_strength_vs_sector=Decimal("0.010"),
                av_news_sentiment=None,
                price_source="fixture",
                overview_source="fixture",
                sources=("fixture",),
            ),
            news_brief=bundle.brief,
            valuation_date=date(2026, 5, 14),
            option_chain=(contract,),
            strategy_source="sector_relative_strength",
            event_signal=signal,
            expected_move_percent=Decimal("0.027889"),
        ),
        evaluation=CandidateEvaluation(
            ticker="PM",
            direction=DirectionResult(
                classification="bullish",
                bias=Decimal("0.65"),
                score=75,
                factors=(),
                reasons=("PM relative strength stayed positive.",),
            ),
            confidence=DataConfidenceResult(
                score=84,
                label="good",
                blockers=(),
                notes=(),
            ),
            strategy_selection=StrategySelection(
                allowed_strategies=("long_call",),
                preferred_order=("long_call",),
                reason="Fixture strategy order.",
            ),
            considered_contracts=(result,),
            chosen_contract=result,
            final_score=76,
            action="recommend",
            reasons=("Fixture PM candidate.",),
        ),
        news_bundle=bundle,
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


def _news_bundle_with_articles(
    ticker: str, *, article_count: int, brief_status: str = "ok"
) -> NewsBundle:
    """Bundle that actually carries article evidence — used to assert the
    raw_extractive fallback is treated as decision-grade news."""
    articles = tuple(
        NewsArticle(
            title=f"{ticker} headline {i}",
            url=f"https://example.com/{ticker.lower()}/{i}",
            snippet="",
            content="",
            source="example.com",
            published_at=datetime(2026, 5, 1, 12, 0, tzinfo=UTC),
        )
        for i in range(article_count)
    )
    coverage = "none" if article_count == 0 else (
        "rich" if article_count >= 3 else "sparse"
    )
    raw_facts = [
        f"{ticker} headline {i} — example.com (2026-05-01)"
        for i in range(article_count)
    ]
    brief = (
        NewsBrief(
            key_facts=raw_facts,
            neutral_contextual_evidence=[
                "Raw extractive brief built from fetched articles."
            ],
            key_uncertainty=(
                "Lightweight summary model unavailable; raw article headlines below."
            ),
        )
        if brief_status == "raw_extractive"
        else NewsBrief(
            summary=f"{ticker} fundamentals look stable.",
            key_facts=[],
            key_uncertainty="None notable.",
        )
    )
    return NewsBundle(
        ticker=ticker,
        company_name=f"{ticker} Corp.",
        generated_at=datetime(2026, 5, 1, 15, 55, tzinfo=UTC),
        search_results=(),
        articles=articles,
        brief=brief,
        used_ir_fallback=False,
        used_llm_summary=brief_status == "ok",
        news_coverage=coverage,
        brief_status=brief_status,  # type: ignore[arg-type]
    )


def _user_context() -> UserContext:
    return UserContext(
        account_size=Decimal("10000"),
        risk_profile="Balanced",
        strategy_permission="long_and_short",
        max_contracts=2,
    )
