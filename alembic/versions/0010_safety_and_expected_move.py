"""add safety rails and expected-move audit fields

Revision ID: 0010_safety_expected_move
Revises: 0009_news_coverage
Create Date: 2026-05-11 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0010_safety_expected_move"
down_revision = "0009_news_coverage"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "candidates",
        "earnings_date",
        existing_type=sa.Date(),
        nullable=True,
    )
    op.add_column(
        "candidates",
        sa.Column("expected_move_percent", sa.Numeric(10, 6), nullable=True),
    )

    op.add_column(
        "option_contracts",
        sa.Column("underlying_stop_price", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column(
        "option_contracts",
        sa.Column("expected_move_percent", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "option_contracts",
        sa.Column("margin_requirement", sa.Numeric(14, 4), nullable=True),
    )

    op.add_column(
        "recommendations",
        sa.Column("earnings_date", sa.Date(), nullable=True),
    )
    op.add_column(
        "recommendations",
        sa.Column(
            "strategy_source",
            sa.String(32),
            nullable=False,
            server_default=sa.text("'catalyst_confluence'"),
        ),
    )
    op.add_column(
        "recommendations",
        sa.Column("underlying_stop_price", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column(
        "recommendations",
        sa.Column("expected_move_percent", sa.Numeric(10, 6), nullable=True),
    )
    op.add_column(
        "recommendations",
        sa.Column("margin_requirement", sa.Numeric(14, 4), nullable=True),
    )

    op.execute("UPDATE users SET custom_risk_percent = NULL WHERE custom_risk_percent <= 0")
    op.execute("UPDATE users SET custom_risk_percent = 0.05 WHERE custom_risk_percent > 0.05")
    op.create_check_constraint(
        "ck_users_custom_risk_percent_0_5",
        "users",
        "custom_risk_percent IS NULL OR (custom_risk_percent > 0 AND custom_risk_percent <= 0.05)",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_users_custom_risk_percent_0_5",
        "users",
        type_="check",
    )
    op.drop_column("recommendations", "margin_requirement")
    op.drop_column("recommendations", "expected_move_percent")
    op.drop_column("recommendations", "underlying_stop_price")
    op.drop_column("recommendations", "strategy_source")
    op.drop_column("recommendations", "earnings_date")

    op.drop_column("option_contracts", "margin_requirement")
    op.drop_column("option_contracts", "expected_move_percent")
    op.drop_column("option_contracts", "underlying_stop_price")

    op.drop_column("candidates", "expected_move_percent")
    op.execute("UPDATE candidates SET earnings_date = CURRENT_DATE WHERE earnings_date IS NULL")
    op.alter_column(
        "candidates",
        "earnings_date",
        existing_type=sa.Date(),
        nullable=False,
    )
