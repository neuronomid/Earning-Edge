from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import CreatedAt, UpdatedAt, UuidFK, UuidPK

if TYPE_CHECKING:
    from app.db.models.user import User


class CronJob(Base):
    __tablename__ = "cron_jobs"
    __table_args__ = (Index("ix_cron_jobs_user_id", "user_id"),)

    id: Mapped[UuidPK]
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    day_of_week: Mapped[str] = mapped_column(String(16))  # e.g. "monday"
    local_time: Mapped[str] = mapped_column(String(8))  # e.g. "10:30"
    timezone_label: Mapped[str] = mapped_column(String(8))
    timezone_iana: Mapped[str] = mapped_column(String(64))

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    user: Mapped[User] = relationship(back_populates="cron_jobs")
