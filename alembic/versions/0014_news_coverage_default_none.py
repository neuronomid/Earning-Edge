"""default unavailable recommendation news coverage to none

Revision ID: 0014_news_coverage_default_none
Revises: 0013_strategy_source_widen
Create Date: 2026-05-15 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0014_news_coverage_default_none"
down_revision = "0013_strategy_source_widen"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "recommendations",
        "news_coverage",
        existing_type=sa.String(length=16),
        server_default=sa.text("'none'"),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "recommendations",
        "news_coverage",
        existing_type=sa.String(length=16),
        server_default=sa.text("'adequate'"),
        existing_nullable=False,
    )
