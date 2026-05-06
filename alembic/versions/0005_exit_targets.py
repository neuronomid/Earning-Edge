"""add exit target fields

Revision ID: 0005_exit_targets
Revises: 0004_strategy_source, 0004_recommendation_parent_chain
Create Date: 2026-05-05 22:45:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_exit_targets"
down_revision = ("0004_strategy_source", "0004_recommendation_parent_chain")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("option_contracts", sa.Column("gamma", sa.Numeric(10, 6), nullable=True))
    op.add_column("option_contracts", sa.Column("theta", sa.Numeric(10, 6), nullable=True))
    op.add_column("option_contracts", sa.Column("vega", sa.Numeric(10, 6), nullable=True))
    op.add_column(
        "option_contracts", sa.Column("target_stock_price", sa.Numeric(14, 4), nullable=True)
    )
    op.add_column(
        "option_contracts", sa.Column("target_option_price", sa.Numeric(14, 4), nullable=True)
    )
    op.add_column(
        "option_contracts", sa.Column("target_gain_percent", sa.Numeric(8, 4), nullable=True)
    )
    op.add_column(
        "option_contracts",
        sa.Column("stop_loss_option_price", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column("option_contracts", sa.Column("exit_by_date", sa.Date(), nullable=True))
    op.add_column(
        "option_contracts", sa.Column("expected_holding_days", sa.Integer(), nullable=True)
    )
    op.add_column("option_contracts", sa.Column("target_method", sa.String(32), nullable=True))

    op.add_column(
        "recommendations", sa.Column("target_stock_price", sa.Numeric(14, 4), nullable=True)
    )
    op.add_column(
        "recommendations", sa.Column("target_option_price", sa.Numeric(14, 4), nullable=True)
    )
    op.add_column(
        "recommendations", sa.Column("target_gain_percent", sa.Numeric(8, 4), nullable=True)
    )
    op.add_column(
        "recommendations",
        sa.Column("stop_loss_option_price", sa.Numeric(14, 4), nullable=True),
    )
    op.add_column("recommendations", sa.Column("exit_by_date", sa.Date(), nullable=True))
    op.add_column(
        "recommendations", sa.Column("expected_holding_days", sa.Integer(), nullable=True)
    )
    op.add_column("recommendations", sa.Column("target_method", sa.String(32), nullable=True))


def downgrade() -> None:
    op.drop_column("recommendations", "target_method")
    op.drop_column("recommendations", "expected_holding_days")
    op.drop_column("recommendations", "exit_by_date")
    op.drop_column("recommendations", "stop_loss_option_price")
    op.drop_column("recommendations", "target_gain_percent")
    op.drop_column("recommendations", "target_option_price")
    op.drop_column("recommendations", "target_stock_price")

    op.drop_column("option_contracts", "target_method")
    op.drop_column("option_contracts", "expected_holding_days")
    op.drop_column("option_contracts", "exit_by_date")
    op.drop_column("option_contracts", "stop_loss_option_price")
    op.drop_column("option_contracts", "target_gain_percent")
    op.drop_column("option_contracts", "target_option_price")
    op.drop_column("option_contracts", "target_stock_price")
    op.drop_column("option_contracts", "vega")
    op.drop_column("option_contracts", "theta")
    op.drop_column("option_contracts", "gamma")
