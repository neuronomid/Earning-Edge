from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Protocol

from app.telegram.templates.short_option import contract_label, max_loss_display


class RecommendationLike(Protocol):
    ticker: str
    company_name: str
    option_type: str
    position_side: str
    strike: Decimal
    expiry: date
    suggested_entry: Decimal | None
    suggested_quantity: int
    estimated_max_loss: str
    account_risk_percent: Decimal
    confidence_score: int
    risk_level: str
    reasoning_summary: str
    key_concerns_json: Any


def render_main_recommendation(
    recommendation: RecommendationLike,
    *,
    warning_text: str | None = None,
    watchlist_only: bool = False,
) -> str:
    lines: list[str] = []
    if warning_text:
        lines.extend([warning_text, ""])

    lines.extend(
        [
            "<b>Weekly Earnings Options Signal</b>",
            "",
            f"<b>Best setup:</b> {recommendation.ticker}",
            f"<b>Direction:</b> {_direction_label(recommendation)}",
            f"<b>Contract:</b> {contract_label(recommendation)}",
            f"<b>Strike:</b> ${_money(recommendation.strike)}",
            f"<b>Expiry:</b> {recommendation.expiry.isoformat()}",
            f"<b>Suggested entry:</b> {_entry_text(recommendation.suggested_entry)}",
        ]
    )
    if watchlist_only:
        lines.append("<b>Suggested quantity:</b> Watchlist only")
    else:
        lines.append(f"<b>Suggested quantity:</b> {recommendation.suggested_quantity} contract(s)")
    lines.extend(
        [
            f"<b>Estimated max loss:</b> {max_loss_display(recommendation)}",
            f"<b>Account risk:</b> {_percent(recommendation.account_risk_percent)}",
            f"<b>Earnings date:</b> {_earnings_date(recommendation).isoformat()}",
            f"<b>Confidence:</b> {recommendation.confidence_score}/100",
            f"<b>Risk level:</b> {recommendation.risk_level}",
            "",
            "<b>Why this setup:</b>",
            recommendation.reasoning_summary,
            "",
            "<b>Important warning:</b>",
            _warning_text(recommendation),
            "",
            "<b>Action:</b>",
            _action_text(watchlist_only),
        ]
    )
    return "\n".join(lines)


def _direction_label(recommendation: RecommendationLike) -> str:
    if recommendation.option_type == "call":
        return "Bullish"
    return "Bearish"


def _entry_text(value: Decimal | None) -> str:
    if value is None:
        return "Review live pricing in your broker"
    return f"up to ${_money(value)} premium"


def _warning_text(recommendation: RecommendationLike) -> str:
    concerns = _normalize_string_list(recommendation.key_concerns_json)
    if recommendation.position_side == "short":
        base = (
            "Short options can be assignment- and margin-sensitive around earnings, "
            "so confirm the broker treatment before placing anything."
        )
    else:
        base = (
            "This trade holds through earnings. IV crush can reduce the option value after "
            "the report even if the stock moves in the expected direction."
        )
    if not concerns:
        return base
    return f"{base} Main concern: {concerns[0]}"


def _action_text(watchlist_only: bool) -> str:
    if watchlist_only:
        return "Keep this on the watchlist and only size it if the setup improves."
    return "Manually review the contract in your broker before buying."


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list):
            return [str(item) for item in items]
    return []


def _earnings_date(recommendation: RecommendationLike) -> date:
    value = getattr(recommendation, "earnings_date", None)
    return recommendation.expiry if value is None else value


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"
