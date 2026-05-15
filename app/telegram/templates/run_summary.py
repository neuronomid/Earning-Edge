from __future__ import annotations

from collections.abc import Iterable

from app.services.candidate_models import StrategyRunReport

_STATUS_ICONS: dict[str, str] = {
    "success": "✅",
    "fallback": "♻️",
    "empty": "⚪️",
    "failed": "⚠️",
}


def render_strategy_status_rows(reports: Iterable[StrategyRunReport]) -> str:
    """Render one row per strategy arm for the post-scan summary card.

    Used by the run-scan-now flow to show the user how each of the five
    strategies fared. Output stays compact: header, then one line per arm
    in the order the orchestrator returned them.
    """
    rows = list(reports)
    lines: list[str] = ["<b>Strategy scan summary</b>", ""]
    if not rows:
        lines.append("No strategies were run in this scan.")
        return "\n".join(lines)

    for report in rows:
        icon = _STATUS_ICONS.get(report.status, "•")
        candidate_text = (
            "no candidates" if report.candidate_count == 0 else f"{report.candidate_count} cand."
        )
        lines.append(f"{icon} <b>{report.strategy_label}</b> — {report.status} ({candidate_text})")
    return "\n".join(lines)
