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
    ConfidenceBand,
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
from app.scoring.direction import structural_direction_tier
from app.scoring.final import combine_scores
from app.scoring.final import final_action as structural_action
from app.scoring.types import (
    ContractScoreResult,
    UserContext,
    breakeven_price,
    option_mid,
    spread_percent,
)
from app.services.market_hours import next_trading_session

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
    reference_dates = [
        item.context.valuation_date
        for item in candidates
        if item.context.valuation_date is not None
    ]
    reference_trading_date = min(reference_dates) if reference_dates else None
    return DecisionInput(
        user_strategy_permission=_strategy_permission(user.strategy_permission),
        risk_profile=user.risk_profile,
        account_size=user.account_size,
        reference_trading_date=reference_trading_date,
        next_market_session=None
        if reference_trading_date is None
        else next_trading_session(reference_trading_date),
        market_calendar_notes=[
            "All dates are NYSE/Eastern trading-session dates.",
            "Never recommend a contract with P0 reality_check_flags.",
        ],
        candidates=[_candidate_bundle(item) for item in candidates],
    )


def validate_llm_decision(
    candidates: Sequence[PipelineCandidate],
    decision: StructuredDecision,
) -> StructuredDecision:
    raw_response = decision.model_dump_json()

    nominated_band = _band_or_default(decision.confidence_band, decision.action)
    _validate_band_action_consistency(nominated_band, decision.action, raw_response=raw_response)

    if decision.action == "no_trade":
        normalized = decision.model_copy(
            update={
                "action": "no_trade",
                "confidence_band": "no_trade",
                "chosen_ticker": None,
                "chosen_contract": None,
                "contract_score": None,
                "final_score": None,
            }
        )
        watchlist = _sanitize_watchlist(
            candidates,
            decision.watchlist_tickers,
            exclude=decision.chosen_ticker,
        )
        if not watchlist:
            watchlist = _default_watchlist(candidates, exclude=None)
        return normalized.model_copy(update={"watchlist_tickers": watchlist})

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

    if _claims_impossible_runway(decision, matched_contract):
        reality = matched_contract.reality_check
        dte_calendar = reality.dte_calendar if reality is not None else None
        dte_text = f"{dte_calendar} calendar days" if dte_calendar is not None else "short-dated"
        raise LLMValidationError(
            (
                "Heavy model described a contract with "
                f"{dte_text} to expiry as long-dated or months of runway. "
                "Restate the rationale using the actual DTE and do not call it "
                "long-dated unless dte_calendar >= 45."
            ),
            raw_response=raw_response,
        )

    structural_final_score = combine_scores(
        candidate.evaluation.direction.score,
        matched_contract.score,
    )
    structural_band = _band_from_action(
        structural_action(
            structural_final_score,
            candidate.evaluation.confidence,
            matched_contract,
            direction_score=candidate.evaluation.direction.score,
        ),
        structural_final_score,
    )
    final_band = _min_band(nominated_band, structural_band)
    final_action = _action_for_band(final_band)

    normalized = decision.model_copy(
        update={
            "action": final_action,
            "confidence_band": final_band,
            "contract_score": matched_contract.score,
            "final_score": structural_final_score,
        }
    )

    blocking_flags = _blocking_reality_flags(matched_contract)
    if blocking_flags:
        normalized = normalized.model_copy(
            update={
                "action": "no_trade",
                "confidence_band": "no_trade",
                "reasoning": (
                    "Deterministic option reality checks blocked this contract: "
                    + ", ".join(blocking_flags)
                ),
                "key_concerns": list(dict.fromkeys([*decision.key_concerns, *blocking_flags])),
            }
        )

    if normalized.action == "no_trade":
        watchlist_seed = list(normalized.watchlist_tickers)
        if decision.chosen_ticker is not None and decision.chosen_ticker not in watchlist_seed:
            watchlist_seed.insert(0, decision.chosen_ticker)
        watchlist = _sanitize_watchlist(candidates, watchlist_seed, exclude=None)
        watchlist = _augment_with_catalyst_pending(candidates, watchlist, exclude=None)
        if not watchlist:
            watchlist = _default_watchlist(candidates, exclude=None)
        return normalized.model_copy(
            update={
                "chosen_ticker": None,
                "chosen_contract": None,
                "contract_score": None,
                "final_score": None,
                "watchlist_tickers": watchlist,
            }
        )
    watchlist = _sanitize_watchlist(
        candidates,
        normalized.watchlist_tickers,
        exclude=normalized.chosen_ticker,
    )
    watchlist = _augment_with_catalyst_pending(
        candidates, watchlist, exclude=normalized.chosen_ticker
    )

    if normalized.action == "watchlist" and _chosen_news_unavailable(candidates, normalized):
        normalized = normalized.model_copy(
            update={
                "key_concerns": _ensure_news_blackout_concern(normalized.key_concerns),
            }
        )

    return normalized.model_copy(update={"watchlist_tickers": watchlist})


def resolve_selected_contract(
    candidate: PipelineCandidate,
    chosen_contract: ChosenContract | None,
    *,
    visible_only: bool = False,
) -> ContractScoreResult | None:
    if chosen_contract is None:
        return candidate.evaluation.chosen_contract if not visible_only else None

    contracts = (
        candidate.evaluation.considered_contracts[:3]
        if visible_only
        else (candidate.evaluation.considered_contracts)
    )
    for contract in contracts:
        if _contract_matches(contract, chosen_contract):
            if visible_only and not contract.is_viable:
                return None
            return contract

    if visible_only:
        return None
    if candidate.evaluation.chosen_contract is not None and _contract_matches(
        candidate.evaluation.chosen_contract, chosen_contract
    ):
        return candidate.evaluation.chosen_contract
    return None


def _heuristic_decision(candidates: Sequence[PipelineCandidate]) -> StructuredDecision:
    if not candidates:
        return StructuredDecision(
            action="no_trade",
            confidence_band="no_trade",
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
            direction_tier=structural_direction_tier(best.evaluation.direction.score),
            confidence_band=_band_from_score(best.evaluation.final_score),
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
            direction_tier=structural_direction_tier(best.evaluation.direction.score),
            confidence_band="watchlist",
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
        confidence_band="no_trade",
        reasoning=_no_trade_reason(best),
        key_evidence=[],
        key_concerns=_key_concerns(best),
        watchlist_tickers=watchlist,
    )


def _candidate_bundle(candidate: PipelineCandidate) -> CandidateBundle:
    snapshot = candidate.context.market_snapshot
    viable_contracts = [
        contract for contract in candidate.evaluation.considered_contracts if contract.is_viable
    ]
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
        structural_direction_tier=structural_direction_tier(candidate.evaluation.direction.score),
        strategy_source=candidate.context.strategy_source,
        event_signal_detail=(
            candidate.context.event_signal.detail if candidate.context.event_signal else None
        ),
        news_coverage=candidate.news_bundle.news_coverage,
        stale_news=candidate.news_bundle.stale_news,
        news_article_count=len(candidate.news_bundle.articles),
        news_source_count=len(
            {
                result.source or result.url
                for result in candidate.news_bundle.search_results
            }
        ),
        news_status=_news_status(candidate),
        option_chain_candidates=[
            _option_chain_candidate(contract) for contract in viable_contracts[:3]
        ],
        tradeable_contracts_available=bool(viable_contracts),
        catalyst_pending_no_tradeable_contract=(
            not viable_contracts and _catalyst_pending_no_viable_contract(candidate)
        ),
        expected_move=candidate.context.expected_move_percent,
        previous_earnings_move=candidate.context.previous_earnings_move_percent,
        data_confidence_score=candidate.evaluation.confidence.score,
        rejected_contract_reasons=list(candidate.evaluation.reasons),
    )


def _option_chain_candidate(contract: ContractScoreResult) -> OptionChainCandidate:
    spread = spread_percent(contract.contract)
    target = contract.exit_target
    reality = contract.reality_check
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
        dte_calendar=None if reality is None else reality.dte_calendar,
        dte_trading_sessions=None if reality is None else reality.dte_trading_sessions,
        proposed_exit_by=None if target is None else target.exit_by_date,
        proposed_exit_is_trading_session=None
        if reality is None
        else reality.exit_is_trading_session,
        expected_holding_calendar_days=None
        if target is None
        else target.expected_holding_calendar_days,
        expected_holding_trading_days=None
        if target is None
        else target.expected_holding_trading_days,
        proposed_target_stock=None if target is None else target.target_stock_price,
        proposed_target_option=None if target is None else target.target_option_price,
        proposed_stop_option=None if target is None else target.stop_loss_option_price,
        target_method=None if target is None else target.target_method,
        required_sigma_to_target=None if reality is None else reality.required_sigma_to_target,
        required_sigma_to_breakeven=None
        if reality is None
        else reality.required_sigma_to_breakeven,
        approx_probability_touch_target=None
        if reality is None
        else reality.approx_probability_touch_target,
        approx_probability_expire_itm=None
        if reality is None
        else reality.approx_probability_expire_itm,
        theta_cost_to_exit=None if reality is None else reality.theta_cost_to_exit,
        has_named_catalyst_before_exit=bool(
            reality is not None and reality.has_named_catalyst_before_exit
        ),
        reality_check_flags=[] if reality is None else list(reality.flags),
    )


def _news_status(candidate: PipelineCandidate) -> str:
    uncertainty = candidate.news_bundle.brief.key_uncertainty.strip().lower()
    if uncertainty == "news service unavailable" or candidate.news_bundle.news_coverage == "none":
        return "unavailable"
    if "deferred" in uncertainty:
        return "deferred"
    return "available"


def _news_summary(candidate: PipelineCandidate) -> str:
    brief = candidate.news_bundle.brief
    parts = []
    if brief.summary:
        parts.append(f"Summary: {brief.summary}")
    if brief.key_facts:
        parts.append(f"Key facts: {'; '.join(brief.key_facts[:6])}")
    if brief.named_actions:
        parts.append(f"Named actions: {'; '.join(brief.named_actions[:4])}")
    if brief.quoted_statements:
        parts.append(f"Quotes: {'; '.join(brief.quoted_statements[:3])}")
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


_BAND_RANK: dict[ConfidenceBand, int] = {
    "no_trade": 0,
    "watchlist": 1,
    "standard": 2,
    "strong": 3,
}


def _band_from_score(score: int) -> ConfidenceBand:
    """Map a deterministic structural score to its confidence band."""
    if score >= 78:
        return "strong"
    if score >= 68:
        return "standard"
    if score >= 60:
        return "watchlist"
    return "no_trade"


def _action_for_band(band: ConfidenceBand) -> str:
    if band in ("strong", "standard"):
        return "recommend"
    if band == "watchlist":
        return "watchlist"
    return "no_trade"


def _band_from_action(action: str, score: int) -> ConfidenceBand:
    if action == "recommend":
        return _band_from_score(score)
    if action == "watchlist":
        return "watchlist"
    return "no_trade"


def _band_or_default(band: ConfidenceBand | None, action: str) -> ConfidenceBand:
    """Best-effort fallback when the LLM omits confidence_band."""
    if band is not None:
        return band
    if action == "recommend":
        return "standard"
    if action == "watchlist":
        return "watchlist"
    return "no_trade"


def _min_band(a: ConfidenceBand, b: ConfidenceBand) -> ConfidenceBand:
    return a if _BAND_RANK[a] <= _BAND_RANK[b] else b


def _validate_band_action_consistency(
    band: ConfidenceBand,
    action: str,
    *,
    raw_response: str | None,
) -> None:
    expected = _action_for_band(band)
    if expected != action:
        raise LLMValidationError(
            f"Heavy model confidence_band {band!r} does not match action {action!r} "
            f"(expected action {expected!r}).",
            raw_response=raw_response,
        )


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


def _build_corrective_prompt(
    *,
    base_prompt: str,
    error_message: str,
    raw_response: str | None,
) -> str:
    response_block = "(no parsed JSON available)" if not raw_response else raw_response
    targeted_hint = _targeted_retry_hint(error_message)
    targeted_block = f"\n{targeted_hint}\n" if targeted_hint else ""
    return (
        f"{base_prompt}\n\n"
        "## Retry context\n\n"
        "Your previous response was rejected by the validator. Re-read the\n"
        "Hard Rules above carefully and produce a corrected JSON response\n"
        "that satisfies them — do not repeat the same mistake.\n\n"
        f"Validator error: {error_message}\n"
        f"{targeted_block}"
        f"\nPrevious response (rejected):\n{response_block}"
    )


def _targeted_retry_hint(error_message: str) -> str | None:
    lowered = error_message.lower()
    if (
        "long-dated" in lowered
        or "long dated" in lowered
        or "months of runway" in lowered
        or "month of runway" in lowered
    ):
        return (
            "Targeted hint: drop every phrase like 'long-dated', 'long runway', "
            "or 'months/month of runway' from your rationale and key_evidence. "
            "Quote the contract's actual `dte_calendar` value verbatim. Only "
            "use long-dated language if dte_calendar >= 45."
        )
    if "not present in option_chain_candidates" in lowered:
        return (
            "Targeted hint: only choose a contract whose ticker, option_type, "
            "position_side, strike, and expiry match a row in this candidate's "
            "`option_chain_candidates` list exactly."
        )
    if "confidence_band" in lowered and "does not match action" in lowered:
        return (
            "Targeted hint: confidence_band ∈ {strong, standard} requires "
            "action='recommend'; 'watchlist' requires action='watchlist'; "
            "'no_trade' requires action='no_trade'. Keep them aligned."
        )
    return None


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
    return [item.record.ticker for item in ranked if item.record.ticker != exclude][:3]


_CATALYST_WINDOW_DAYS = 14
_NEWS_BLACKOUT_PHRASES = (
    "news service unavailable",
    "news_status=unavailable",
    "news unavailable",
    "news blackout",
    "news dark",
    "news_status unavailable",
    "no news coverage",
    "news coverage unavailable",
)
_NEWS_BLACKOUT_CONCERN = (
    "Downgraded to watchlist because news_status=unavailable for the selected setup."
)


def _augment_with_catalyst_pending(
    candidates: Sequence[PipelineCandidate],
    watchlist: list[str],
    *,
    exclude: str | None,
) -> list[str]:
    """Fill empty watchlist slots with catalyst-pending candidates that had no tradable contract.

    NVDA-style outcomes — earnings inside the next two weeks, no contract cleared
    the hard filters this scan — should not silently disappear from the watchlist
    behind score-0 noise. The LLM gets first dibs; this only seeds the slots it
    left open.
    """
    if len(watchlist) >= 3:
        return watchlist[:3]
    existing = set(watchlist)
    extras: list[tuple[int, str]] = []
    for item in candidates:
        ticker = item.record.ticker
        if not ticker or ticker == exclude or ticker in existing:
            continue
        if not _catalyst_pending_no_viable_contract(item):
            continue
        confidence = item.evaluation.confidence.score
        extras.append((confidence, ticker))
    extras.sort(reverse=True)
    augmented = list(watchlist)
    for _, ticker in extras:
        if len(augmented) >= 3:
            break
        augmented.append(ticker)
    return augmented


def _catalyst_pending_no_viable_contract(item: PipelineCandidate) -> bool:
    has_viable = any(
        contract.is_viable for contract in item.evaluation.considered_contracts
    )
    if has_viable:
        return False

    valuation_date = item.context.valuation_date or item.context.market_snapshot.as_of_date
    earnings_date = item.record.earnings_date or item.context.earnings_date
    if earnings_date is not None and valuation_date is not None:
        delta_days = (earnings_date - valuation_date).days
        if 0 <= delta_days <= _CATALYST_WINDOW_DAYS:
            return True
    event = item.context.event_signal
    return bool(event is not None and event.is_supportive)


def _chosen_news_unavailable(
    candidates: Sequence[PipelineCandidate],
    decision: StructuredDecision,
) -> bool:
    if decision.chosen_ticker is None:
        return False
    candidate = next(
        (item for item in candidates if item.record.ticker == decision.chosen_ticker),
        None,
    )
    if candidate is None:
        return False
    return _news_status(candidate) == "unavailable"


def _ensure_news_blackout_concern(concerns: Sequence[str]) -> list[str]:
    concerns_list = list(concerns)
    haystack = " ".join(concern.lower() for concern in concerns_list)
    if any(phrase in haystack for phrase in _NEWS_BLACKOUT_PHRASES):
        return concerns_list
    return [_NEWS_BLACKOUT_CONCERN, *concerns_list]


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


def _blocking_reality_flags(contract: ContractScoreResult) -> tuple[str, ...]:
    hard_codes = {veto.code for veto in contract.vetoes}
    reality_flags = set(contract.reality_check.flags if contract.reality_check else ())
    return tuple(
        sorted(
            hard_codes
            | {
                flag
                for flag in reality_flags
                if flag
                in {
                    "invalid_exit_session",
                    "no_actionable_exit_window",
                    "weekly_otm_no_catalyst",
                    "too_few_exit_sessions_no_catalyst",
                    "target_unreachable_by_exit",
                    "low_pot_no_catalyst",
                    "breakeven_outside_exit_move",
                    "missing_exit_horizon_move",
                }
            }
        )
    )


def _claims_impossible_runway(
    decision: StructuredDecision,
    contract: ContractScoreResult,
) -> bool:
    reality = contract.reality_check
    dte = None if reality is None else reality.dte_calendar
    if dte is None or dte >= 45:
        return False
    text = " ".join(
        part
        for part in (
            decision.reasoning,
            decision.rationale,
            None if decision.chosen_contract is None else decision.chosen_contract.rationale,
            " ".join(decision.key_evidence),
        )
        if part
    ).lower()
    return any(
        phrase in text
        for phrase in (
            "months of runway",
            "month of runway",
            "long-dated",
            "long dated",
            "six months",
            "6 months",
        )
    )


def _llm_blocked_decision(error: str) -> StructuredDecision:
    return StructuredDecision(
        action="no_trade",
        confidence_band="no_trade",
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
