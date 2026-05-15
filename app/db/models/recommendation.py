from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK

if TYPE_CHECKING:
    from app.db.models.user import User


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        Index(
            "ix_recommendations_user_created_desc",
            "user_id",
            "created_at",
            postgresql_using="btree",
        ),
    )

    id: Mapped[UuidPK]
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    run_id: Mapped[UuidFK] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))
    parent_recommendation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="SET NULL"),
        nullable=True,
    )

    ticker: Mapped[str] = mapped_column(String(16))
    company_name: Mapped[str] = mapped_column(String(255))
    earnings_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    strategy_source: Mapped[str] = mapped_column(
        String(32), default="catalyst_confluence", server_default="catalyst_confluence"
    )

    strategy: Mapped[str] = mapped_column(String(32))
    option_type: Mapped[str] = mapped_column(String(8))  # call/put
    position_side: Mapped[str] = mapped_column(String(8))  # long/short

    strike: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    expiry: Mapped[date] = mapped_column(Date)

    suggested_entry: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    target_stock_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    target_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    target_gain_percent: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    stop_loss_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    underlying_stop_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    exit_by_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    expected_holding_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    expected_move_percent: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    margin_requirement: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    suggested_quantity: Mapped[int] = mapped_column(Integer)
    estimated_max_loss: Mapped[str] = mapped_column(Text)  # text, e.g. "Undefined for naked..."
    account_risk_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4))

    confidence_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(16))

    reasoning_summary: Mapped[str] = mapped_column(Text)
    key_evidence_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)
    key_concerns_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)

    telegram_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    news_coverage: Mapped[str] = mapped_column(String(16), default="none", server_default="none")
    stale_news: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

    created_at: Mapped[CreatedAt]

    user: Mapped[User] = relationship(back_populates="recommendations")
