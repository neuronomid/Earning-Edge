"""add mute tracking and alert frequency counters to positions and alert_mute_duration to users

Revision ID: 0008_position_mute
Revises: 0007_position_pnl_applied
Create Date: 2026-05-08 00:00:01
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_position_mute"
down_revision = "0007_position_pnl_applied"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add alert count columns to track frequency logic (first crossing vs subsequent)
    op.add_column(
        "open_positions",
        sa.Column(
            "target_alert_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.add_column(
        "open_positions",
        sa.Column(
            "stop_alert_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )

    # Add dismissal flags (user pressed "Okay" — no more alerts)
    op.add_column(
        "open_positions",
        sa.Column(
            "target_dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "open_positions",
        sa.Column(
            "stop_dismissed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )

    # Add mute expiry columns (user pressed "Mute" — silence until this time)
    op.add_column(
        "open_positions",
        sa.Column(
            "target_muted_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "open_positions",
        sa.Column(
            "stop_muted_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    # Backfill: if position has "target_hit" in alerts_sent, set alert_count=1
    # to preserve behavior (already crossed once, so use crossing logic)
    op.execute(
        """
        UPDATE open_positions
        SET target_alert_count = 1
        WHERE alerts_sent @> '["target_hit"]'
        """
    )
    op.execute(
        """
        UPDATE open_positions
        SET stop_alert_count = 1
        WHERE alerts_sent @> '["stop_hit"]'
        """
    )

    # Add alert_mute_duration to users table
    op.add_column(
        "users",
        sa.Column(
            "alert_mute_duration",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'1d'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "alert_mute_duration")
    op.drop_column("open_positions", "stop_muted_until")
    op.drop_column("open_positions", "target_muted_until")
    op.drop_column("open_positions", "stop_dismissed")
    op.drop_column("open_positions", "target_dismissed")
    op.drop_column("open_positions", "stop_alert_count")
    op.drop_column("open_positions", "target_alert_count")
