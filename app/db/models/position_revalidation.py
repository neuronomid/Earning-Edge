from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK


class PositionRevalidation(Base):
    __tablename__ = "position_revalidations"
    __table_args__ = (
        Index("ix_position_revalidations_position_fired", "open_position_id", "fired_at"),
        Index("ix_position_revalidations_user_fired", "user_id", "fired_at"),
        Index(
            "ix_position_revalidations_auto_cooldown",
            "open_position_id",
            "trigger",
            "fired_at",
        ),
    )

    id: Mapped[UuidPK]
    open_position_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("open_positions.id", ondelete="CASCADE")
    )
    position_thesis_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("position_theses.id", ondelete="CASCADE")
    )
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    fired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    trigger: Mapped[str] = mapped_column(String(8))
    trigger_codes_json: Mapped[list[str]] = mapped_column(JSONB, default=list)

    market_session_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    market_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_close_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    current_underlying_price: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )
    current_option_premium: Mapped[Decimal | None] = mapped_column(
        Numeric(14, 4),
        nullable=True,
    )
    current_option_bid: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    current_option_ask: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    current_option_mid: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    current_implied_volatility: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )
    current_delta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    current_gamma: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    current_theta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    current_vega: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    quote_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quote_status: Mapped[str] = mapped_column(String(16))

    drift_snapshot_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    new_headlines_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)

    llm_action_raw: Mapped[str | None] = mapped_column(String(32), nullable=True)
    llm_action_final: Mapped[str] = mapped_column(String(32))
    llm_confidence_band: Mapped[str | None] = mapped_column(String(16), nullable=True)
    llm_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_evidence_json: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    proposed_adjustment_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    normalization_notes_json: Mapped[list[str]] = mapped_column(JSONB, default=list)

    llm_model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    llm_call_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    delivered_telegram_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[CreatedAt]
