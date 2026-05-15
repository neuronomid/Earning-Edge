from __future__ import annotations

from app.scoring.expiry import is_valid_expiry
from app.scoring.strategy_policy import NO_EARNINGS_REQUIRED_STRATEGIES, trade_policy_for
from app.scoring.types import (
    CandidateContext,
    ExitTarget,
    HardVeto,
    OptionContractInput,
    OptionRealityCheck,
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
    *,
    exit_target: ExitTarget | None = None,
    reality_check: OptionRealityCheck | None = None,
) -> tuple[HardVeto, ...]:
    vetoes: list[HardVeto] = []

    if (
        candidate.earnings_date is None
        and candidate.strategy_source not in NO_EARNINGS_REQUIRED_STRATEGIES
    ):
        vetoes.append(HardVeto("earnings_missing", "Earnings date is unavailable."))
    if candidate.earnings_date is not None and not candidate.verified_earnings_date:
        vetoes.append(HardVeto("earnings_unverified", "Earnings date cannot be verified."))
    if candidate.market_snapshot.current_price is None:
        vetoes.append(HardVeto("missing_current_price", "Current price is unavailable."))
    if not candidate.option_chain:
        vetoes.append(HardVeto("missing_option_chain", "Option chain unavailable."))
    if not is_valid_expiry(
        contract.expiry,
        candidate.earnings_date,
        candidate.earnings_timing,
        valuation_date=candidate.valuation_date or candidate.market_snapshot.as_of_date,
    ):
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

    policy = trade_policy_for(candidate.strategy_source)
    valuation_date = candidate.valuation_date or candidate.market_snapshot.as_of_date
    if valuation_date is not None:
        dte_calendar = max((contract.expiry - valuation_date).days, 0)
        if dte_calendar < policy.min_dte_calendar:
            vetoes.append(
                HardVeto(
                    "strategy_dte_too_short",
                    (
                        f"{candidate.strategy_source} requires at least "
                        f"{policy.min_dte_calendar} DTE for this contract type."
                    ),
                )
            )
        if dte_calendar > policy.max_dte_calendar:
            vetoes.append(
                HardVeto(
                    "strategy_dte_too_long",
                    (
                        f"{candidate.strategy_source} contracts must expire within "
                        f"{policy.max_dte_calendar} calendar days."
                    ),
                )
            )

    if spread is not None and spread > policy.max_spread_percent:
        vetoes.append(
            HardVeto(
                "strategy_spread_too_wide",
                "Bid/ask spread is too wide for this strategy's policy.",
            )
        )

    if reality_check is not None:
        if reality_check.trading_days_to_exit < policy.min_trading_days_to_exit:
            vetoes.append(
                HardVeto(
                    "strategy_exit_window_too_short",
                    (
                        f"{candidate.strategy_source} needs at least "
                        f"{policy.min_trading_days_to_exit} trading sessions to planned exit."
                    ),
                )
            )
        if (
            reality_check.required_sigma_to_target is not None
            and reality_check.required_sigma_to_target > policy.max_required_sigma_to_target
        ):
            vetoes.append(
                HardVeto(
                    "target_unreachable_by_exit",
                    "Target requires too large a move for the planned exit window.",
                )
            )
        if (
            reality_check.approx_probability_touch_target is not None
            and reality_check.approx_probability_touch_target < policy.min_target_touch_probability
        ):
            vetoes.append(
                HardVeto(
                    "low_pot_no_catalyst",
                    "Estimated target-touch probability is below the strategy floor.",
                )
            )
        if (
            not policy.allow_weeklies_without_named_catalyst
            and not reality_check.has_named_catalyst_before_exit
            and "weekly_otm_no_catalyst" in reality_check.flags
        ):
            vetoes.append(
                HardVeto(
                    "weekly_otm_no_catalyst",
                    "Short-dated OTM long option has no named catalyst before exit.",
                )
            )
        for flag in reality_check.flags:
            if flag in {
                "invalid_exit_session",
                "no_actionable_exit_window",
                "too_few_exit_sessions_no_catalyst",
                "breakeven_outside_exit_move",
                "missing_exit_horizon_move",
            }:
                vetoes.append(HardVeto(flag, _reality_flag_reason(flag)))

    if exit_target is not None and not exit_target.exit_is_trading_session:
        vetoes.append(
            HardVeto("invalid_exit_session", "Planned exit date is not a NYSE trading session.")
        )

    max_contracts = estimate_max_contracts(user, contract)
    if max_contracts <= 0:
        vetoes.append(HardVeto("zero_contracts", "User risk settings allow zero contracts."))

    if contract.position_side == "short" and user.strategy_permission == "long":
        vetoes.append(HardVeto("short_disabled", "Short options are disabled for this user."))
    if contract.position_side == "long" and user.strategy_permission == "short":
        vetoes.append(HardVeto("long_disabled", "Long options are disabled for this user."))

    return tuple(_dedupe_vetoes(vetoes))


def _reality_flag_reason(flag: str) -> str:
    return {
        "invalid_exit_session": "Planned exit date is not a NYSE trading session.",
        "no_actionable_exit_window": "There are no trading sessions before planned exit.",
        "too_few_exit_sessions_no_catalyst": (
            "No-catalyst long option has too few trading sessions to work."
        ),
        "breakeven_outside_exit_move": (
            "Breakeven sits outside the expected move for the planned exit window."
        ),
        "missing_exit_horizon_move": "Exit-horizon expected move could not be calculated.",
    }.get(flag, flag.replace("_", " "))


def _dedupe_vetoes(vetoes: list[HardVeto]) -> tuple[HardVeto, ...]:
    seen: set[str] = set()
    deduped: list[HardVeto] = []
    for veto in vetoes:
        if veto.code in seen:
            continue
        seen.add(veto.code)
        deduped.append(veto)
    return tuple(deduped)
