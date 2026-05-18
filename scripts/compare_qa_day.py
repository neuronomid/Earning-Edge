from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from app.core.config import get_settings
from app.services.market_hours import NEW_YORK_TZ
from app.services.qa_compare_service import QACompareService
from app.services.qa_runtime import get_qa_runtime_config


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare one day of QA intraday captures.")
    parser.add_argument(
        "--day",
        help="Trading day in YYYY-MM-DD format. Defaults to today in New York.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    settings = get_settings()
    runtime = get_qa_runtime_config(settings)
    if args.day:
        day = args.day
    else:
        day = datetime.now(NEW_YORK_TZ).date().isoformat()
    day_dir = Path(runtime.root_dir) / day
    comparison = QACompareService().compare_day(day_dir=day_dir)
    print(f"summary_csv={comparison.summary_csv}")
    print(f"adjacent_diffs_csv={comparison.adjacent_diffs_csv}")
    print(f"candidate_score_diffs_csv={comparison.candidate_score_diffs_csv}")
    print(f"daily_report_md={comparison.daily_report_md}")


if __name__ == "__main__":
    main()
