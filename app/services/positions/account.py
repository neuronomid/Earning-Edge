from __future__ import annotations

from decimal import Decimal

from app.db.models.open_position import OpenPosition
from app.db.models.recommendation import Recommendation
from app.db.models.user import User
from app.services.positions.monitor import position_pnl


def realized_pnl(position: OpenPosition, recommendation: Recommendation) -> Decimal:
    """P/L at the moment the position was closed.

    For expired-worthless rows we treat close_price as 0 (long pays the full
    premium, short keeps the full premium).
    """
    close_price = position.close_price if position.close_price is not None else Decimal("0")
    return position_pnl(
        entry_price=position.entry_price,
        close_price=close_price,
        quantity=position.entry_quantity,
        position_side=recommendation.position_side,
    )


def apply_pnl_to_account(
    user: User,
    position: OpenPosition,
    recommendation: Recommendation,
) -> Decimal:
    """Add the realized P/L to user.account_size and mark the row applied.

    Idempotent: if pnl_applied is already true, this is a no-op and returns 0.
    Returns the delta that was applied.
    """
    if position.pnl_applied:
        return Decimal("0")
    pnl = realized_pnl(position, recommendation)
    user.account_size = user.account_size + pnl
    position.pnl_applied = True
    return pnl


def reverse_pnl_from_account(
    user: User,
    position: OpenPosition,
    recommendation: Recommendation,
) -> Decimal:
    """Subtract a previously-applied P/L from user.account_size.

    Idempotent: if pnl_applied is false, no-op. Returns the delta that was
    reversed.
    """
    if not position.pnl_applied:
        return Decimal("0")
    pnl = realized_pnl(position, recommendation)
    user.account_size = user.account_size - pnl
    position.pnl_applied = False
    return pnl


def reapply_pnl_after_modification(
    user: User,
    position: OpenPosition,
    recommendation: Recommendation,
    *,
    previous_pnl: Decimal,
) -> Decimal:
    """Adjust account_size by (new_pnl - previous_pnl) after a field change.

    Caller is responsible for snapshotting previous_pnl via realized_pnl()
    before mutating the position. Returns the net delta applied.
    """
    new_pnl = realized_pnl(position, recommendation)
    delta = new_pnl - previous_pnl
    if delta != 0:
        user.account_size = user.account_size + delta
    position.pnl_applied = True
    return delta
