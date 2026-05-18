from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace

from app.telegram.templates.validation import render_validation_history, render_validation_result


def _position():
    return SimpleNamespace(entry_price=Decimal("1.25"))


def _recommendation():
    return SimpleNamespace(
        ticker="AMD",
        strike=Decimal("104.00"),
        option_type="call",
        expiry=date(2026, 5, 16),
        target_option_price=Decimal("2.00"),
        stop_loss_option_price=Decimal("0.50"),
    )


def _validation(**overrides):
    defaults = {
        "llm_action_final": "hold",
        "llm_confidence_band": "standard",
        "trigger_codes_json": [],
        "llm_evidence_json": [
            {
                "code": "drift_signal:no_breach",
                "observation": "No kill or degrade criteria fired.",
                "significance": "marginal",
            }
        ],
        "llm_summary": "The thesis remains intact.",
        "current_underlying_price": Decimal("101.00"),
        "current_option_premium": Decimal("1.20"),
        "proposed_adjustment_json": None,
        "fired_at": datetime(2026, 5, 15, 14, 30, tzinfo=UTC),
        "trigger": "manual",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_validation_result_renders_hold_in_plain_language() -> None:
    message = render_validation_result(_validation(), _position(), _recommendation())

    assert "Decision: Hold" in message
    assert "No thesis break" in message
    assert "INSUFFICIENT DATA" not in message
    assert "Option exit premium: $1.20" in message


def test_validation_result_renders_insufficient_data_as_could_not_verify() -> None:
    message = render_validation_result(
        _validation(
            llm_action_final="insufficient_data",
            llm_confidence_band="low",
            llm_evidence_json=[
                {
                    "code": "data_quality:insufficient_supported_evidence",
                    "observation": "No supported evidence mapped to supplied drift data.",
                    "significance": "material",
                }
            ],
            current_underlying_price=None,
            current_option_premium=None,
            llm_summary="The review could not verify the thesis.",
        ),
        _position(),
        _recommendation(),
    )

    assert "Decision: Could not verify" in message
    assert "not a close or hold instruction" in message
    assert "Target, stop, exit-date, and expiry alerts continue to run." in message
    assert "Underlying: N/A" in message


def test_validation_result_renders_adjustment_action() -> None:
    message = render_validation_result(
        _validation(
            llm_action_final="adjust_stop",
            proposed_adjustment_json={
                "stop_loss_option_price": "0.75",
                "reason": "Tighten risk while the thesis is still marginally intact.",
            },
        ),
        _position(),
        _recommendation(),
    )

    assert "Decision: Adjust stop" in message
    assert "Suggested adjustment" in message
    assert "Stop: $0.75" in message


def test_validation_history_uses_ascii_separators() -> None:
    message = render_validation_history(
        [
            _validation(
                llm_action_final="insufficient_data",
                trigger_codes_json=["data_unavailable"],
            )
        ]
    )

    assert "Could not verify" in message
    assert " - " in message
    assert "\u00c2" not in message
    assert "\u00e2" not in message
