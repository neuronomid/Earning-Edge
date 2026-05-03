from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.llm.router import LLMRouter
from app.llm.schemas import (
    CandidateBundle,
    ChosenContract,
    DecisionInput,
    OptionChainCandidate,
    StructuredDecision,
)
from app.llm.types import (
    LLMAuthenticationError,
    LLMError,
    LLMRateLimitError,
    LLMUnavailableError,
    LLMValidationError,
)
from app.pipeline.types import (
    DecisionStepResult,
    DecisionTrace,
    PipelineCandidate,
)
from app.scoring.types import (
    ContractScoreResult,
    UserContext,
    breakeven_price,
    option_mid,
    spread_percent,
)

ZERO = Decimal("0")
PROMPT_PATH = Path(__file__).resolve().parents[2] / "llm" / "prompts" / "decide_recommendation.md"


class DecisionStep(Protocol):
    async def execute(
        self,
        candidates: Sequence[PipelineCandidate],
        user: UserContext,
        *,
        openrouter_api_key: str,
    ) -> DecisionStepResult: ...


class HeuristicDecisionStep:
    """Deterministic selector used as the test default and runtime fallback."""

    async def execute(
        self,
        candidates: Sequence[PipelineCandidate],
        user: UserContext,
        *,
        openrouter_api_key: str,
    ) -> DecisionStepResult:
        del user
        del openrouter_api_key
        return DecisionStepResult(
            decision=_heuristic_decision(candidates),
            trace=DecisionTrace(engine="heuristic"),
        )


class LLMDecisionStep:
    def __init__(
        self,
        *,
        router: LLMRouter | None = None,
        fallback: HeuristicDecisionStep | None = None,
        system_prompt: str | None = None,
        logger: Any | None = None,
    ) -> None:
        self.router = router or LLMRouter()
        self.fallback = fallback or HeuristicDecisionStep()
        self.system_prompt = system_prompt or _decision_prompt()
        self.logger = logger or get_logger(__name__)

    async def execute(
        self,
        candidates: Sequence[PipelineCandidate],
        user: UserContext,
        *,
        openrouter_api_key: str,
    ) -> DecisionStepResult:
        fallback_result = await self.fallback.execute(
            candidates,
            user,
            openrouter_api_key=openrouter_api_key,
        )
        if not candidates:
            return fallback_result

        decision_input = build_decision_input(candidates, user)
        try:
            validated, retry_note = await self._decide_with_retry(
                candidates,
                decision_input,
                openrouter_api_key=openrouter_api_key,
            )
            return DecisionStepResult(
                decision=validated,
                trace=DecisionTrace(
                    engine="llm",
                    heavy_model_used=self.router.heavy_model,
                    notes=() if retry_note is None else (retry_note,),
                ),
            )
        except LLMAuthenticationError as exc:
            self.logger.warning("llm_decision_auth_failed", error=str(exc))
            return DecisionStepResult(
                decision=_llm_blocked_decision(str(exc)),
                trace=DecisionTrace(
                    engine="llm_blocked",
                    notes=(str(exc),),
                ),
            )
        except (
            LLMRateLimitError,
            LLMUnavailableError,
            LLMValidationError,
            LLMError,
            ValueError,
        ) as exc:
            self.logger.warning(
                "llm_decision_fallback",
                error=str(exc),
                raw_response=getattr(exc, "raw_response", None),
            )
            return DecisionStepResult(
                decision=fallback_result.decision,
                trace=DecisionTrace(
                    engine="heuristic_fallback",
                    notes=(f"Heavy-model decision failed: {exc}",),
                ),
            )

    async def _decide_with_retry(
        self,
        candidates: Sequence[PipelineCandidate],
        decision_input: DecisionInput,
        *,
        openrouter_api_key: str,
    ) -> tuple[StructuredDecision, str | None]:
        decision = await self.router.decide(
            api_key=openrouter_api_key,
            structured_input=decision_input,
            response_schema=StructuredDecision,
            system_prompt=self.system_prompt,
        )
        try:
            return validate_llm_decision(candidates, decision), None
        except LLMValidationError as exc:
            self.logger.warning(
                "llm_decision_invalid_retrying",
                error=str(exc),
                raw_response=exc.raw_response,
            )
            corrective_prompt = _build_corrective_prompt(
                base_prompt=self.system_prompt,
                error_message=str(exc),
                raw_response=exc.raw_response,
            )
            retry_decision = await self.router.decide(
                api_key=openrouter_api_key,
                structured_input=decision_input,
                response_schema=StructuredDecision,
                system_prompt=corrective_prompt,
            )
            validated = validate_llm_decision(candidates, retry_decision)
            return validated, f"Heavy-model retry succeeded after: {exc}"


def get_default_decision_step(*, settings: Settings | None = None) -> DecisionStep:
    resolved = settings or get_settings()
    if resolved.app_env == "test":
        return HeuristicDecisionStep()
    return LLMDecisionStep(router=LLMRouter(settings=resolved))


def build_decision_input(
    candidates: Sequence[PipelineCandidate],
    user: UserContext,
) -> DecisionInput:
    return DecisionInput(
        user_strategy_permission=_strategy_permission(user.strategy_permission),
        risk_profile=user.risk_profile,
        account_size=user.account_size,
        candidates=[_candidate_bundle(item) for item in candidates],
    )


def validate_llm_decision(
    candidates: Sequence[PipelineCandidate],
    decision: StructuredDecision,
) -> StructuredDecision:
    watchlist = _sanitize_watchlist(
        candidates,
        decision.watchlist_tickers,
        exclude=decision.chosen_ticker,
    )
    raw_response = decision.model_dump_json()
    _validate_action_thresholds(decision, raw_response=raw_response)

    if decision.action == "no_trade":
        if not watchlist:
            watchlist = _default_watchlist(candidates, exclude=None)
        return decision.model_copy(
            update={
                "chosen_ticker": None,
                "chosen_contract": None,
                "watchlist_tickers": watchlist,
            }
        )

    if decision.chosen_ticker is None or decision.chosen_contract is None:
        raise LLMValidationError(
            "Heavy model returned an actionable decision without a ticker and contract.",
            raw_response=raw_response,
        )

    if decision.chosen_contract.ticker != decision.chosen_ticker:
        raise LLMValidationError(
            "Heavy model returned mismatched ticker fields.",
            raw_response=raw_response,
        )

    candidate = next(
        (item for item in candidates if item.record.ticker == decision.chosen_ticker),
        None,
    )
    if candidate is None:
        raise LLMValidationError(
            f"Heavy model selected unknown ticker {decision.chosen_ticker!r}.",
            raw_response=raw_response,
        )

    matched_contract = resolve_selected_contract(
        candidate,
        decision.chosen_contract,
        visible_only=True,
    )
    if matched_contract is None:
        raise LLMValidationError(
            "Heavy model selected a contract that was not present in option_chain_candidates.",
            raw_response=raw_response,
        )

    return decision.model_copy(update={"watchlist_tickers": watchlist})


def resolve_selected_contract(
    candidate: PipelineCandidate,
    chosen_contract: ChosenContract | None,
    *,
    visible_only: bool = False,
) -> ContractScoreResult | None:
    if chosen_contract is None:
        return candidate.evaluation.chosen_contract if not visible_only else None

    contracts = candidate.evaluation.considered_contracts[:3] if visible_only else (
        candidate.evaluation.considered_contracts
    )
    for contract in contracts:
        if _contract_matches(contract, chosen_contract):
            return contract

    if visible_only:
        return None
    if (
        candidate.evaluation.chosen_contract is not None
        and _contract_matches(candidate.evaluation.chosen_contract, chosen_contract)
    ):
        return candidate.evaluation.chosen_contract
    return None


def _heuristic_decision(candidates: Sequence[PipelineCandidate]) -> StructuredDecision:
    if not candidates:
        return StructuredDecision(
            action="no_trade",
            reasoning="No validated candidates were available for this scan.",
            key_concerns=["The candidate list came back empty."],
        )

    ranked = _rank_candidates(candidates)
    best = ranked[0]
    watchlist = [item.record.ticker for item in ranked[:3]]

    if best.evaluation.action == "recommend" and best.evaluation.chosen_contract is not None:
        chosen = best.evaluation.chosen_contract
        return StructuredDecision(
            action="recommend",
            chosen_ticker=best.record.ticker,
            chosen_contract=ChosenContract(
                ticker=best.record.ticker,
                option_type=chosen.contract.option_type,
                position_side=chosen.contract.position_side,
                strike=chosen.contract.strike,
                expiry=chosen.contract.expiry,
                rationale=(
                    "Highest final score after the direction, contract, and confidence checks."
                ),
            ),
            direction_score=best.evaluation.direction.score,
            contract_score=chosen.score,
            final_score=best.evaluation.final_score,
            reasoning=_summarize_reasons(best),
            key_evidence=_key_evidence(best),
            key_concerns=_key_concerns(best),
            watchlist_tickers=watchlist,
        )

    if best.evaluation.action == "watchlist" and best.evaluation.chosen_contract is not None:
        chosen = best.evaluation.chosen_contract
        return StructuredDecision(
            action="watchlist",
            chosen_ticker=best.record.ticker,
            chosen_contract=ChosenContract(
                ticker=best.record.ticker,
                option_type=chosen.contract.option_type,
                position_side=chosen.contract.position_side,
                strike=chosen.contract.strike,
                expiry=chosen.contract.expiry,
                rationale=(
                    "The setup cleared the watchlist bar, but not the live-sizing threshold."
                ),
            ),
            direction_score=best.evaluation.direction.score,
            contract_score=chosen.score,
            final_score=best.evaluation.final_score,
            reasoning=(
                "This setup is interesting enough to monitor, but it still needs a cleaner "
                "mix of pricing, liquidity, or confidence before it becomes a full "
                "recommendation."
            ),
            key_evidence=_key_evidence(best),
            key_concerns=_key_concerns(best),
            watchlist_tickers=watchlist,
        )

    return StructuredDecision(
        action="no_trade",
        reasoning=_no_trade_reason(best),
        key_evidence=[],
        key_concerns=_key_concerns(best),
        watchlist_tickers=watchlist,
    )


def _candidate_bundle(candidate: PipelineCandidate) -> CandidateBundle:
    snapshot = candidate.context.market_snapshot
    return CandidateBundle(
        ticker=candidate.record.ticker,
        company_name=candidate.record.company_name or candidate.context.company_name,
        earnings_date=candidate.context.earnings_date,
        earnings_timing=candidate.context.earnings_timing,
        market_cap=candidate.record.market_cap or snapshot.market_cap,
        current_price=snapshot.current_price,
        recent_returns={
            "1d": _decimal_to_float(snapshot.stock_returns.one_day),
            "5d": _decimal_to_float(snapshot.stock_returns.five_day),
            "20d": _decimal_to_float(snapshot.stock_returns.twenty_day),
            "50d": _decimal_to_float(snapshot.stock_returns.fifty_day),
        },
        trend_indicators={
            "volume_vs_average_20d": _decimal_to_float(snapshot.volume_vs_average_20d),
            "relative_strength_vs_spy": _decimal_to_float(snapshot.relative_strength_vs_spy),
            "relative_strength_vs_sector": _decimal_to_float(snapshot.relative_strength_vs_sector),
        },
        sector_comparison={
            "sector_5d": _decimal_to_float(
                None if snapshot.sector_returns is None else snapshot.sector_returns.five_day
            ),
        },
        market_comparison={
            "spy_5d": _decimal_to_float(snapshot.spy_returns.five_day),
            "qqq_5d": _decimal_to_float(snapshot.qqq_returns.five_day),
        },
        news_summary=_news_summary(candidate),
        option_chain_candidates=[
            _option_chain_candidate(contract)
            for contract in candidate.evaluation.considered_contracts[:3]
        ],
        expected_move=candidate.context.expected_move_percent,
        previous_earnings_move=candidate.context.previous_earnings_move_percent,
        data_confidence_score=candidate.evaluation.confidence.score,
        rejected_contract_reasons=list(candidate.evaluation.reasons),
    )


def _option_chain_candidate(contract: ContractScoreResult) -> OptionChainCandidate:
    spread = spread_percent(contract.contract)
    return OptionChainCandidate(
        option_type=contract.contract.option_type,
        position_side=contract.contract.position_side,
        strike=contract.contract.strike,
        expiry=contract.contract.expiry,
        bid=contract.contract.bid,
        ask=contract.contract.ask,
        mid=option_mid(contract.contract),
        spread_percent=None if spread is None else spread * Decimal("100"),
        implied_volatility=contract.contract.implied_volatility,
        delta=contract.contract.delta,
        volume=contract.contract.volume,
        open_interest=contract.contract.open_interest,
        liquidity_score=contract.liquidity_score,
        breakeven=breakeven_price(contract.contract),
    )


def _news_summary(candidate: PipelineCandidate) -> str:
    brief = candidate.news_bundle.brief
    parts = []
    if brief.bullish_evidence:
        parts.append(f"Bullish: {'; '.join(brief.bullish_evidence[:2])}")
    if brief.bearish_evidence:
        parts.append(f"Bearish: {'; '.join(brief.bearish_evidence[:2])}")
    if brief.neutral_contextual_evidence:
        parts.append(f"Context: {'; '.join(brief.neutral_contextual_evidence[:2])}")
    parts.append(f"Uncertainty: {brief.key_uncertainty}")
    return " ".join(parts)


def _strategy_permission(value: str) -> str:
    if value == "long":
        return "long_only"
    if value == "short":
        return "short_only"
    return "long_and_short"


def _decimal_to_float(value: Decimal | None) -> float:
    return 0.0 if value is None else float(value)


def _summarize_reasons(candidate: PipelineCandidate) -> str:
    reasons = list(candidate.evaluation.reasons[:4])
    if not reasons:
        return "This setup had the strongest balance of trend, contract quality, and confidence."
    return " ".join(reasons)


def _key_evidence(candidate: PipelineCandidate) -> list[str]:
    evidence = list(candidate.evaluation.direction.reasons[:3])
    if candidate.evaluation.chosen_contract is not None:
        evidence.append(
            f"Best contract: {candidate.evaluation.chosen_contract.strategy} "
            f"{candidate.evaluation.chosen_contract.contract.expiry.isoformat()} "
            f"{candidate.evaluation.chosen_contract.contract.strike}"
        )
    return evidence[:4]


def _key_concerns(candidate: PipelineCandidate) -> list[str]:
    concerns = list(candidate.evaluation.confidence.blockers)
    concerns.extend(candidate.evaluation.confidence.notes)
    return concerns[:4]


def _no_trade_reason(candidate: PipelineCandidate) -> str:
    blockers = candidate.evaluation.confidence.blockers
    if blockers:
        return blockers[0]

    veto_reasons = [
        veto.reason
        for contract in candidate.evaluation.considered_contracts
        for veto in contract.vetoes
    ]
    if veto_reasons:
        return veto_reasons[0]

    if candidate.evaluation.reasons:
        return candidate.evaluation.reasons[0]

    return (
        "No trade cleared the minimum bar this time. The best setups still had weaker "
        "direction, pricing, liquidity, or data confidence than I want for an "
        "earnings hold."
    )


def _validate_action_thresholds(
    decision: StructuredDecision,
    *,
    raw_response: str | None = None,
) -> None:
    score = decision.final_score
    if decision.action == "recommend":
        if score is None or score < 68:
            raise LLMValidationError(
                "Heavy model returned recommend with final_score below 68.",
                raw_response=raw_response,
            )
        return
    if decision.action == "watchlist":
        if score is None or not 60 <= score <= 67:
            raise LLMValidationError(
                "Heavy model returned watchlist with final_score outside 60-67.",
                raw_response=raw_response,
            )
        return
    if score is not None and score >= 60:
        raise LLMValidationError(
            "Heavy model returned no_trade with final_score 60 or higher.",
            raw_response=raw_response,
        )


def _build_corrective_prompt(
    *,
    base_prompt: str,
    error_message: str,
    raw_response: str | None,
) -> str:
    response_block = (
        "(no parsed JSON available)" if not raw_response else raw_response
    )
    return (
        f"{base_prompt}\n\n"
        "## Retry context\n\n"
        "Your previous response was rejected by the validator. Re-read the\n"
        "Hard Rules above carefully and produce a corrected JSON response\n"
        "that satisfies them — do not repeat the same mistake.\n\n"
        f"Validator error: {error_message}\n\n"
        f"Previous response (rejected):\n{response_block}"
    )


def _sanitize_watchlist(
    candidates: Sequence[PipelineCandidate],
    requested: Sequence[str],
    *,
    exclude: str | None,
) -> list[str]:
    allowed = {item.record.ticker for item in candidates}
    ordered: list[str] = []
    for ticker in requested:
        if ticker not in allowed or ticker == exclude or ticker in ordered:
            continue
        ordered.append(ticker)
    return ordered[:3]


def _default_watchlist(
    candidates: Sequence[PipelineCandidate],
    *,
    exclude: str | None,
) -> list[str]:
    ranked = _rank_candidates(candidates)
    return [
        item.record.ticker
        for item in ranked
        if item.record.ticker != exclude
    ][:3]


def _rank_candidates(candidates: Sequence[PipelineCandidate]) -> list[PipelineCandidate]:
    return sorted(
        candidates,
        key=lambda item: (
            item.evaluation.final_score,
            item.evaluation.confidence.score,
            item.record.market_cap or ZERO,
        ),
        reverse=True,
    )


def _contract_matches(contract: ContractScoreResult, chosen_contract: ChosenContract) -> bool:
    return (
        contract.contract.ticker == chosen_contract.ticker
        and contract.contract.option_type == chosen_contract.option_type
        and contract.contract.position_side == chosen_contract.position_side
        and contract.contract.strike == chosen_contract.strike
        and contract.contract.expiry == chosen_contract.expiry
    )


def _llm_blocked_decision(error: str) -> StructuredDecision:
    return StructuredDecision(
        action="no_trade",
        reasoning=(
            "I could not run the final Opus decision step because the OpenRouter key is "
            "missing or invalid. Update the OpenRouter key in Telegram settings and rerun "
            "the scan."
        ),
        key_concerns=[error],
    )


@lru_cache(maxsize=1)
def _decision_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")
