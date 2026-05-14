"""strategy_source widen for pead, sector_rs, activist_13d

Revision ID: 0013_strategy_source_widen
Revises: 0012_position_validation
Create Date: 2026-05-13 00:00:00
"""

from __future__ import annotations

revision = "0013_strategy_source_widen"
down_revision = "0012_position_validation"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # No DDL: strategy_source columns are String(32), and all new slugs fit.
    pass


def downgrade() -> None:
    pass
