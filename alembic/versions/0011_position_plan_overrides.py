"""add position plan overrides

Revision ID: 0011_position_plan_overrides
Revises: 0010_safety_expected_move
Create Date: 2026-05-13 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0011_position_plan_overrides"
down_revision = "0010_safety_expected_move"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_plan_overrides",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "open_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("open_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # The revalidation table lands in a later phase. Keep the identifier now
        # so the override contract is stable, and add the FK in that migration.
        sa.Column("position_revalidation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_option_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("stop_loss_option_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("underlying_stop_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("source", sa.String(32), nullable=False, server_default="user"),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_position_plan_overrides_position_created",
        "position_plan_overrides",
        ["open_position_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_position_plan_overrides_position_created",
        table_name="position_plan_overrides",
    )
    op.drop_table("position_plan_overrides")
