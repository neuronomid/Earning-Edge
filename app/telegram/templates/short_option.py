from __future__ import annotations

from typing import Protocol

from app.services.sizing import BROKER_MARGIN_DEPENDENT_TEXT, SHORT_CALL_MAX_LOSS_TEXT


class RecommendationLike(Protocol):
    ticker: str
    option_type: str
    position_side: str
    estimated_max_loss: str


def contract_label(recommendation: RecommendationLike) -> str:
    option_name = recommendation.option_type.capitalize()
    if recommendation.position_side == "short":
        return f"{recommendation.ticker} Short {option_name}"
    return f"{recommendation.ticker} {option_name}"


def max_loss_display(recommendation: RecommendationLike) -> str:
    if recommendation.position_side != "short":
        return recommendation.estimated_max_loss
    if recommendation.option_type == "call":
        return SHORT_CALL_MAX_LOSS_TEXT
    return BROKER_MARGIN_DEPENDENT_TEXT
