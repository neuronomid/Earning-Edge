"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-01 00:00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telegram_chat_id", sa.String(64), nullable=False),
        sa.Column("account_size", sa.Numeric(14, 2), nullable=False),
        sa.Column("risk_profile", sa.String(32), nullable=False),
        sa.Column("custom_risk_percent", sa.Numeric(5, 4), nullable=True),
        sa.Column("broker", sa.String(32), nullable=False),
        sa.Column("timezone_label", sa.String(8), nullable=False),
        sa.Column("timezone_iana", sa.String(64), nullable=False),
        sa.Column("strategy_permission", sa.String(32), nullable=False),
        sa.Column("max_contracts", sa.Integer(), nullable=False),
        sa.Column("max_option_premium", sa.Numeric(10, 4), nullable=True),
        sa.Column("openrouter_api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("alpaca_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("alpaca_api_secret_encrypted", sa.Text(), nullable=True),
        sa.Column("alpha_vantage_api_key_encrypted", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_users_telegram_chat_id", "users", ["telegram_chat_id"], unique=True
    )

    op.create_table(
        "cron_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("day_of_week", sa.String(16), nullable=False),
        sa.Column("local_time", sa.String(8), nullable=False),
        sa.Column("timezone_label", sa.String(8), nullable=False),
        sa.Column("timezone_iana", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_cron_jobs_user_id", "cron_jobs", ["user_id"])

    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("trigger_type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tradingview_status", sa.String(16), nullable=True),
        sa.Column(
            "selected_candidate_count", sa.Integer(), nullable=False, server_default="0"
        ),
        # final_recommendation_id FK is added after recommendations table exists
        sa.Column(
            "final_recommendation_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
    )
    op.create_index(
        "ix_workflow_runs_user_status", "workflow_runs", ["user_id", "status"]
    )

    op.create_table(
        "candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("market_cap", sa.Numeric(20, 2), nullable=False),
        sa.Column("earnings_date", sa.Date(), nullable=False),
        sa.Column("earnings_timing", sa.String(8), nullable=True),
        sa.Column("current_price", sa.Numeric(14, 4), nullable=False),
        sa.Column("direction_classification", sa.String(16), nullable=False),
        sa.Column("candidate_direction_score", sa.Integer(), nullable=False),
        sa.Column("best_strategy", sa.String(32), nullable=True),
        sa.Column("final_opportunity_score", sa.Integer(), nullable=False),
        sa.Column("data_confidence_score", sa.Integer(), nullable=False),
        sa.Column(
            "selected_for_final", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "option_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "candidate_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("candidates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("option_type", sa.String(8), nullable=False),
        sa.Column("position_side", sa.String(8), nullable=False),
        sa.Column("strike", sa.Numeric(14, 4), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("bid", sa.Numeric(14, 4), nullable=False),
        sa.Column("ask", sa.Numeric(14, 4), nullable=False),
        sa.Column("mid", sa.Numeric(14, 4), nullable=False),
        sa.Column("volume", sa.Integer(), nullable=True),
        sa.Column("open_interest", sa.Integer(), nullable=True),
        sa.Column("implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("breakeven", sa.Numeric(14, 4), nullable=False),
        sa.Column("spread_percent", sa.Numeric(8, 4), nullable=False),
        sa.Column("liquidity_score", sa.Integer(), nullable=False),
        sa.Column("contract_opportunity_score", sa.Integer(), nullable=False),
        sa.Column(
            "passed_hard_filters",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )

    op.create_table(
        "recommendations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workflow_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=False),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("option_type", sa.String(8), nullable=False),
        sa.Column("position_side", sa.String(8), nullable=False),
        sa.Column("strike", sa.Numeric(14, 4), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("suggested_entry", sa.Numeric(14, 4), nullable=True),
        sa.Column("suggested_quantity", sa.Integer(), nullable=False),
        sa.Column("estimated_max_loss", sa.Text(), nullable=False),
        sa.Column("account_risk_percent", sa.Numeric(7, 4), nullable=False),
        sa.Column("confidence_score", sa.Integer(), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("reasoning_summary", sa.Text(), nullable=False),
        sa.Column("key_evidence_json", postgresql.JSONB(), nullable=False),
        sa.Column("key_concerns_json", postgresql.JSONB(), nullable=False),
        sa.Column("telegram_message_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_recommendations_user_created_desc",
        "recommendations",
        ["user_id", "created_at"],
    )

    # Add the cyclic FK from workflow_runs to recommendations now that both exist.
    op.create_foreign_key(
        "fk_workflow_runs_final_recommendation_id",
        "workflow_runs",
        "recommendations",
        ["final_recommendation_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_table(
        "feedback_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "recommendation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("recommendations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_action", sa.String(32), nullable=False),
        sa.Column("entry_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("exit_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("pnl", sa.Numeric(14, 4), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("feedback_events")
    op.drop_constraint(
        "fk_workflow_runs_final_recommendation_id", "workflow_runs", type_="foreignkey"
    )
    op.drop_index("ix_recommendations_user_created_desc", table_name="recommendations")
    op.drop_table("recommendations")
    op.drop_table("option_contracts")
    op.drop_table("candidates")
    op.drop_index("ix_workflow_runs_user_status", table_name="workflow_runs")
    op.drop_table("workflow_runs")
    op.drop_index("ix_cron_jobs_user_id", table_name="cron_jobs")
    op.drop_table("cron_jobs")
    op.drop_index("ix_users_telegram_chat_id", table_name="users")
    op.drop_table("users")
