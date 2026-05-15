from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.sec.scoring import (
    EventScoreInputs,
    active_intent_score,
    compose_event_score,
    earnings_collision_penalty,
    filer_quality_score,
    gap_exhaustion_penalty,
    option_liquidity_score,
    price_confirmation_score,
    recency_score,
    rel_vol_score,
    stake_size_score,
    tech_concentration_penalty,
)

TODAY = date(2026, 5, 14)


def _inputs(
    *,
    stake: Decimal | None = Decimal("7.5"),
    active_intent: bool = True,
    filing_date: date = date(2026, 5, 10),
    filer_name: str | None = "Elliott Management",
    rel_vol: Decimal | None = Decimal("2.0"),
    price_confirmation_pct: Decimal | None = Decimal("0.05"),
    option_liquidity_score: Decimal | None = Decimal("3"),
    days_to_next_earnings: int | None = None,
    gap_exhaustion_pct: Decimal | None = Decimal("0.04"),
    is_technology_sector: bool = False,
) -> EventScoreInputs:
    return EventScoreInputs(
        stake_percent=stake,
        active_intent=active_intent,
        filing_date=filing_date,
        today=TODAY,
        filer_name=filer_name,
        rel_vol=rel_vol,
        price_confirmation_pct=price_confirmation_pct,
        option_liquidity_score=option_liquidity_score,
        days_to_next_earnings=days_to_next_earnings,
        gap_exhaustion_pct=gap_exhaustion_pct,
        is_technology_sector=is_technology_sector,
    )


def test_event_score_ranks_fresh_active_above_stale_passive() -> None:
    fresh_active = compose_event_score(_inputs())
    stale_passive = compose_event_score(
        _inputs(
            active_intent=False,
            filing_date=date(2026, 4, 1),
            filer_name=None,
        )
    )

    assert fresh_active > stale_passive
    assert fresh_active > Decimal("50")
    assert stale_passive < Decimal("30")


def test_tech_concentration_penalty_pushes_tech_below_non_tech_ties() -> None:
    base = compose_event_score(_inputs())
    tech_variant = compose_event_score(_inputs(is_technology_sector=True))

    assert tech_variant < base
    assert (base - tech_variant) == Decimal("8")


def test_earnings_collision_penalty_kicks_in_within_5_days() -> None:
    no_collision = compose_event_score(_inputs(days_to_next_earnings=12))
    collision = compose_event_score(_inputs(days_to_next_earnings=3))

    assert collision < no_collision
    assert (no_collision - collision) == Decimal("10")


def test_each_sub_scorer_caps_at_documented_maximum() -> None:
    assert stake_size_score(Decimal("50")) == Decimal("20")
    assert stake_size_score(None) == Decimal("0")
    assert active_intent_score(True) == Decimal("15")
    assert active_intent_score(False) == Decimal("0")
    assert recency_score(TODAY, TODAY) == Decimal("15")
    assert recency_score(date(2026, 4, 1), TODAY) == Decimal("0")
    assert filer_quality_score("Elliott Investment Management") == Decimal("10")
    assert filer_quality_score("Engaged Capital LLC") == Decimal("6")
    assert filer_quality_score("Unknown Filer LP") == Decimal("0")
    assert rel_vol_score(Decimal("100")) == Decimal("10")
    assert price_confirmation_score(Decimal("0.50")) == Decimal("10")
    assert option_liquidity_score(Decimal("99")) == Decimal("5")
    assert earnings_collision_penalty(2) == Decimal("10")
    assert earnings_collision_penalty(None) == Decimal("0")
    assert gap_exhaustion_penalty(Decimal("0.99")) == Decimal("15")
    assert gap_exhaustion_penalty(Decimal("0.05")) == Decimal("0")
    assert tech_concentration_penalty(True) == Decimal("8")
    assert tech_concentration_penalty(False) == Decimal("0")

    saturated = compose_event_score(
        _inputs(
            stake=Decimal("99"),
            rel_vol=Decimal("99"),
            price_confirmation_pct=Decimal("0.50"),
            option_liquidity_score=Decimal("99"),
            gap_exhaustion_pct=Decimal("0"),
        )
    )
    # 20 (stake) + 15 (intent) + 15 (recency) + 10 (filer) + 10 (rel_vol) +
    # 10 (price confirmation) + 5 (option liquidity) = 85
    assert saturated == Decimal("85")
