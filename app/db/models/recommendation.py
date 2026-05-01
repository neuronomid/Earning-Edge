from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from sqlalchemy import Date, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import JSONB
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

    ticker: Mapped[str] = mapped_column(String(16))
    company_name: Mapped[str] = mapped_column(String(255))

    strategy: Mapped[str] = mapped_column(String(32))
    option_type: Mapped[str] = mapped_column(String(8))  # call/put
    position_side: Mapped[str] = mapped_column(String(8))  # long/short

    strike: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    expiry: Mapped[date] = mapped_column(Date)

    suggested_entry: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    suggested_quantity: Mapped[int] = mapped_column(Integer)
    estimated_max_loss: Mapped[str] = mapped_column(Text)  # text, e.g. "Undefined for naked..."
    account_risk_percent: Mapped[Decimal] = mapped_column(Numeric(7, 4))

    confidence_score: Mapped[int] = mapped_column(Integer)
    risk_level: Mapped[str] = mapped_column(String(16))

    reasoning_summary: Mapped[str] = mapped_column(Text)
    key_evidence_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)
    key_concerns_json: Mapped[dict[str, Any] | list[Any]] = mapped_column(JSONB)

    telegram_message_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[CreatedAt]

    user: Mapped[User] = relationship(back_populates="recommendations")
