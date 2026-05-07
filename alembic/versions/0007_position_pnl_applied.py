"""add pnl_applied flag and backfill account_size from closed positions

Revision ID: 0007_position_pnl_applied
Revises: 0006_open_positions
Create Date: 2026-05-07 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_position_pnl_applied"
down_revision = "0006_open_positions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "open_positions",
        sa.Column(
            "pnl_applied",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Backfill: roll cumulative P/L of every already-closed position into the
    # owning user's account_size, then mark those rows as applied so the
    # close/modify/delete flows never double-count.
    op.execute(
        """
        WITH closed_pnl AS (
            SELECT
                op.user_id,
                SUM(
                    CASE r.position_side
                        WHEN 'short' THEN
                            (op.entry_price - COALESCE(op.close_price, 0))
                            * 100 * op.entry_quantity
                        ELSE
                            (COALESCE(op.close_price, 0) - op.entry_price)
                            * 100 * op.entry_quantity
                    END
                ) AS pnl
            FROM open_positions op
            JOIN recommendations r ON r.id = op.recommendation_id
            WHERE op.status <> 'active'
            GROUP BY op.user_id
        )
        UPDATE users u
        SET account_size = u.account_size + cp.pnl
        FROM closed_pnl cp
        WHERE u.id = cp.user_id
        """
    )

    op.execute("UPDATE open_positions SET pnl_applied = true WHERE status <> 'active'")


def downgrade() -> None:
    # Account-size backfill is intentionally not reversed on downgrade — undoing
    # it could erase legitimate trade outcomes the user has since acted on.
    op.drop_column("open_positions", "pnl_applied")
