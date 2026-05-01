from __future__ import annotations

from decimal import Decimal

from app.scoring.expiry import score_expiry_fit
from app.scoring.types import (
    CandidateContext,
    DirectionResult,
    OptionContractInput,
    SoftPenalty,
    UserContext,
    absolute_spread,
    option_premium,
    preferred_absolute_spread_limit,
    spread_percent,
)


def collect_soft_penalties(
    candidate: CandidateContext,
    user: UserContext,
    contract: OptionContractInput,
    direction: DirectionResult,
) -> tuple[SoftPenalty, ...]:
    penalties: list[SoftPenalty] = []

    if candidate.news_brief.bullish_evidence and candidate.news_brief.bearish_evidence:
        penalties.append(
            SoftPenalty(
                "mixed_news",
                "News flow was mixed rather than one-way.",
                -8 if candidate.news_brief.news_confidence < 60 else -5,
            )
        )

    sector_returns = candidate.market_snapshot.sector_returns
    if sector_returns is not None and sector_returns.five_day is not None:
        aligned = sector_returns.five_day
        if direction.classification == "bearish":
            aligned = -aligned
        if aligned < 0:
            penalties.append(
                SoftPenalty(
                    "weak_sector_trend",
                    "Sector trend does not fully support the thesis.",
                    -8 if abs(sector_returns.five_day) >= Decimal("0.03") else -3,
                )
            )

    if (contract.volume or 0) < 20 and (contract.open_interest or 0) >= 50:
        penalties.append(
            SoftPenalty(
                "light_volume",
                "Same-day volume is light even though open interest is acceptable.",
                -5,
            )
        )

    premium = option_premium(contract)
    spread = spread_percent(contract)
    abs_spread = absolute_spread(contract)
    spread_limit = preferred_absolute_spread_limit(premium)
    if spread is not None:
        if Decimal("0.25") < spread <= Decimal("0.35"):
            penalties.append(
                SoftPenalty(
                    "wide_spread",
                    "Spread is wide enough to demand a material price concession.",
                    -12,
                )
            )
        elif spread > Decimal("0.15"):
            penalties.append(
                SoftPenalty(
                    "moderate_spread",
                    "Spread is wider than ideal but still usable.",
                    -5,
                )
            )
    elif abs_spread is not None and abs_spread > spread_limit:
        penalties.append(
            SoftPenalty(
                "wide_absolute_spread",
                "Absolute spread is wide for the contract's premium band.",
                -5,
            )
        )

    if contract.implied_volatility is not None:
        if contract.position_side == "long":
            if contract.implied_volatility >= Decimal("0.80"):
                penalties.append(
                    SoftPenalty(
                        "elevated_iv",
                        "IV is very elevated for a long option.",
                        -15,
                    )
                )
            elif contract.implied_volatility >= Decimal("0.60"):
                penalties.append(
                    SoftPenalty(
                        "rich_iv",
                        "IV is elevated for a long option.",
                        -5,
                    )
                )
        else:
            if contract.implied_volatility < Decimal("0.30"):
                penalties.append(
                    SoftPenalty(
                        "thin_iv",
                        "IV is too low to justify the short premium setup.",
                        -10,
                    )
                )
            elif contract.implied_volatility < Decimal("0.45"):
                penalties.append(
                    SoftPenalty(
                        "soft_iv",
                        "IV is only modest for the short premium setup.",
                        -5,
                    )
                )

    expiry_fit = score_expiry_fit(
        contract.expiry,
        candidate.earnings_date,
        candidate.earnings_timing,
        contract.strategy,
        user.risk_profile,
    )
    if 0 < expiry_fit < 10:
        penalties.append(
            SoftPenalty(
                "expiry_less_ideal",
                "Expiry is valid but sits outside the preferred window.",
                -8 if expiry_fit <= 6 else -3,
            )
        )

    if (
        candidate.previous_earnings_move_percent is not None
        and candidate.expected_move_percent is not None
        and abs(candidate.previous_earnings_move_percent)
        < abs(candidate.expected_move_percent) * Decimal("0.75")
    ):
        penalties.append(
            SoftPenalty(
                "inconsistent_history",
                "Previous earnings reactions have been smaller than the current implied move.",
                -5,
            )
        )

    return tuple(penalties)

