from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import CreatedAt, UpdatedAt, UuidPK

if TYPE_CHECKING:
    from app.db.models.cron_job import CronJob
    from app.db.models.recommendation import Recommendation
    from app.db.models.workflow_run import WorkflowRun


class User(Base):
    __tablename__ = "users"

    id: Mapped[UuidPK]

    telegram_chat_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)

    account_size: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    risk_profile: Mapped[str] = mapped_column(String(32))  # Conservative/Balanced/Aggressive
    custom_risk_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 4), nullable=True)
    broker: Mapped[str] = mapped_column(String(32))

    timezone_label: Mapped[str] = mapped_column(String(8))  # PT/MT/CT/ET/AT/NT
    timezone_iana: Mapped[str] = mapped_column(String(64))

    strategy_permission: Mapped[str] = mapped_column(String(32))  # long/short/long_and_short
    max_contracts: Mapped[int] = mapped_column(Integer, default=1)
    max_option_premium: Mapped[Decimal | None] = mapped_column(Numeric(10, 4), nullable=True)

    openrouter_api_key_encrypted: Mapped[str] = mapped_column(Text)
    alpaca_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    alpaca_api_secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    alpha_vantage_api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[CreatedAt]
    updated_at: Mapped[UpdatedAt]

    cron_jobs: Mapped[list[CronJob]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    workflow_runs: Mapped[list[WorkflowRun]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    recommendations: Mapped[list[Recommendation]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
