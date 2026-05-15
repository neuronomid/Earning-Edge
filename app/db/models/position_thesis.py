from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK


class PositionThesis(Base):
    __tablename__ = "position_theses"
    __table_args__ = (
        Index("ix_position_theses_user_created", "user_id", "created_at"),
        Index("ix_position_theses_recommendation", "recommendation_id"),
    )

    id: Mapped[UuidPK]
    open_position_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("open_positions.id", ondelete="CASCADE"),
        unique=True,
    )
    recommendation_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    schema_version: Mapped[str] = mapped_column(String(16), default="v1")

    ticker: Mapped[str] = mapped_column(String(16))
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    strategy_source: Mapped[str] = mapped_column(String(32), default="catalyst_confluence")
    strategy: Mapped[str] = mapped_column(String(32))
    option_type: Mapped[str] = mapped_column(String(8))
    position_side: Mapped[str] = mapped_column(String(8))
    strike: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    expiry: Mapped[date] = mapped_column(Date)

    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    entry_option_premium: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    entry_quantity: Mapped[int] = mapped_column(Integer)
    entry_price_source: Mapped[str] = mapped_column(String(16), default="user_fill")

    entry_underlying_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_option_bid: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_option_ask: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_option_mid: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    entry_implied_volatility: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )
    entry_delta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_theta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_vega: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    entry_snapshot_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    entry_snapshot_status: Mapped[str] = mapped_column(String(16), default="partial")
    entry_snapshot_notes_json: Mapped[list[Any]] = mapped_column(JSONB, default=list)

    target_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    target_stock_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    stop_loss_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    underlying_stop_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    exit_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_move_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    expected_trajectory_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)

    catalyst_kind: Mapped[str] = mapped_column(String(16), default="none")
    catalyst_event_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    catalyst_baseline_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    invalidation_criteria_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)

    direction_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    final_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    contract_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_confidence_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reasoning_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_evidence_json: Mapped[list[Any] | dict[str, Any]] = mapped_column(JSONB, default=list)
    key_concerns_json: Mapped[list[Any] | dict[str, Any]] = mapped_column(JSONB, default=list)

    news_brief_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    news_articles_baseline_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    news_coverage: Mapped[str | None] = mapped_column(String(16), nullable=True)
    stale_news: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    news_published_max_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    news_baseline_status: Mapped[str] = mapped_column(String(32), default="unknown")

    decision_engine: Mapped[str | None] = mapped_column(String(32), nullable=True)
    heavy_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[CreatedAt]
