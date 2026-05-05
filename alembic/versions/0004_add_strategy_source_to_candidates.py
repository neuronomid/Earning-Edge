"""add strategy_source column to candidates

Revision ID: 0004_add_strategy_source_to_candidates
Revises: 0003_rename_tradingview_status
Create Date: 2026-05-04 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_add_strategy_source_to_candidates"
down_revision: str | None = "0003_rename_tradingview_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "candidates",
        sa.Column("strategy_source", sa.String(32), nullable=True),
    )
    op.execute(
        "UPDATE candidates SET strategy_source = 'catalyst_confluence' "
        "WHERE strategy_source IS NULL"
    )
    op.alter_column("candidates", "strategy_source", nullable=False)
    op.create_index(
        "ix_candidates_strategy_source", "candidates", ["strategy_source"]
    )


def downgrade() -> None:
    op.drop_index("ix_candidates_strategy_source", table_name="candidates")
    op.drop_column("candidates", "strategy_source")
