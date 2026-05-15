"""add news_coverage and stale_news to recommendations

Revision ID: 0009_news_coverage
Revises: 0008_position_mute
Create Date: 2026-05-10 00:00:01
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_news_coverage"
down_revision = "0008_position_mute"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "recommendations",
        sa.Column(
            "news_coverage",
            sa.String(16),
            nullable=False,
            server_default=sa.text("'adequate'"),
        ),
    )
    op.add_column(
        "recommendations",
        sa.Column(
            "stale_news",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("recommendations", "stale_news")
    op.drop_column("recommendations", "news_coverage")
