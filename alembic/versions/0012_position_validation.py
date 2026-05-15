"""add position theses and revalidations

Revision ID: 0012_position_validation
Revises: 0011_position_plan_overrides
Create Date: 2026-05-13 00:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "0012_position_validation"
down_revision = "0011_position_plan_overrides"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "position_theses",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "open_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("open_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
        sa.Column("schema_version", sa.String(16), nullable=False, server_default="v1"),
        sa.Column("ticker", sa.String(16), nullable=False),
        sa.Column("company_name", sa.String(255), nullable=True),
        sa.Column(
            "strategy_source",
            sa.String(32),
            nullable=False,
            server_default="catalyst_confluence",
        ),
        sa.Column("strategy", sa.String(32), nullable=False),
        sa.Column("option_type", sa.String(8), nullable=False),
        sa.Column("position_side", sa.String(8), nullable=False),
        sa.Column("strike", sa.Numeric(14, 4), nullable=False),
        sa.Column("expiry", sa.Date(), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("entry_option_premium", sa.Numeric(14, 4), nullable=False),
        sa.Column("entry_quantity", sa.Integer(), nullable=False),
        sa.Column("entry_price_source", sa.String(16), nullable=False, server_default="user_fill"),
        sa.Column("entry_underlying_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_option_bid", sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_option_ask", sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_option_mid", sa.Numeric(14, 4), nullable=True),
        sa.Column("entry_implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_gamma", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("entry_snapshot_source", sa.String(32), nullable=True),
        sa.Column("entry_snapshot_status", sa.String(16), nullable=False, server_default="partial"),
        sa.Column(
            "entry_snapshot_notes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("target_option_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("target_stock_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("stop_loss_option_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("underlying_stop_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("exit_by_date", sa.Date(), nullable=True),
        sa.Column("expected_holding_days", sa.Integer(), nullable=True),
        sa.Column("expected_move_percent", sa.Numeric(10, 6), nullable=True),
        sa.Column(
            "expected_trajectory_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("catalyst_kind", sa.String(16), nullable=False, server_default="none"),
        sa.Column("catalyst_event_date", sa.Date(), nullable=True),
        sa.Column(
            "catalyst_baseline_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("invalidation_criteria_json", postgresql.JSONB(), nullable=False),
        sa.Column("direction_score", sa.Integer(), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=True),
        sa.Column("contract_score", sa.Integer(), nullable=True),
        sa.Column("data_confidence_score", sa.Integer(), nullable=True),
        sa.Column("reasoning_summary", sa.Text(), nullable=True),
        sa.Column(
            "key_evidence_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "key_concerns_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "news_brief_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "news_articles_baseline_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("news_coverage", sa.String(16), nullable=True),
        sa.Column("stale_news", sa.Boolean(), nullable=True),
        sa.Column("news_published_max_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("news_baseline_status", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("decision_engine", sa.String(32), nullable=True),
        sa.Column("heavy_model_used", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("open_position_id", name="uq_position_theses_open_position"),
    )
    op.create_index(
        "ix_position_theses_user_created",
        "position_theses",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_position_theses_recommendation",
        "position_theses",
        ["recommendation_id"],
    )

    op.create_table(
        "position_revalidations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "open_position_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("open_positions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "position_thesis_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("position_theses.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "fired_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(8), nullable=False),
        sa.Column(
            "trigger_codes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("market_session_date", sa.Date(), nullable=True),
        sa.Column("market_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_close_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_underlying_price", sa.Numeric(14, 4), nullable=True),
        sa.Column("current_option_premium", sa.Numeric(14, 4), nullable=True),
        sa.Column("current_option_bid", sa.Numeric(14, 4), nullable=True),
        sa.Column("current_option_ask", sa.Numeric(14, 4), nullable=True),
        sa.Column("current_option_mid", sa.Numeric(14, 4), nullable=True),
        sa.Column("current_implied_volatility", sa.Numeric(10, 6), nullable=True),
        sa.Column("current_delta", sa.Numeric(10, 6), nullable=True),
        sa.Column("current_gamma", sa.Numeric(10, 6), nullable=True),
        sa.Column("current_theta", sa.Numeric(10, 6), nullable=True),
        sa.Column("current_vega", sa.Numeric(10, 6), nullable=True),
        sa.Column("quote_source", sa.String(32), nullable=True),
        sa.Column("quote_status", sa.String(16), nullable=False),
        sa.Column("drift_snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "new_headlines_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("llm_action_raw", sa.String(32), nullable=True),
        sa.Column("llm_action_final", sa.String(32), nullable=False),
        sa.Column("llm_confidence_band", sa.String(16), nullable=True),
        sa.Column("llm_summary", sa.Text(), nullable=True),
        sa.Column(
            "llm_evidence_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("proposed_adjustment_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "normalization_notes_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("llm_model_used", sa.String(64), nullable=True),
        sa.Column("llm_call_duration_ms", sa.Integer(), nullable=True),
        sa.Column("delivered_telegram_message_id", sa.String(64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_position_revalidations_position_fired",
        "position_revalidations",
        ["open_position_id", "fired_at"],
    )
    op.create_index(
        "ix_position_revalidations_user_fired",
        "position_revalidations",
        ["user_id", "fired_at"],
    )
    op.create_index(
        "ix_position_revalidations_auto_cooldown",
        "position_revalidations",
        ["open_position_id", "trigger", "fired_at"],
    )
    op.create_foreign_key(
        "fk_position_plan_overrides_revalidation",
        "position_plan_overrides",
        "position_revalidations",
        ["position_revalidation_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_position_plan_overrides_revalidation",
        "position_plan_overrides",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_position_revalidations_auto_cooldown",
        table_name="position_revalidations",
    )
    op.drop_index(
        "ix_position_revalidations_user_fired",
        table_name="position_revalidations",
    )
    op.drop_index(
        "ix_position_revalidations_position_fired",
        table_name="position_revalidations",
    )
    op.drop_table("position_revalidations")
    op.drop_index("ix_position_theses_recommendation", table_name="position_theses")
    op.drop_index("ix_position_theses_user_created", table_name="position_theses")
    op.drop_table("position_theses")
