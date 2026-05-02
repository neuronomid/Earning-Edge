"""rename tradingview_status to screener_status

Revision ID: 0003_rename_tradingview_status
Revises: 0002_run_artifacts
Create Date: 2026-05-02 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003_rename_tradingview_status"
down_revision: str | None = "0002_run_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("workflow_runs", "tradingview_status", new_column_name="screener_status")


def downgrade() -> None:
    op.alter_column("workflow_runs", "screener_status", new_column_name="tradingview_status")
