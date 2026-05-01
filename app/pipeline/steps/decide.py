from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import Protocol

from app.llm.schemas import (
    CandidateBundle,
    ChosenContract,
    DecisionInput,
    OptionChainCandidate,
    StructuredDecision,
)
from app.pipeline.types import PipelineCandidate
from app.scoring.types import (
    UserContext,
    breakeven_price,
    option_mid,
    spread_percent,
)

ZERO = Decimal("0")


class DecisionStep(Protocol):
    async def execute(
        self,
        candidates: Sequence[PipelineCandidate],
        user: UserContext,
    ) -> StructuredDecision: ...


class HeuristicDecisionStep:
    """Deterministic selector used until the LLM decision step is fully wired."""

    async def execute(
        self,
        candidates: Sequence[PipelineCandidate],
        user: UserContext,
    ) -> StructuredDecision:
        if not candidates:
            return StructuredDecision(
                action="no_trade",
                reasoning="No validated candidates were available for this scan.",
                key_concerns=["The candidate list came back empty."],
            )

        ranked = sorted(
            candidates,
            key=lambda item: (
                item.evaluation.final_score,
                item.evaluation.confidence.score,
                item.record.market_cap or ZERO,
            ),
            reverse=True,
        )
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
                        "Highest final score after the direction, contract, and confidence "
                        "checks."
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
                        "The setup cleared the watchlist bar, but not the live-sizing "
                        "threshold."
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
            reasoning=(
                "No trade cleared the minimum bar this time. The best setups still had weaker "
                "direction, pricing, liquidity, or data confidence than I want for an "
                "earnings hold."
            ),
            key_evidence=[],
            key_concerns=_key_concerns(best),
            watchlist_tickers=watchlist,
        )


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


def _option_chain_candidate(contract) -> OptionChainCandidate:
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
