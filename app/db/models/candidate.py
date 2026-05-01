from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK

if TYPE_CHECKING:
    from app.db.models.option_contract import OptionContract
    from app.db.models.workflow_run import WorkflowRun


class Candidate(Base):
    __tablename__ = "candidates"

    id: Mapped[UuidPK]
    run_id: Mapped[UuidFK] = mapped_column(ForeignKey("workflow_runs.id", ondelete="CASCADE"))

    ticker: Mapped[str] = mapped_column(String(16))
    company_name: Mapped[str] = mapped_column(String(255))
    market_cap: Mapped[Decimal] = mapped_column(Numeric(20, 2))
    earnings_date: Mapped[date] = mapped_column(Date)
    earnings_timing: Mapped[str | None] = mapped_column(String(8), nullable=True)  # BMO/AMC

    current_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    direction_classification: Mapped[str] = mapped_column(String(16))  # bullish/bearish/neutral
    candidate_direction_score: Mapped[int] = mapped_column(Integer)

    best_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)
    final_opportunity_score: Mapped[int] = mapped_column(Integer)
    data_confidence_score: Mapped[int] = mapped_column(Integer)
    selected_for_final: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[CreatedAt]

    run: Mapped[WorkflowRun] = relationship(back_populates="candidates", foreign_keys=[run_id])
    option_contracts: Mapped[list[OptionContract]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
