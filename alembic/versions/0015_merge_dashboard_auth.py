"""merge dashboard_auth branch into main

Revision ID: 0015_merge_dashboard_auth
Revises: 0009_dashboard_auth, 0014_news_coverage_default_none
Create Date: 2026-05-15 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0015_merge_dashboard_auth"
down_revision: tuple[str, str] | None = (
    "0009_dashboard_auth",
    "0014_news_coverage_default_none",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
