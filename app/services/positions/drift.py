from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

from app.db.models.position_thesis import PositionThesis
from app.services.market_hours import MarketSession, market_sessions_between
from app.services.positions.plans import ActivePositionPlan
from app.services.positions.snapshots import PositionQuoteSnapshot

ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class NewsHeadline:
    id: str
    title: str
    source: str | None = None
    published_at: str | None = None


@dataclass(frozen=True, slots=True)
class FiredCriterion:
    code: str
    severity: str
    observation: str


@dataclass(frozen=True, slots=True)
class DriftEvaluation:
    fired: tuple[FiredCriterion, ...]
    snapshot: dict[str, Any]
    data_quality: tuple[str, ...]

    @property
    def auto_trigger_codes(self) -> tuple[str, ...]:
        return tuple(item.code for item in self.fired if item.severity in {"kill", "degrade"})


def evaluate_position_drift(
    *,
    thesis: PositionThesis,
    current: PositionQuoteSnapshot,
    session: MarketSession,
    new_headlines: Sequence[NewsHeadline] = (),
    plan: ActivePositionPlan | None = None,
) -> DriftEvaluation:
    target = _plan_target(thesis, plan)
    stop = _plan_stop(thesis, plan)
    underlying_stop = _plan_underlying_stop(thesis, plan)
    sessions_held = _sessions_held(thesis.entered_at.date(), session.session_date)
    sessions_to_expiry = len(market_sessions_between(session.session_date, thesis.expiry))
    expected_premium = _expected_premium_for_session(
        thesis.expected_trajectory_json,
        max(sessions_held - 1, 0),
    )
    premium = current.liquidation_premium
    direction = _direction(thesis)

    snapshot = {
        "ticker": thesis.ticker,
        "strategy_source": getattr(thesis, "strategy_source", "catalyst_confluence"),
        "direction": direction,
        "session_date": session.session_date.isoformat(),
        "sessions_held": sessions_held,
        "sessions_to_expiry": sessions_to_expiry,
        "current_underlying_price": _decimal_json(current.underlying_price),
        "entry_underlying_price": _decimal_json(thesis.entry_underlying_price),
        "underlying_drift_percent": _decimal_json(
            _percent_change(thesis.entry_underlying_price, current.underlying_price)
        ),
        "directional_underlying_drift_percent": _decimal_json(
            _directional_underlying_drift(
                thesis.entry_underlying_price,
                current.underlying_price,
                direction,
            )
        ),
        "current_option_premium": _decimal_json(premium),
        "entry_option_premium": _decimal_json(thesis.entry_option_premium),
        "premium_return_percent": _decimal_json(
            _percent_change(thesis.entry_option_premium, premium)
        ),
        "expected_premium": _decimal_json(expected_premium),
        "premium_vs_expected_ratio": _decimal_json(_ratio(premium, expected_premium)),
        "entry_implied_volatility": _decimal_json(thesis.entry_implied_volatility),
        "current_implied_volatility": _decimal_json(current.implied_volatility),
        "iv_ratio": _decimal_json(
            _ratio(current.implied_volatility, thesis.entry_implied_volatility)
        ),
        "target_option_price": _decimal_json(target),
        "stop_loss_option_price": _decimal_json(stop),
        "underlying_stop_price": _decimal_json(underlying_stop),
        "time_used_percent": _decimal_json(
            _time_used_percent(sessions_held, thesis.expected_holding_days)
        ),
        "catalyst_kind": thesis.catalyst_kind,
        "catalyst_event_date": (
            None if thesis.catalyst_event_date is None else thesis.catalyst_event_date.isoformat()
        ),
        "catalyst_baseline": getattr(thesis, "catalyst_baseline_json", {}),
        "new_headline_count": len(new_headlines),
        "new_headline_ids": [headline.id for headline in new_headlines],
        "quote_status": current.status,
        "quote_source": current.source,
    }

    data_quality = tuple(current.notes)
    fired: list[FiredCriterion] = []
    criteria = _enabled_criteria(thesis)

    if "option_stop_breach" in criteria and premium is not None and stop is not None:
        if _stop_reached(thesis.position_side, premium, stop):
            fired.append(
                FiredCriterion(
                    code="option_stop_breach",
                    severity="kill",
                    observation=f"Current exit premium {premium} breached stop {stop}.",
                )
            )

    if (
        "underlying_stop_breach" in criteria
        and current.underlying_price is not None
        and underlying_stop is not None
    ):
        if _underlying_stop_reached(direction, current.underlying_price, underlying_stop):
            fired.append(
                FiredCriterion(
                    code="underlying_stop_breach",
                    severity="kill",
                    observation=(
                        f"Underlying {current.underlying_price} breached stop {underlying_stop}."
                    ),
                )
            )

    adverse_drift = _directional_underlying_drift(
        thesis.entry_underlying_price,
        current.underlying_price,
        direction,
    )
    expected_move = _expected_move_ratio(thesis.expected_move_percent)
    if (
        "adverse_underlying_drift" in criteria
        and adverse_drift is not None
        and expected_move is not None
        and adverse_drift <= -(expected_move * Decimal("0.75"))
    ):
        fired.append(
            FiredCriterion(
                code="adverse_underlying_drift",
                severity="degrade",
                observation="Underlying moved adversely beyond plan tolerance.",
            )
        )

    premium_expected_ratio = _ratio(premium, expected_premium)
    if (
        "premium_trajectory_lag" in criteria
        and premium_expected_ratio is not None
        and _premium_lagged(thesis.position_side, premium_expected_ratio)
    ):
        fired.append(
            FiredCriterion(
                code="premium_trajectory_lag",
                severity="degrade",
                observation="Option premium is materially behind the expected path.",
            )
        )

    iv_ratio = _ratio(current.implied_volatility, thesis.entry_implied_volatility)
    if "iv_adverse_move" in criteria and iv_ratio is not None:
        if thesis.position_side == "long" and iv_ratio < Decimal("0.65"):
            fired.append(
                FiredCriterion(
                    code="iv_adverse_move",
                    severity="degrade",
                    observation="Implied volatility fell materially against a long option.",
                )
            )
        elif thesis.position_side == "short" and iv_ratio > Decimal("1.50"):
            fired.append(
                FiredCriterion(
                    code="iv_adverse_move",
                    severity="degrade",
                    observation="Implied volatility expanded materially against a short option.",
                )
            )

    if (
        "time_decay_overshoot" in criteria
        and thesis.position_side == "long"
        and thesis.expected_holding_days
        and premium is not None
        and sessions_held > thesis.expected_holding_days * Decimal("0.50")
        and premium < thesis.entry_option_premium * Decimal("0.50")
        and not _target_reached(thesis.position_side, premium, target)
    ):
        fired.append(
            FiredCriterion(
                code="time_decay_overshoot",
                severity="degrade",
                observation=(
                    "More than half the planned hold is used while premium is below half entry."
                ),
            )
        )

    if (
        "catalyst_passed_no_follow_through" in criteria
        and thesis.catalyst_event_date is not None
        and thesis.catalyst_event_date < session.session_date
        and adverse_drift is not None
        and expected_move is not None
        and adverse_drift < expected_move * Decimal("0.50")
    ):
        fired.append(
            FiredCriterion(
                code="catalyst_passed_no_follow_through",
                severity="degrade",
                observation="Catalyst passed without enough favorable follow-through.",
            )
        )

    if (
        "pead_follow_through_failure" in criteria
        and getattr(thesis, "strategy_source", None) == "pead_continuation"
        and adverse_drift is not None
        and expected_move is not None
        and adverse_drift < expected_move * Decimal("0.25")
    ):
        fired.append(
            FiredCriterion(
                code="pead_follow_through_failure",
                severity="degrade",
                observation="Post-earnings drift has not held enough follow-through.",
            )
        )

    if (
        "expiry_imminent_unresolved" in criteria
        and sessions_to_expiry <= 2
        and premium is not None
        and not _target_reached(thesis.position_side, premium, target)
    ):
        fired.append(
            FiredCriterion(
                code="expiry_imminent_unresolved",
                severity="kill",
                observation="Two or fewer market sessions remain and target is unresolved.",
            )
        )

    material_headlines = [
        headline for headline in new_headlines if _headline_looks_material(headline)
    ]
    if "new_material_news_candidate" in criteria and material_headlines:
        fired.append(
            FiredCriterion(
                code="new_material_news_candidate",
                severity="degrade",
                observation=f"{len(material_headlines)} new potentially material headline(s).",
            )
        )

    if current.liquidation_premium is None or current.underlying_price is None:
        fired.append(
            FiredCriterion(
                code="data_unavailable",
                severity="informational",
                observation="Current option premium or underlying price is unavailable.",
            )
        )

    snapshot["fired_codes"] = [item.code for item in fired]
    return DriftEvaluation(
        fired=tuple(fired),
        snapshot=snapshot,
        data_quality=data_quality,
    )


def _enabled_criteria(thesis: PositionThesis) -> set[str]:
    enabled: set[str] = set()
    raw = thesis.invalidation_criteria_json or []
    if not isinstance(raw, list):
        return enabled
    for item in raw:
        if isinstance(item, dict) and item.get("enabled") is True:
            enabled.add(str(item.get("code")))
    return enabled


def _direction(thesis: PositionThesis) -> str:
    strategy = thesis.strategy.lower()
    if strategy in {"long_put", "short_call"}:
        return "bearish"
    if strategy in {"long_call", "short_put"}:
        return "bullish"
    if thesis.option_type.lower() == "put":
        return "bearish" if thesis.position_side.lower() == "long" else "bullish"
    return "bullish" if thesis.position_side.lower() == "long" else "bearish"


def _plan_target(thesis: PositionThesis, plan: ActivePositionPlan | None) -> Decimal | None:
    return thesis.target_option_price if plan is None else plan.target_option_price


def _plan_stop(thesis: PositionThesis, plan: ActivePositionPlan | None) -> Decimal | None:
    return thesis.stop_loss_option_price if plan is None else plan.stop_loss_option_price


def _plan_underlying_stop(
    thesis: PositionThesis,
    plan: ActivePositionPlan | None,
) -> Decimal | None:
    return thesis.underlying_stop_price if plan is None else plan.underlying_stop_price


def _sessions_held(entry_date: date, session_date: date) -> int:
    return max(len(market_sessions_between(entry_date, session_date)), 1)


def _expected_premium_for_session(
    trajectory: dict[str, Any] | None,
    session_index: int,
) -> Decimal | None:
    if not isinstance(trajectory, dict):
        return None
    points = trajectory.get("points")
    if not isinstance(points, list) or not points:
        return None
    candidates = [
        point
        for point in points
        if isinstance(point, dict) and int(point.get("session_index", -1)) <= session_index
    ]
    point = candidates[-1] if candidates else points[0]
    if not isinstance(point, dict):
        return None
    return _decimal(point.get("expected_premium"))


def _stop_reached(position_side: str, current: Decimal, stop: Decimal) -> bool:
    if position_side == "short":
        return current >= stop
    return current <= stop


def _target_reached(
    position_side: str,
    current: Decimal | None,
    target: Decimal | None,
) -> bool:
    if current is None or target is None:
        return False
    if position_side == "short":
        return current <= target
    return current >= target


def _underlying_stop_reached(direction: str, current: Decimal, stop: Decimal) -> bool:
    if direction == "bearish":
        return current >= stop
    return current <= stop


def _premium_lagged(position_side: str, ratio: Decimal) -> bool:
    if position_side == "short":
        return ratio > Decimal("1.25")
    return ratio < Decimal("0.75")


def _directional_underlying_drift(
    entry: Decimal | None,
    current: Decimal | None,
    direction: str,
) -> Decimal | None:
    raw = _percent_change(entry, current)
    if raw is None:
        return None
    return -raw if direction == "bearish" else raw


def _percent_change(entry: Decimal | None, current: Decimal | None) -> Decimal | None:
    if entry is None or current is None or entry == ZERO:
        return None
    return (current - entry) / entry


def _ratio(numerator: Decimal | None, denominator: Decimal | None) -> Decimal | None:
    if numerator is None or denominator is None or denominator == ZERO:
        return None
    return numerator / denominator


def _time_used_percent(sessions_held: int, expected_holding_days: int | None) -> Decimal | None:
    if expected_holding_days is None or expected_holding_days <= 0:
        return None
    return Decimal(sessions_held) / Decimal(expected_holding_days)


def _expected_move_ratio(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value if value <= Decimal("1") else value / Decimal("100")


def _headline_looks_material(headline: NewsHeadline) -> bool:
    text = f"{headline.title} {headline.source or ''}".lower()
    terms = (
        "guidance",
        "downgrade",
        "upgrade",
        "offering",
        "investigation",
        "lawsuit",
        "sec",
        "fda",
        "merger",
        "acquisition",
        "bankruptcy",
        "restatement",
        "resignation",
        "target cut",
        "target raise",
        "preannouncement",
    )
    return any(term in text for term in terms)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _decimal_json(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.0001")))
