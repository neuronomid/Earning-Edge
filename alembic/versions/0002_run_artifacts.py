"""store phase-12 run artifacts

Revision ID: 0002_run_artifacts
Revises: 0001_initial
Create Date: 2026-05-01 17:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_run_artifacts"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("run_summary_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("candidate_cards_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("option_contracts_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("recommendation_card_json", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "workflow_runs",
        sa.Column("telegram_message_text", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workflow_runs", "telegram_message_text")
    op.drop_column("workflow_runs", "recommendation_card_json")
    op.drop_column("workflow_runs", "option_contracts_json")
    op.drop_column("workflow_runs", "candidate_cards_json")
    op.drop_column("workflow_runs", "run_summary_json")
