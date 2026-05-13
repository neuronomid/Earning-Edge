from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.positions.plans import ActivePositionPlan
from app.telegram.templates.positions import render_position_card


def test_position_card_renders_adjusted_plan_values() -> None:
    position = SimpleNamespace(entry_quantity=2, entry_price=Decimal("1.25"))
    recommendation = SimpleNamespace(
        ticker="AMD",
        position_side="long",
        option_type="call",
        expiry=date(2026, 5, 16),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
    )
    plan = ActivePositionPlan(
        target_option_price=Decimal("2.50"),
        stop_loss_option_price=Decimal("0.75"),
        underlying_stop_price=None,
        source="user",
    )

    rendered = render_position_card(position, recommendation, None, plan)

    assert "Target: $2.50 · Stop: $0.75" in rendered
    assert "Plan: adjusted" in rendered
