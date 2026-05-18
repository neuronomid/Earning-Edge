from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True, frozen=True)
class QADayComparison:
    summary_csv: Path
    adjacent_diffs_csv: Path
    candidate_score_diffs_csv: Path
    daily_report_md: Path


class QACompareService:
    def compare_day(self, *, day_dir: Path) -> QADayComparison:
        manifests = sorted(
            (_load_manifest(path) for path in day_dir.glob("*/manifest.json")),
            key=lambda item: item.get("reference_dt_utc", ""),
        )
        comparison_dir = day_dir / "comparison"
        comparison_dir.mkdir(parents=True, exist_ok=True)

        summary_csv = comparison_dir / "summary.csv"
        adjacent_diffs_csv = comparison_dir / "adjacent_diffs.csv"
        candidate_score_diffs_csv = comparison_dir / "candidate_score_diffs.csv"
        daily_report_md = comparison_dir / "daily_report.md"

        self._write_summary(summary_csv, manifests)
        adjacent = self._write_adjacent_diffs(adjacent_diffs_csv, manifests)
        self._write_candidate_score_diffs(candidate_score_diffs_csv, manifests)
        self._write_daily_report(daily_report_md, day_dir=day_dir, manifests=manifests, adjacent=adjacent)

        return QADayComparison(
            summary_csv=summary_csv,
            adjacent_diffs_csv=adjacent_diffs_csv,
            candidate_score_diffs_csv=candidate_score_diffs_csv,
            daily_report_md=daily_report_md,
        )

    def _write_summary(self, path: Path, manifests: list[dict[str, Any]]) -> None:
        rows = []
        for manifest in manifests:
            rows.append(
                {
                    "run_id": manifest.get("run_id", ""),
                    "reference_dt_utc": manifest.get("reference_dt_utc", ""),
                    "status": manifest.get("status", ""),
                    "decision_action": manifest.get("decision_action", ""),
                    "selected_ticker": manifest.get("selected_ticker", ""),
                    "decision_engine": manifest.get("decision_engine", ""),
                    "replay_consistent": _replay_state(manifest),
                    "slot_dir": manifest.get("slot_dir", ""),
                }
            )
        _write_csv(path, rows)

    def _write_adjacent_diffs(
        self,
        path: Path,
        manifests: list[dict[str, Any]],
    ) -> list[dict[str, str]]:
        live = [
            manifest
            for manifest in manifests
            if manifest.get("status") in {"success", "no_trade"}
        ]
        rows: list[dict[str, str]] = []
        for left, right in zip(live, live[1:]):
            classification = _classify_adjacent(left, right)
            rows.append(
                {
                    "from_run_id": left.get("run_id", ""),
                    "to_run_id": right.get("run_id", ""),
                    "from_reference_dt_utc": left.get("reference_dt_utc", ""),
                    "to_reference_dt_utc": right.get("reference_dt_utc", ""),
                    "classification": classification,
                    "from_action": left.get("decision_action", ""),
                    "to_action": right.get("decision_action", ""),
                    "from_selected_ticker": left.get("selected_ticker", ""),
                    "to_selected_ticker": right.get("selected_ticker", ""),
                    "changed_hashes": " | ".join(_changed_hashes(left, right)),
                }
            )
        _write_csv(path, rows)
        return rows

    def _write_candidate_score_diffs(
        self,
        path: Path,
        manifests: list[dict[str, Any]],
    ) -> None:
        rows = []
        live = [
            manifest
            for manifest in manifests
            if manifest.get("status") in {"success", "no_trade"}
        ]
        for left, right in zip(live, live[1:]):
            left_scores = _scoring_rows(left)
            right_scores = _scoring_rows(right)
            for ticker in sorted(set(left_scores) | set(right_scores)):
                before = left_scores.get(ticker, {})
                after = right_scores.get(ticker, {})
                if before == after:
                    continue
                rows.append(
                    {
                        "from_run_id": left.get("run_id", ""),
                        "to_run_id": right.get("run_id", ""),
                        "ticker": ticker,
                        "before_final_score": before.get("final_opportunity_score", ""),
                        "after_final_score": after.get("final_opportunity_score", ""),
                        "before_confidence": before.get("data_confidence_score", ""),
                        "after_confidence": after.get("data_confidence_score", ""),
                        "before_direction_score": before.get("direction_score", ""),
                        "after_direction_score": after.get("direction_score", ""),
                        "before_action": before.get("candidate_action", ""),
                        "after_action": after.get("candidate_action", ""),
                    }
                )
        _write_csv(path, rows)

    def _write_daily_report(
        self,
        path: Path,
        *,
        day_dir: Path,
        manifests: list[dict[str, Any]],
        adjacent: list[dict[str, str]],
    ) -> None:
        lines = [
            f"# QA Daily Report - {day_dir.name}",
            "",
            f"Runs captured: {len(manifests)}",
            f"Adjacent comparisons: {len(adjacent)}",
            "",
            "## Run Summary",
        ]
        for manifest in manifests:
            lines.append(
                "- "
                + " | ".join(
                    [
                        manifest.get("reference_dt_utc", ""),
                        manifest.get("status", ""),
                        manifest.get("decision_action", ""),
                        manifest.get("selected_ticker", "") or "(none)",
                        manifest.get("decision_engine", ""),
                    ]
                )
            )
        lines.extend(["", "## Drift Summary"])
        if not adjacent:
            lines.append("- No adjacent live runs were available for comparison.")
        else:
            for row in adjacent:
                lines.append(
                    "- "
                    + " | ".join(
                        [
                            row["from_reference_dt_utc"],
                            row["to_reference_dt_utc"],
                            row["classification"],
                            row["changed_hashes"] or "no_hash_change",
                        ]
                    )
                )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    data["slot_dir"] = str(path.parent)
    return data


def _changed_hashes(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    left_hashes = left.get("hashes", {})
    right_hashes = right.get("hashes", {})
    keys = sorted(set(left_hashes) | set(right_hashes))
    return [key for key in keys if left_hashes.get(key) != right_hashes.get(key)]


def _classify_adjacent(left: dict[str, Any], right: dict[str, Any]) -> str:
    changed = set(_changed_hashes(left, right))
    if _has_determinism_regression(left) or _has_determinism_regression(right):
        return "determinism_regression"
    if "strategies" in changed or "candidates" in changed:
        return "screening_source_drift"
    if "market" in changed:
        return "market_data_drift"
    if "news_summary" in changed or "news_articles" in changed:
        return "news_drift"
    if "options" in changed:
        return "options_data_drift"
    if "scoring" in changed:
        return "determinism_regression"
    if (
        "decision_output" in changed
        and "heuristic_decision_output" not in changed
        and "scoring" not in changed
    ):
        return "decision_layer_drift"
    if changed:
        return "mixed_input_drift"
    return "no_material_change"


def _scoring_rows(manifest: dict[str, Any]) -> dict[str, dict[str, str]]:
    files = manifest.get("files", {})
    scoring_path = files.get("scoring")
    if not scoring_path:
        return {}
    path = Path(scoring_path)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return {row["ticker"]: row for row in reader if row.get("ticker")}


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = []
    seen = set()
    for row in rows:
        for key in row.keys():
            if key in seen:
                continue
            seen.add(key)
            fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if fieldnames:
            writer.writeheader()
            for row in rows:
                writer.writerow({field: row.get(field, "") for field in fieldnames})


def _yesno(value: bool) -> str:
    return "true" if value else "false"


def _replay_state(manifest: dict[str, Any]) -> str:
    if manifest.get("replay_skipped"):
        return "skipped"
    if manifest.get("replay_consistent") is None:
        return ""
    return _yesno(bool(manifest.get("replay_consistent", False)))


def _has_determinism_regression(manifest: dict[str, Any]) -> bool:
    if manifest.get("replay_skipped"):
        return False
    return manifest.get("replay_consistent") is False
