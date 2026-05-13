from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from app.db.models.position_plan_override import PositionPlanOverride
from app.db.models.recommendation import Recommendation


@dataclass(frozen=True, slots=True)
class ActivePositionPlan:
    target_option_price: Decimal | None
    stop_loss_option_price: Decimal | None
    underlying_stop_price: Decimal | None
    source: str = "recommendation"

    @property
    def is_adjusted(self) -> bool:
        return self.source != "recommendation"


def active_position_plan(
    recommendation: Recommendation,
    override: PositionPlanOverride | None = None,
) -> ActivePositionPlan:
    if override is None:
        return ActivePositionPlan(
            target_option_price=recommendation.target_option_price,
            stop_loss_option_price=recommendation.stop_loss_option_price,
            underlying_stop_price=getattr(recommendation, "underlying_stop_price", None),
        )
    return ActivePositionPlan(
        target_option_price=override.target_option_price,
        stop_loss_option_price=override.stop_loss_option_price,
        underlying_stop_price=override.underlying_stop_price,
        source=override.source,
    )
