from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import UuidFK, UuidPK

if TYPE_CHECKING:
    from app.db.models.candidate import Candidate
    from app.db.models.recommendation import Recommendation
    from app.db.models.user import User


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (Index("ix_workflow_runs_user_status", "user_id", "status"),)

    id: Mapped[UuidPK]
    user_id: Mapped[UuidFK] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))

    trigger_type: Mapped[str] = mapped_column(String(16))  # cron/manual
    status: Mapped[str] = mapped_column(String(16))  # running/success/failed/no_trade

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    tradingview_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    selected_candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    final_recommendation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey(
            "recommendations.id",
            ondelete="SET NULL",
            use_alter=True,
            name="fk_workflow_runs_final_recommendation_id",
        ),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    run_summary_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    candidate_cards_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    option_contracts_json: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB, nullable=True
    )
    recommendation_card_json: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    telegram_message_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    user: Mapped[User] = relationship(back_populates="workflow_runs")
    candidates: Mapped[list[Candidate]] = relationship(
        back_populates="run", cascade="all, delete-orphan", foreign_keys="Candidate.run_id"
    )
    final_recommendation: Mapped[Recommendation | None] = relationship(
        foreign_keys=[final_recommendation_id], post_update=True
    )
