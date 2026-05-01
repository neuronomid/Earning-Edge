from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    id: Mapped[UuidPK]
    recommendation_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    user_action: Mapped[str] = mapped_column(
        String(32)
    )  # bought/skipped/still_holding/closed
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    exit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    pnl: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[CreatedAt]
