from __future__ import annotations

from types import SimpleNamespace

from app.services.positions.thesis_builder import (
    _catalyst_baseline,
    _catalyst_kind,
    _strategy_specific_criteria,
)


def test_activist_13d_baseline_extracts_sec_validation_notes() -> None:
    recommendation = SimpleNamespace(earnings_date=None)
    candidate_card = {
        "candidate_sources": ["sec_edgar"],
        "candidate_origin": "backup_source",
        "event_signal_detail": "Fresh SC 13D from Elliott, active intent",
        "event_signal_score": 82,
        "event_signal_supportive": True,
        "validation_notes": [
            "SC_13D_ACCESSION=0001234567-26-000123",
            "SC_13D_URL=https://www.sec.gov/Archives/example.txt",
            "Activist 13D filer: Elliott",
        ],
    }

    baseline = _catalyst_baseline(
        recommendation=recommendation,
        candidate_card=candidate_card,
        strategy_source="activist_13d_followthrough",
    )

    assert _catalyst_kind("activist_13d_followthrough", recommendation) == "filing"
    assert baseline["strategy_source"] == "activist_13d_followthrough"
    assert baseline["event_signal_score"] == 82
    assert baseline["validation_metadata"]["sc_13d_accession"] == "0001234567-26-000123"
    assert baseline["validation_metadata"]["activist_13d_filer"] == "Elliott"


def test_sector_rs_regime_warning_is_reserved_without_auto_firing() -> None:
    criteria = _strategy_specific_criteria("sector_relative_strength")

    assert criteria[0]["code"] == "sector_regime_warning"
    assert criteria[0]["enabled"] is False
    assert criteria[0]["source"] == "strategy_specific"
