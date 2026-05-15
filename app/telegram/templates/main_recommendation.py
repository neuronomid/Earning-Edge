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
    underlying_stop_price: Decimal | None
    exit_by_date: date | None
    earnings_date: date | None
    suggested_quantity: int
    estimated_max_loss: str
    margin_requirement: Decimal | None
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
        "Watchlist only" if watchlist_only else f"{recommendation.suggested_quantity} contract(s)"
    )
    lines.extend(
        [
            f"<b>{_signal_title(recommendation)}</b>",
            "",
            setup_text,
            "",
            (
                f"{_direction_emoji(recommendation)} <b>Direction:</b> "
                f"{_direction_label(recommendation)}"
            ),
            f"📃 <b>Contract:</b> {contract_label(recommendation)}",
            f"🏷️ <b>Strike:</b> ${_money(recommendation.strike)}",
            f"💵 <b>Suggested entry:</b> {_entry_text(recommendation)}",
            f"📎 <b>Suggested quantity:</b> {quantity_text}",
            f"🗓️ <b>Expiry:</b> {recommendation.expiry.isoformat()}",
            "",
        ]
    )
    target_option_price = getattr(recommendation, "target_option_price", None)
    if target_option_price is not None:
        lines.append(f"🟢 <b>{_target_label(recommendation)}:</b> ${_money(target_option_price)}")
    stop_loss_option_price = getattr(recommendation, "stop_loss_option_price", None)
    if stop_loss_option_price is not None:
        lines.append(f"🛑 <b>{_stop_label(recommendation)}:</b> ${_money(stop_loss_option_price)}")
    underlying_stop_price = getattr(recommendation, "underlying_stop_price", None)
    if underlying_stop_price is not None:
        lines.append(f"<b>Underlying stop alert:</b> ${_money(underlying_stop_price)}")
    target_stock_price = getattr(recommendation, "target_stock_price", None)
    if target_stock_price is not None:
        lines.append(f"🎯 <b>Stock target:</b> ${_money(target_stock_price)}")
    exit_by_date = getattr(recommendation, "exit_by_date", None)
    if exit_by_date is not None:
        lines.append(
            f"🗓️ <b>Exit by:</b> {exit_by_date.isoformat()} ({exit_by_date.strftime('%A')})"
        )
    lines.extend(
        [
            "",
            f"<b>Estimated max loss:</b> {_max_loss_text(recommendation)}",
            *_margin_lines(recommendation),
            f"<b>Account risk:</b> {_percent(recommendation.account_risk_percent)}",
            f"<b>Earnings date:</b> {_earnings_date_text(recommendation)}",
            f"<b>Setup score:</b> {recommendation.confidence_score}/100",
            f"<b>Risk level:</b> {recommendation.risk_level}",
        ]
    )
    lines.extend(_risk_disclosures(recommendation))
    news_coverage = getattr(recommendation, "news_coverage", None)
    if news_coverage in {"none", "sparse"}:
        lines.append(f"📰 <b>News:</b> {news_coverage}")
    if getattr(recommendation, "stale_news", False):
        lines.append("⚠️ <b>Stale news</b> (most recent article > 14 days old)")
    lines.extend(
        [
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


def _signal_title(recommendation: RecommendationLike) -> str:
    strategy_source = getattr(recommendation, "strategy_source", "catalyst_confluence")
    return {
        "catalyst_confluence": "Earnings Options Signal",
        "pead_continuation": "Post-Earnings Drift Options Signal",
        "coiled_setup": "Coiled Setup Options Signal",
        "sector_relative_strength": "Sector Relative Strength Options Signal",
        "activist_13d_followthrough": "Activist 13D Options Signal",
    }.get(strategy_source, "Options Signal")


def _direction_emoji(recommendation: RecommendationLike) -> str:
    return "📈" if recommendation.option_type == "call" else "📉"


def _entry_text(recommendation: RecommendationLike) -> str:
    value = recommendation.suggested_entry
    if value is None:
        return "Review live pricing in your broker"
    if recommendation.position_side == "short":
        return f"at least ${_money(value)} credit"
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


def _earnings_date_text(recommendation: RecommendationLike) -> str:
    value = getattr(recommendation, "earnings_date", None)
    return "No earnings catalyst" if value is None else value.isoformat()


def _target_label(recommendation: RecommendationLike) -> str:
    if recommendation.position_side == "short":
        return "Target buyback"
    return "Target sell price"


def _stop_label(recommendation: RecommendationLike) -> str:
    if recommendation.position_side == "short":
        return "Stop buyback alert"
    return "Stop loss"


def _risk_disclosures(recommendation: RecommendationLike) -> list[str]:
    lines: list[str] = []
    if getattr(recommendation, "stop_loss_option_price", None) is not None:
        lines.append(
            "<b>Stop note:</b> Mental alert only, not a broker order. "
            "Earnings or overnight gaps can move past this stop before you can act."
        )
    if recommendation.position_side == "short" and recommendation.option_type == "call":
        lines.append(
            "<b>Naked short call risk:</b> Undefined gap risk; broker margin "
            "can differ from this estimate."
        )
    return lines


def _margin_lines(recommendation: RecommendationLike) -> list[str]:
    margin_requirement = getattr(recommendation, "margin_requirement", None)
    if margin_requirement is None:
        return []
    return [f"<b>Estimated broker buying power:</b> ${_money(margin_requirement)}"]


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):,.2f}"


def _percent(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'))}%"
