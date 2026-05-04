"""add recommendation parent chain

Revision ID: 0004_recommendation_parent_chain
Revises: 0003_rename_tradingview_status
Create Date: 2026-05-03 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_recommendation_parent_chain"
down_revision: str | None = "0003_rename_tradingview_status"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column("parent_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_recommendations_parent_recommendation_id",
        "recommendations",
        "recommendations",
        ["parent_recommendation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_recommendations_parent_recommendation_id",
        "recommendations",
        type_="foreignkey",
    )
    op.drop_column("recommendations", "parent_recommendation_id")
