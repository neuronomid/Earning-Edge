"""merge parallel 0004 revisions

Revision ID: 0005_merge_heads
Revises: 0004_recommendation_parent_chain, 0004_strategy_source
Create Date: 2026-05-06 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "0005_merge_heads"
down_revision: tuple[str, str] | None = (
    "0004_recommendation_parent_chain",
    "0004_strategy_source",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
