from __future__ import annotations

# Import scoring eagerly to avoid a latent circular-import between
# ``app.services.sizing`` and ``app.scoring`` when the telegram templates
# package is the first thing to pull in scoring transitively.
import app.scoring  # noqa: F401
from app.services.strategy_catalog import build_strategy_report
from app.telegram.templates.run_summary import render_strategy_status_rows
from app.telegram.tone import assert_clean
from tests.fixtures.balanced_25_pool import STRATEGIES


def _success_reports() -> tuple:
    return tuple(
        build_strategy_report(
            strategy,
            status="success",
            raw_row_count=5,
            candidate_count=5,
            finviz_candidate_count=0 if strategy == "activist_13d_followthrough" else 5,
            backup_candidate_count=5 if strategy == "activist_13d_followthrough" else 0,
        )
        for strategy in STRATEGIES
    )


def test_renders_five_strategy_rows() -> None:
    rendered = render_strategy_status_rows(_success_reports())

    lines = rendered.splitlines()
    # header + blank + 5 strategy rows
    assert len(lines) == 2 + 5
    assert lines[0] == "<b>Strategy scan summary</b>"
    assert lines[1] == ""

    # All five strategy labels should appear
    body = "\n".join(lines[2:])
    for label in (
        "Strategy A - Catalyst Confluence",
        "Strategy B - Coiled Setup",
        "Strategy C - PEAD Continuation",
        "Strategy D - Sector Relative Strength",
        "Strategy E - Activist 13D Follow-Through",
    ):
        assert label in body

    # Renderer output must pass the global tone gate (CLAUDE.md tone-gate rule).
    assert_clean(rendered)


def test_renders_mixed_statuses_with_appropriate_icons() -> None:
    reports = (
        build_strategy_report(
            "catalyst_confluence",
            status="success",
            raw_row_count=5,
            candidate_count=5,
        ),
        build_strategy_report(
            "coiled_setup",
            status="empty",
            raw_row_count=0,
            candidate_count=0,
        ),
        build_strategy_report(
            "pead_continuation",
            status="failed",
            raw_row_count=0,
            candidate_count=0,
            error="screen failed",
        ),
        build_strategy_report(
            "sector_relative_strength",
            status="fallback",
            raw_row_count=3,
            candidate_count=3,
            backup_candidate_count=3,
            fallback_used=True,
        ),
        build_strategy_report(
            "activist_13d_followthrough",
            status="success",
            raw_row_count=4,
            candidate_count=4,
            backup_candidate_count=4,
        ),
    )

    rendered = render_strategy_status_rows(reports)

    assert "✅ <b>Strategy A - Catalyst Confluence</b> — success (5 cand.)" in rendered
    assert "⚪️ <b>Strategy B - Coiled Setup</b> — empty (no candidates)" in rendered
    assert "⚠️ <b>Strategy C - PEAD Continuation</b> — failed (no candidates)" in rendered
    assert "♻️ <b>Strategy D - Sector Relative Strength</b> — fallback (3 cand.)" in rendered
    assert "✅ <b>Strategy E - Activist 13D Follow-Through</b> — success (4 cand.)" in rendered


def test_renders_empty_reports_gracefully() -> None:
    rendered = render_strategy_status_rows(())
    assert "No strategies were run in this scan." in rendered
