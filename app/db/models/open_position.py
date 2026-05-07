from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK


class OpenPosition(Base):
    __tablename__ = "open_positions"

    id: Mapped[UuidPK]
    recommendation_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("recommendations.id", ondelete="CASCADE")
    )
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    entry_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    entry_quantity: Mapped[int] = mapped_column(Integer)
    entry_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(String(16), default="active")
    close_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    close_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    last_premium: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_data_source: Mapped[str | None] = mapped_column(String(16), nullable=True)
    alerts_sent: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    pnl_applied: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    created_at: Mapped[CreatedAt]
