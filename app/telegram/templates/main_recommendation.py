from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol

from app.telegram.templates.short_option import contract_label, max_loss_display


class RecommendationLike(Protocol):
    ticker: str
    company_name: str
    option_type: str
    position_side: str
    strike: Decimal
    expiry: date
    suggested_entry: Decimal | None
    target_stock_price: Decimal | None
    target_option_price: Decimal | None
    stop_loss_option_price: Decimal | None
    exit_by_date: date | None
    suggested_quantity: int
    estimated_max_loss: str
    account_risk_percent: Decimal
    confidence_score: int
    risk_level: str
    reasoning_summary: str


def render_main_recommendation(
    recommendation: RecommendationLike,
    *,
    rank_position: int = 1,
    warning_text: str | None = None,
    watchlist_only: bool = False,
    setup_label: str = "Best setup",
) -> str:
    lines: list[str] = []
    if warning_text:
        lines.extend([warning_text, ""])

    setup_text = (
        f"<b>{_setup_label(rank_position)}:</b> "
        f"{_rank_medal(rank_position)} {recommendation.ticker}"
    )
    quantity_text = (
        "Watchlist only"
        if watchlist_only
        else f"{recommendation.suggested_quantity} contract(s)"
    )
    lines.extend(
        [
            "<b>Weekly Earnings Options Signal</b>",
            "",
            setup_text,
            "",
            f"{_direction_emoji(recommendation)} <b>Direction:</b> {_direction_label(recommendation)}",
            f"📃 <b>Contract:</b> {contract_label(recommendation)}",
            f"🏷️ <b>Strike:</b> ${_money(recommendation.strike)}",
            f"💵 <b>Suggested entry:</b> {_entry_text(recommendation.suggested_entry)}",
            f"📎 <b>Suggested quantity:</b> {quantity_text}",
            f"🗓️ <b>Expiry:</b> {recommendation.expiry.isoformat()}",
            "",
            "",
        ]
    )
    if getattr(recommendation, "target_option_price", None) is not None:
        lines.append(
            f"🟢 <b>Target sell price:</b> ${_money(recommendation.target_option_price)}"
        )
    if getattr(recommendation, "stop_loss_option_price", None) is not None:
        lines.append(
            f"🛑 <b>Stop loss:</b> ${_money(recommendation.stop_loss_option_price)}"
        )
    if getattr(recommendation, "target_stock_price", None) is not None:
        lines.append(f"🎯 <b>Stock target:</b> ${_money(recommendation.target_stock_price)}")
    if getattr(recommendation, "exit_by_date", None) is not None:
        lines.append(f"🗓️ <b>Exit by:</b> {recommendation.exit_by_date.isoformat()}")
    lines.extend(
        [
            "",
            f"<b>Estimated max loss:</b> {_max_loss_text(recommendation)}",
            f"<b>Account risk:</b> {_percent(recommendation.account_risk_percent)}",
            f"<b>Earnings date:</b> {_earnings_date(recommendation).isoformat()}",
            f"<b>Confidence:</b> {recommendation.confidence_score}/100",
            f"<b>Risk level:</b> {recommendation.risk_level}",
            "",
            f"{_action_emoji(watchlist_only)} <b>Action:</b>",
            _action_text(watchlist_only),
        ]
    )
    return "\n".join(lines)


def _setup_label(rank_position: int) -> str:
    if rank_position == 2:
        return "2nd best setup"
    if rank_position == 3:
        return "3rd best setup"
    if rank_position > 3:
        return f"Alternative setup #{rank_position}"
    return "Best setup"


def _rank_medal(rank_position: int) -> str:
    return {
        1: "🥇",
        2: "🥈",
        3: "🥉",
    }.get(rank_position, "•")


def _direction_label(recommendation: RecommendationLike) -> str:
    if recommendation.option_type == "call":
        return "Bullish"
    return "Bearish"


def _direction_emoji(recommendation: RecommendationLike) -> str:
    return "📈" if recommendation.option_type == "call" else "📉"


def _entry_text(value: Decimal | None) -> str:
    if value is None:
        return "Review live pricing in your broker"
    return f"up to ${_money(value)} premium"


def _action_text(watchlist_only: bool) -> str:
    if watchlist_only:
        return "Keep this on the watchlist and only size it if the setup improves."
    return "Manually review the contract in your broker before buying."


def _action_emoji(watchlist_only: bool) -> str:
    return "⚠️" if watchlist_only else "✅"


def _max_loss_text(recommendation: RecommendationLike) -> str:
    raw = max_loss_display(recommendation)
    return raw.replace(" max loss ", " ")


def _earnings_date(recommendation: RecommendationLike) -> date:
    value = getattr(recommendation, "earnings_date", None)
    return recommendation.expiry if value is None else value


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"
