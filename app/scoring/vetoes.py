from __future__ import annotations

from app.scoring.expiry import is_valid_expiry
from app.scoring.types import (
    CandidateContext,
    HardVeto,
    OptionContractInput,
    UserContext,
    absolute_spread,
    estimate_max_contracts,
    option_premium,
    preferred_absolute_spread_limit,
    spread_percent,
)


def evaluate_hard_vetoes(
    candidate: CandidateContext,
    user: UserContext,
    contract: OptionContractInput,
) -> tuple[HardVeto, ...]:
    vetoes: list[HardVeto] = []

    if not candidate.verified_earnings_date:
        vetoes.append(HardVeto("earnings_unverified", "Earnings date cannot be verified."))
    if candidate.market_snapshot.current_price is None:
        vetoes.append(HardVeto("missing_current_price", "Current price is unavailable."))
    if not candidate.option_chain:
        vetoes.append(HardVeto("missing_option_chain", "Option chain unavailable."))
    if not is_valid_expiry(contract.expiry, candidate.earnings_date, candidate.earnings_timing):
        vetoes.append(HardVeto("invalid_expiry", "Expiry is outside the valid earnings window."))

    premium = option_premium(contract)
    if contract.position_side == "long":
        if contract.ask is None or contract.ask <= 0:
            vetoes.append(HardVeto("missing_ask", "Ask quote is missing for a long option."))
    elif contract.bid is None or contract.bid <= 0:
        vetoes.append(HardVeto("missing_bid", "Bid quote is missing for a short option."))

    if premium is None:
        vetoes.append(HardVeto("missing_quote", "Usable bid/ask or mid pricing is unavailable."))

    if (contract.open_interest or 0) == 0 and (contract.volume or 0) == 0:
        vetoes.append(HardVeto("dead_contract", "Open interest and volume are both zero."))

    spread = spread_percent(contract)
    abs_spread = absolute_spread(contract)
    if spread is not None and spread > 0.35:
        cheap_contract = premium is not None and premium < 0.50
        spread_limit = preferred_absolute_spread_limit(premium)
        if not cheap_contract or abs_spread is None or abs_spread > spread_limit:
            vetoes.append(HardVeto("extreme_spread", "Bid/ask spread is extremely wide."))

    if contract.is_stale or not contract.is_tradable:
        vetoes.append(HardVeto("stale_contract", "Contract appears stale or not tradable."))

    max_contracts = estimate_max_contracts(user, contract)
    if max_contracts <= 0:
        vetoes.append(HardVeto("zero_contracts", "User risk settings allow zero contracts."))

    if contract.position_side == "short" and user.strategy_permission == "long":
        vetoes.append(HardVeto("short_disabled", "Short options are disabled for this user."))
    if contract.position_side == "long" and user.strategy_permission == "short":
        vetoes.append(HardVeto("long_disabled", "Long options are disabled for this user."))

    return tuple(vetoes)

