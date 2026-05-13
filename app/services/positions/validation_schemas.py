from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ValidationAction = Literal[
    "hold",
    "adjust_target",
    "adjust_stop",
    "close",
    "insufficient_data",
]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ValidationEvidence(_Frozen):
    code: str
    observation: str
    significance: Literal["material", "marginal"]
    source_ref: str | None = None


class ProposedAdjustment(_Frozen):
    target_option_price: Decimal | None = None
    stop_loss_option_price: Decimal | None = None
    underlying_stop_price: Decimal | None = None
    reason: str


class StructuredPositionValidation(_Frozen):
    action: ValidationAction
    confidence_band: Literal["low", "standard", "strong"]
    evidence: list[ValidationEvidence] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=1200)
    proposed_adjustment: ProposedAdjustment | None = None


class PositionValidationInput(_Frozen):
    trigger: Literal["manual", "auto"]
    trigger_codes: list[str] = Field(default_factory=list)
    position: dict[str, Any]
    thesis: dict[str, Any]
    active_plan: dict[str, Any]
    current_snapshot: dict[str, Any]
    drift_snapshot: dict[str, Any]
    fired_criteria: list[dict[str, Any]] = Field(default_factory=list)
    data_quality: list[str] = Field(default_factory=list)
    new_headlines: list[dict[str, Any]] = Field(default_factory=list)
