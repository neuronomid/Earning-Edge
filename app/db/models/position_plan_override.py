from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK


class PositionPlanOverride(Base):
    __tablename__ = "position_plan_overrides"

    id: Mapped[UuidPK]
    open_position_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("open_positions.id", ondelete="CASCADE")
    )
    position_revalidation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("position_revalidations.id", ondelete="SET NULL"),
        nullable=True,
    )

    target_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    stop_loss_option_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)
    underlying_stop_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 4), nullable=True)

    source: Mapped[str] = mapped_column(
        String(32),
        default="user",
        server_default="user",
        nullable=False,
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[CreatedAt]
