from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from html import escape
from typing import Any

from app.db.models.open_position import OpenPosition
from app.db.models.position_revalidation import PositionRevalidation
from app.db.models.recommendation import Recommendation


def render_validation_result(
    validation: PositionRevalidation,
    position: OpenPosition,
    recommendation: Recommendation,
) -> str:
    action = str(validation.llm_action_final or "insufficient_data")
    lines = [
        (
            f"<b>Position review - {_escape(recommendation.ticker)} "
            f"{_format_strike(recommendation.strike)} "
            f"{_escape(str(recommendation.option_type).capitalize())} "
            f"exp {_date_iso(recommendation.expiry)}</b>"
        ),
        "",
        f"Decision: {_decision_label(action)}",
        f"Confidence: {_escape(str(validation.llm_confidence_band or 'low'))}",
    ]

    explanation = _decision_explanation(action)
    if explanation:
        lines.extend(["", explanation])

    if validation.trigger_codes_json:
        codes = ", ".join(_escape(str(code)) for code in validation.trigger_codes_json)
        lines.append(f"Review triggered by: {codes}")

    evidence_lines = _evidence_lines(validation.llm_evidence_json or [])
    if evidence_lines:
        lines.extend(["", "<b>Evidence checked</b>", *evidence_lines])

    if validation.llm_summary:
        lines.extend(["", "<b>Summary</b>", _escape(str(validation.llm_summary))])

    lines.extend(
        [
            "",
            "<b>Current position</b>",
            f"Underlying: {_money_or_na(validation.current_underlying_price)}",
            f"Option exit premium: {_money_or_na(validation.current_option_premium)}",
            f"Entry premium: {_money_or_na(position.entry_price)}",
            f"Target: {_money_or_na(recommendation.target_option_price)}",
            f"Stop: {_money_or_na(recommendation.stop_loss_option_price)}",
        ]
    )

    proposed = validation.proposed_adjustment_json
    if isinstance(proposed, dict):
        adjustment_lines = _adjustment_lines(proposed)
        if adjustment_lines:
            lines.extend(["", "<b>Suggested adjustment</b>", *adjustment_lines])

    return "\n".join(lines)


def render_validation_history(rows: list[PositionRevalidation]) -> str:
    if not rows:
        return "No validation history yet."
    lines = ["<b>Validation history</b>"]
    for row in rows:
        fired = _date_display(row.fired_at)
        codes = ", ".join(str(code) for code in row.trigger_codes_json or []) or "manual"
        lines.append(
            f"- {fired} - {_escape(str(row.trigger))} - "
            f"{_decision_label(str(row.llm_action_final))} - {_escape(codes)}"
        )
    return "\n".join(lines)


def _decision_label(action: str) -> str:
    if action == "hold":
        return "Hold"
    if action == "adjust_target":
        return "Adjust target"
    if action == "adjust_stop":
        return "Adjust stop"
    if action == "close":
        return "Review close"
    if action == "insufficient_data":
        return "Could not verify"
    return action.replace("_", " ").title()


def _decision_explanation(action: str) -> str:
    if action == "hold":
        return "The thesis still has supported evidence and no unaddressed kill signal."
    if action == "adjust_target":
        return "The review suggests changing the target; use the apply button only if you agree."
    if action == "adjust_stop":
        return "The review suggests changing the stop; use the apply button only if you agree."
    if action == "close":
        return (
            "The review found a thesis-break signal worth considering. "
            "The bot has not closed the position."
        )
    if action == "insufficient_data":
        return (
            "The review did not have enough supported live data or evidence to verify the "
            "thesis. This is not a close or hold instruction. Target, stop, exit-date, "
            "and expiry alerts continue to run."
        )
    return ""


def _evidence_lines(evidence: list[Any]) -> list[str]:
    lines: list[str] = []
    for item in evidence[:5]:
        if not isinstance(item, dict):
            continue
        code = str(item.get("code") or "evidence")
        observation = str(item.get("observation") or "No detail supplied.")
        significance = str(item.get("significance") or "").strip()
        suffix = f" ({_escape(significance)})" if significance else ""
        lines.append(f"- {_escape(_friendly_code(code))}{suffix}: {_escape(observation)}")
    return lines


def _friendly_code(code: str) -> str:
    labels = {
        "drift_signal:no_breach": "No thesis break",
        "drift_signal:within_plan": "Within plan",
        "data_quality:insufficient_supported_evidence": "Evidence gap",
        "data_quality:llm_unavailable": "Review unavailable",
        "option_stop_breach": "Option stop breach",
        "underlying_stop_breach": "Underlying stop breach",
        "adverse_underlying_drift": "Adverse underlying move",
        "premium_trajectory_lag": "Premium lag",
        "iv_adverse_move": "IV move",
        "time_decay_overshoot": "Time decay risk",
        "catalyst_passed_no_follow_through": "Catalyst follow-through",
        "pead_follow_through_failure": "PEAD follow-through",
        "expiry_imminent_unresolved": "Expiry risk",
        "new_material_news_candidate": "Material news",
    }
    if code in labels:
        return labels[code]
    if ":" in code:
        code = code.split(":", 1)[1]
    return code.replace("_", " ").title()


def _adjustment_lines(proposed: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    if proposed.get("target_option_price") is not None:
        lines.append(f"Target: {_money_or_na(proposed['target_option_price'])}")
    if proposed.get("stop_loss_option_price") is not None:
        lines.append(f"Stop: {_money_or_na(proposed['stop_loss_option_price'])}")
    if proposed.get("underlying_stop_price") is not None:
        lines.append(f"Underlying stop: {_money_or_na(proposed['underlying_stop_price'])}")
    if proposed.get("reason"):
        lines.append(_escape(str(proposed["reason"])))
    return lines


def _money_or_na(value: Any) -> str:
    amount = _decimal(value)
    if amount is None:
        return "N/A"
    return f"${amount:.2f}"


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return amount if amount.is_finite() else None


def _format_strike(value: Any) -> str:
    amount = _decimal(value)
    if amount is None:
        return _escape(str(value))
    return f"{amount:g}"


def _date_iso(value: Any) -> str:
    if hasattr(value, "isoformat"):
        return _escape(value.isoformat())
    return _escape(str(value))


def _date_display(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M")


def _escape(value: str) -> str:
    return escape(value, quote=False)
