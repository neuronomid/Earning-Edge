from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from app.db.models.open_position import OpenPosition
from app.db.models.position_revalidation import PositionRevalidation
from app.db.models.recommendation import Recommendation


def render_validation_result(
    validation: PositionRevalidation,
    position: OpenPosition,
    recommendation: Recommendation,
) -> str:
    action = _action_label(validation.llm_action_final)
    lines = [
        (
            f"<b>Position review - {recommendation.ticker} "
            f"{recommendation.strike:g} {recommendation.option_type.capitalize()} "
            f"exp {recommendation.expiry.isoformat()}</b>"
        ),
        "",
        f"Action: {action}",
        f"Confidence: {validation.llm_confidence_band or 'low'}",
    ]
    if validation.trigger_codes_json:
        lines.append("Triggered by: " + ", ".join(validation.trigger_codes_json))
    lines.extend(["", "<b>Why</b>"])
    for item in (validation.llm_evidence_json or [])[:5]:
        if isinstance(item, dict):
            code = item.get("code", "evidence")
            observation = item.get("observation", "")
            lines.append(f"- {code} - {observation}")
    if validation.llm_summary:
        lines.extend(["", "<b>Summary</b>", validation.llm_summary])

    lines.extend(
        [
            "",
            "<b>Current</b>",
            f"Underlying: {_money_or_dash(validation.current_underlying_price)}",
            f"Exit premium: {_money_or_dash(validation.current_option_premium)}",
            f"Entry: {_money_or_dash(position.entry_price)}",
            f"Target: {_money_or_dash(recommendation.target_option_price)}",
            f"Stop: {_money_or_dash(recommendation.stop_loss_option_price)}",
        ]
    )
    proposed = validation.proposed_adjustment_json
    if isinstance(proposed, dict):
        lines.extend(["", "<b>Suggested adjustment</b>"])
        if proposed.get("target_option_price") is not None:
            lines.append(f"Target: ${Decimal(str(proposed['target_option_price'])):.2f}")
        if proposed.get("stop_loss_option_price") is not None:
            lines.append(f"Stop: ${Decimal(str(proposed['stop_loss_option_price'])):.2f}")
        if proposed.get("underlying_stop_price") is not None:
            lines.append(f"Underlying stop: ${Decimal(str(proposed['underlying_stop_price'])):.2f}")
        if proposed.get("reason"):
            lines.append(str(proposed["reason"]))
    return "\n".join(lines)


def render_validation_history(rows: list[PositionRevalidation]) -> str:
    if not rows:
        return "No validation history yet."
    lines = ["<b>Validation history</b>"]
    for row in rows:
        fired = _date_display(row.fired_at)
        codes = ", ".join(row.trigger_codes_json or []) or "manual"
        lines.append(f"- {fired} · {row.trigger} · {_action_label(row.llm_action_final)} · {codes}")
    return "\n".join(lines)


def _action_label(action: str) -> str:
    if action == "close":
        return "REVIEW CLOSE"
    if action == "insufficient_data":
        return "INSUFFICIENT DATA"
    return action.replace("_", " ").upper()


def _money_or_dash(value: Decimal | None) -> str:
    return "—" if value is None else f"${value:.2f}"


def _date_display(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%Y-%m-%d %H:%M")
