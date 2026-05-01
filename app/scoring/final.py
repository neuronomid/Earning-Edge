from __future__ import annotations

from collections import defaultdict
from decimal import Decimal

from app.scoring.confidence import compute_data_confidence
from app.scoring.contract import score_contract
from app.scoring.direction import score_direction
from app.scoring.strategy_select import select_allowed_strategies
from app.scoring.strike import select_strike_candidates
from app.scoring.types import (
    CandidateContext,
    CandidateEvaluation,
    DataConfidenceResult,
    DecisionAction,
    UserContext,
    clamp_int,
)


def combine_scores(direction_score: int, contract_score: int) -> int:
    combined = (Decimal(direction_score) * Decimal("0.45")) + (
        Decimal(contract_score) * Decimal("0.55")
    )
    return clamp_int(int(combined.quantize(Decimal("1"))))


def score_candidate(candidate: CandidateContext, user: UserContext) -> CandidateEvaluation:
    provisional_confidence = compute_data_confidence(
        candidate,
        user,
        require_selected_contract=False,
    )
    direction = score_direction(candidate, data_confidence_score=provisional_confidence.score)
    strategy_selection = select_allowed_strategies(
        direction.classification,
        user.strategy_permission,
        direction_score=direction.score,
        option_chain=candidate.option_chain,
    )

    considered = []
    current_price = candidate.market_snapshot.current_price
    if current_price is not None:
        for strategy in strategy_selection.preferred_order:
            by_expiry = defaultdict(list)
            for contract in candidate.option_chain:
                if contract.strategy != strategy:
                    continue
                by_expiry[contract.expiry].append(contract)
            for expiry_contracts in by_expiry.values():
                strike_candidates = select_strike_candidates(
                    tuple(expiry_contracts),
                    current_price=current_price,
                    strategy=strategy,
                )
                for contract in strike_candidates:
                    considered.append(score_contract(candidate, user, contract, direction))

    considered_contracts = tuple(
        sorted(
            considered,
            key=lambda result: (
                result.score,
                result.liquidity_score,
                -(result.expiry_days_after_earnings or 0),
            ),
            reverse=True,
        )
    )
    chosen = next((result for result in considered_contracts if result.is_viable), None)

    final_confidence = compute_data_confidence(
        candidate,
        user,
        selected_contract=chosen.contract if chosen is not None else None,
        require_selected_contract=True,
    )

    final_score = combine_scores(direction.score, chosen.score) if chosen is not None else 0
    action = _final_action(final_score, final_confidence, chosen is not None)

    reasons = list(direction.reasons)
    if chosen is not None:
        reasons.append(
            f"best contract was {chosen.strategy} {chosen.contract.expiry.isoformat()} "
            f"{chosen.contract.strike}"
        )
        reasons.extend(penalty.reason for penalty in chosen.penalties)
        reasons.extend(veto.reason for veto in chosen.vetoes)
    reasons.extend(final_confidence.blockers)

    return CandidateEvaluation(
        ticker=candidate.ticker,
        direction=direction,
        confidence=final_confidence,
        strategy_selection=strategy_selection,
        considered_contracts=considered_contracts,
        chosen_contract=chosen,
        final_score=final_score,
        action=action,
        reasons=tuple(dict.fromkeys(reasons)),
    )


def _final_action(
    final_score: int, confidence: DataConfidenceResult, has_contract: bool
) -> DecisionAction:
    if not has_contract or confidence.blockers or confidence.score < 40:
        return "no_trade"
    if confidence.score < 55:
        return "watchlist" if final_score >= 60 else "no_trade"
    if final_score >= 68:
        return "recommend"
    if final_score >= 60:
        return "watchlist"
    return "no_trade"
