from __future__ import annotations

from decimal import Decimal

from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.services.positions.monitor import position_pnl
from app.services.positions.quotes import BidAskQuote


def render_position_card(
    position: OpenPosition,
    recommendation: Recommendation,
    quote: BidAskQuote | None,
) -> str:
    lines = [
        f"<b>{recommendation.ticker} — {action_label(recommendation)}</b>",
        f"Contracts: {position.entry_quantity}",
        f"Entry: ${_money(position.entry_price)}",
        f"Expiry: {recommendation.expiry.isoformat()}",
        f"Target: {_optional_money(recommendation.target_option_price)} · "
        f"Stop: {_optional_money(recommendation.stop_loss_option_price)}",
    ]

    closing_price = _closing_price(recommendation.position_side, quote)
    closing_label = _closing_label(recommendation.position_side)

    if quote is None or closing_price is None:
        lines.append("Live quote: unavailable")
    else:
        lines.append(
            f"{closing_label} (live): ${_money(closing_price)} (source: {quote.source})"
        )
        pnl = position_pnl(
            entry_price=position.entry_price,
            close_price=closing_price,
            quantity=position.entry_quantity,
            position_side=recommendation.position_side,
        )
        lines.append(f"P/L: {_pnl_display(pnl)}")

    return "\n".join(lines)


def action_label(recommendation: Recommendation) -> str:
    side = recommendation.position_side.lower()
    option_type = recommendation.option_type.lower()
    side_word = "Buy" if side == "long" else "Short"
    option_word = "Call" if option_type == "call" else "Put"
    return f"{side_word} {option_word}"


def _closing_price(position_side: str, quote: BidAskQuote | None) -> Decimal | None:
    if quote is None:
        return None
    if position_side.lower() == "long":
        return quote.bid
    return quote.ask


def _closing_label(position_side: str) -> str:
    return "Bid" if position_side.lower() == "long" else "Ask"


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _optional_money(value: Decimal | None) -> str:
    return "—" if value is None else f"${_money(value)}"


def _pnl_display(pnl: Decimal) -> str:
    if pnl >= 0:
        return f"+${pnl:.2f} profit"
    return f"-${abs(pnl):.2f} loss"
