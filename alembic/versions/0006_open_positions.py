"""add open positions

Revision ID: 0006_open_positions
Revises: 0005_exit_targets
Create Date: 2026-05-07 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0006_open_positions"
down_revision = "0005_exit_targets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "open_positions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entry_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("entry_quantity", sa.Integer(), nullable=False),
        sa.Column(
            "entry_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("close_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_premium", sa.Numeric(14, 4), nullable=True),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_data_source", sa.String(16), nullable=True),
        sa.Column(
            "alerts_sent",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_open_positions_user_status", "open_positions", ["user_id", "status"])
    op.create_index(
        "ix_open_positions_recommendation_status",
        "open_positions",
        ["recommendation_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_open_positions_recommendation_status", table_name="open_positions")
    op.drop_index("ix_open_positions_user_status", table_name="open_positions")
    op.drop_table("open_positions")
