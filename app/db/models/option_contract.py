from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.models._columns import CreatedAt, UuidFK, UuidPK

if TYPE_CHECKING:
    from app.db.models.candidate import Candidate


class OptionContract(Base):
    __tablename__ = "option_contracts"

    id: Mapped[UuidPK]
    candidate_id: Mapped[UuidFK] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE")
    )

    ticker: Mapped[str] = mapped_column(String(16))
    option_type: Mapped[str] = mapped_column(String(8))  # call/put
    position_side: Mapped[str] = mapped_column(String(8))  # long/short

    strike: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    expiry: Mapped[date] = mapped_column(Date)

    bid: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    ask: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    mid: Mapped[Decimal] = mapped_column(Numeric(14, 4))

    volume: Mapped[int | None] = mapped_column(Integer, nullable=True)
    open_interest: Mapped[int | None] = mapped_column(Integer, nullable=True)

    implied_volatility: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)
    delta: Mapped[Decimal | None] = mapped_column(Numeric(10, 6), nullable=True)

    breakeven: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    spread_percent: Mapped[Decimal] = mapped_column(Numeric(8, 4))
    liquidity_score: Mapped[int] = mapped_column(Integer)
    contract_opportunity_score: Mapped[int] = mapped_column(Integer)

    passed_hard_filters: Mapped[bool] = mapped_column(Boolean, default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[CreatedAt]

    candidate: Mapped[Candidate] = relationship(back_populates="option_contracts")
