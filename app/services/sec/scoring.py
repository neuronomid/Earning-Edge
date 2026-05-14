from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# Known activist filer reputational tiers. Names are matched case-insensitively
# against the filer name; the highest tier whose pattern matches wins.
_KNOWN_FILER_TIERS: tuple[tuple[Decimal, tuple[str, ...]], ...] = (
    (
        Decimal("10"),
        (
            "elliott",
            "trian",
            "starboard",
            "icahn",
            "third point",
            "pershing square",
            "valueact",
        ),
    ),
    (
        Decimal("6"),
        (
            "engaged capital",
            "jana partners",
            "ancora",
            "blackwells",
            "voce capital",
        ),
    ),
)


@dataclass(slots=True, frozen=True)
class EventScoreInputs:
    stake_percent: Decimal | None
    active_intent: bool
    filing_date: date
    today: date
    filer_name: str | None
    rel_vol: Decimal | None
    price_confirmation_pct: Decimal | None
    option_liquidity_score: Decimal | None
    days_to_next_earnings: int | None
    gap_exhaustion_pct: Decimal | None
    is_technology_sector: bool


def stake_size_score(stake: Decimal | None) -> Decimal:
    if stake is None:
        return _ZERO
    return min(Decimal("20"), max(_ZERO, stake) * Decimal("2"))


def active_intent_score(active: bool) -> Decimal:
    return Decimal("15") if active else _ZERO


def recency_score(filing_date: date, today: date) -> Decimal:
    days = (today - filing_date).days
    if days < 0:
        return _ZERO
    if days <= 5:
        return Decimal("15")
    if days <= 10:
        return Decimal("10")
    if days <= 20:
        return Decimal("5")
    return _ZERO


def filer_quality_score(filer_name: str | None) -> Decimal:
    if filer_name is None:
        return _ZERO
    lowered = filer_name.lower()
    for tier_value, patterns in _KNOWN_FILER_TIERS:
        if any(pattern in lowered for pattern in patterns):
            return tier_value
    return _ZERO


def rel_vol_score(rel_vol: Decimal | None) -> Decimal:
    if rel_vol is None:
        return _ZERO
    if rel_vol <= Decimal("1"):
        return _ZERO
    capped = min(rel_vol, Decimal("4"))
    return ((capped - Decimal("1")) / Decimal("3")) * Decimal("10")


def price_confirmation_score(price_pct: Decimal | None) -> Decimal:
    if price_pct is None or price_pct <= _ZERO:
        return _ZERO
    capped = min(price_pct, Decimal("0.10"))
    return (capped / Decimal("0.10")) * Decimal("10")


def option_liquidity_score(score: Decimal | None) -> Decimal:
    if score is None:
        return _ZERO
    return min(Decimal("5"), max(_ZERO, score))


def earnings_collision_penalty(days_to_next_earnings: int | None) -> Decimal:
    if days_to_next_earnings is None:
        return _ZERO
    if 0 <= days_to_next_earnings <= 5:
        return Decimal("10")
    return _ZERO


def gap_exhaustion_penalty(gap_pct: Decimal | None) -> Decimal:
    if gap_pct is None or gap_pct <= Decimal("0.10"):
        return _ZERO
    excess = min(gap_pct, Decimal("0.30")) - Decimal("0.10")
    return (excess / Decimal("0.20")) * Decimal("15")


def tech_concentration_penalty(is_technology_sector: bool) -> Decimal:
    return Decimal("8") if is_technology_sector else _ZERO


def compose_event_score(inputs: EventScoreInputs) -> Decimal:
    positive = (
        stake_size_score(inputs.stake_percent)
        + active_intent_score(inputs.active_intent)
        + recency_score(inputs.filing_date, inputs.today)
        + filer_quality_score(inputs.filer_name)
        + rel_vol_score(inputs.rel_vol)
        + price_confirmation_score(inputs.price_confirmation_pct)
        + option_liquidity_score(inputs.option_liquidity_score)
    )
    penalty = (
        earnings_collision_penalty(inputs.days_to_next_earnings)
        + gap_exhaustion_penalty(inputs.gap_exhaustion_pct)
        + tech_concentration_penalty(inputs.is_technology_sector)
    )
    raw = positive - penalty
    if raw < _ZERO:
        return _ZERO
    if raw > _HUNDRED:
        return _HUNDRED
    return raw
