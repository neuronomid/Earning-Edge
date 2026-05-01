from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(slots=True, frozen=True)
class SizingResult:
    quantity: int
    max_loss_text: str
    account_risk_pct: Decimal
    broker_verification_required: bool
    watch_only: bool
    trade_budget: Decimal | None = None
    max_loss_per_contract: Decimal | None = None
    max_short_notional_exposure: Decimal | None = None
    contract_notional_exposure: Decimal | None = None
    premium_collected: Decimal | None = None
    margin_requirement_text: str | None = None
