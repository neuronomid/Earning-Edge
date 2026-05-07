from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.services.positions.account import realized_pnl
from app.telegram.templates.positions import action_label


@dataclass(frozen=True, slots=True)
class HistorySummary:
    account_size: Decimal
    total_profit: Decimal
    total_loss: Decimal
    total_positions: int
    wins: int
    losses: int
    win_rate: Decimal
    drawdown: Decimal


def render_history_card(position: OpenPosition, recommendation: Recommendation) -> str:
    pnl = realized_pnl(position, recommendation)
    lines = [
        f"<b>{recommendation.ticker} — {action_label(recommendation)}</b>",
        f"Entry Price: ${_money(position.entry_price)}",
        f"Exit Price: {_exit_price_display(position)}",
        f"Entry Date: {_date_display(position.entry_at)}",
        f"Exit Date: {_date_display(position.close_at)}",
        f"Contracts: {position.entry_quantity}",
        f"P/L: {_pnl_display(pnl)}",
    ]
    return "\n".join(lines)


def compute_history_summary(
    user: User,
    rows: list[tuple[OpenPosition, Recommendation]],
) -> HistorySummary:
    pnl_by_row = [
        (position, realized_pnl(position, recommendation))
        for position, recommendation in rows
    ]

    total_profit = sum((pnl for _, pnl in pnl_by_row if pnl > 0), Decimal("0"))
    total_loss = sum((pnl for _, pnl in pnl_by_row if pnl < 0), Decimal("0"))
    wins = sum(1 for _, pnl in pnl_by_row if pnl > 0)
    losses = sum(1 for _, pnl in pnl_by_row if pnl < 0)
    total_positions = len(pnl_by_row)
    win_rate = (
        (Decimal(wins) * Decimal("100") / Decimal(total_positions))
        if total_positions > 0
        else Decimal("0")
    )

    drawdown = _max_drawdown([pnl for _, pnl in _chronological(pnl_by_row)])

    return HistorySummary(
        account_size=Decimal(user.account_size),
        total_profit=total_profit,
        total_loss=total_loss,
        total_positions=total_positions,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        drawdown=drawdown,
    )


def render_history_summary(summary: HistorySummary) -> str:
    lines = [
        "<b>📜 History Summary</b>",
        f"Account Size: ${_money(summary.account_size)}",
        f"Total Profit: +${_money(summary.total_profit)}",
        f"Total Loss: -${_money(abs(summary.total_loss))}",
        f"Total Positions: {summary.total_positions}",
        f"Wins: {summary.wins}",
        f"Losses: {summary.losses}",
        f"Win Rate: {summary.win_rate:.1f}%",
        f"Max Drawdown: -${_money(summary.drawdown)}",
    ]
    return "\n".join(lines)


def _chronological(
    rows: list[tuple[OpenPosition, Decimal]],
) -> list[tuple[OpenPosition, Decimal]]:
    return sorted(
        rows,
        key=lambda r: (r[0].close_at or r[0].entry_at, r[0].id),
    )


def _max_drawdown(pnls: list[Decimal]) -> Decimal:
    """Largest peak-to-trough decline of cumulative P/L. Returned as a non-negative number."""
    if not pnls:
        return Decimal("0")
    cumulative = Decimal("0")
    peak = Decimal("0")
    max_dd = Decimal("0")
    for pnl in pnls:
        cumulative += pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _exit_price_display(position: OpenPosition) -> str:
    if position.status == "closed_expired" and position.close_price is None:
        return "Expired ($0.00)"
    if position.close_price is None:
        return "—"
    return f"${_money(position.close_price)}"


def _date_display(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.date().isoformat()


def _money(value: Decimal) -> str:
    return f"{value:.2f}"


def _pnl_display(pnl: Decimal) -> str:
    if pnl >= 0:
        return f"+${pnl:.2f} profit"
    return f"-${abs(pnl):.2f} loss"
