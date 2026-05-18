from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.config import get_settings
from app.db.models.user import User
from app.services.qa_compare_service import QACompareService


def _fixture_user() -> User:
    return User(
        telegram_chat_id="qa-fixture",
        account_size=Decimal("10000"),
        risk_profile="Balanced",
        broker="Wealthsimple",
        timezone_label="ET",
        timezone_iana="America/Toronto",
        strategy_permission="long_and_short",
        max_contracts=3,
        openrouter_api_key_encrypted="fixture",
    )


@dataclass(slots=True)
class RecordingOptionsStep:
    chains: dict[str, tuple] = field(default_factory=dict)
    calls: list[tuple[str, date | None]] = field(default_factory=list)

    async def execute(
        self,
        record,
        *,
        alpaca_api_key: str | None,
        alpaca_api_secret: str | None,
        strategy_permission: str,
        today: date | None = None,
    ) -> tuple:
        del alpaca_api_key, alpaca_api_secret, strategy_permission
        self.calls.append((record.ticker, today))
        return self.chains.get(record.ticker, ())


@pytest.mark.asyncio
async def test_pipeline_threads_frozen_trading_date_into_options() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.pipeline.orchestrator import PipelineOrchestrator, UserSecrets
    from app.services.market_hours import trading_reference_date
    from tests.e2e.testkit import (
        FakeScoringStep,
        ScoringPlan,
        StaticMarketDataStep,
        StaticNewsStep,
        make_batch,
        make_news_bundle,
        make_snapshot,
    )

    batch = make_batch(rows=(("AMD", 900, 102),))
    record = batch.candidates[0]
    options_step = RecordingOptionsStep()
    orchestrator = PipelineOrchestrator(
        market_data_step=StaticMarketDataStep({record.ticker: make_snapshot(record)}),
        news_step=StaticNewsStep({record.ticker: make_news_bundle(record)}),
        options_step=options_step,
        scoring_step=FakeScoringStep(
            {record.ticker: ScoringPlan("no_trade", 55, "neutral")}
        ),
        user_secrets_resolver=lambda _: UserSecrets(
            openrouter_api_key="present",
            alpha_vantage_api_key=None,
            alpaca_api_key=None,
            alpaca_api_secret=None,
        ),
    )
    reference_dt = datetime(2026, 5, 15, 1, 0, tzinfo=UTC)
    expected_today = trading_reference_date(reference_dt)

    await orchestrator.evaluate_batch(
        batch,
        _fixture_user(),
        reference_dt=reference_dt,
    )

    assert expected_today != reference_dt.date()
    assert options_step.calls == [
        (record.ticker, expected_today),
        (record.ticker, expected_today),
    ]


@pytest.mark.asyncio
async def test_qa_replay_roundtrip_is_deterministic() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.pipeline.orchestrator import PipelineOrchestrator, UserSecrets
    from app.services.qa_replay_service import (
        capture_replay_input,
        compare_replay_results,
        replay_input_from_json,
        replay_input_to_json,
        run_replay,
    )
    from tests.fixtures.balanced_25_pool import (
        BalancedMarketDataStep,
        BalancedNewsStep,
        BalancedOptionsStep,
        build_balanced_batch,
        build_balanced_index,
    )

    batch = build_balanced_batch(successes=("catalyst_confluence",))
    index = build_balanced_index(successes=("catalyst_confluence",))
    reference_dt = datetime(2026, 5, 1, 16, 0, tzinfo=UTC)
    orchestrator = PipelineOrchestrator(
        market_data_step=BalancedMarketDataStep(index),
        news_step=BalancedNewsStep(index),
        options_step=BalancedOptionsStep(index),
        user_secrets_resolver=lambda _: UserSecrets(
            openrouter_api_key="",
            alpha_vantage_api_key=None,
            alpaca_api_key=None,
            alpaca_api_secret=None,
        ),
    )

    outcome = await orchestrator.evaluate_batch(
        batch,
        _fixture_user(),
        reference_dt=reference_dt,
    )
    replay_input = capture_replay_input(
        outcome=outcome,
        user=_fixture_user(),
        reference_dt=reference_dt,
        has_openrouter_key=False,
    )

    payload = replay_input_to_json(replay_input)
    replay_roundtrip = replay_input_from_json(payload)
    replay_one = await run_replay(replay_input, lane="replay_1")
    replay_two = await run_replay(replay_roundtrip, lane="replay_2")
    diff = compare_replay_results(replay_one, replay_two)

    assert replay_roundtrip.reference_dt_utc == replay_input.reference_dt_utc
    assert replay_roundtrip.reference_trading_date == replay_input.reference_trading_date
    assert diff["matches"] is True
    assert diff["differences"] == []


def test_compare_day_writes_reports_and_classifies_drift(tmp_path: Path) -> None:
    day_dir = tmp_path / "2026-05-15"
    day_dir.mkdir()

    _write_slot(
        day_dir,
        slot="093000_run1",
        reference_dt="2026-05-15T13:30:00+00:00",
        run_id="run-1",
        hashes={
            "market": "market-a",
            "scoring": "scoring-a",
            "decision_output": "decision-a",
            "heuristic_decision_output": "heuristic-a",
        },
        scoring_rows=[
            {
                "ticker": "AMD",
                "final_opportunity_score": "80",
                "data_confidence_score": "88",
                "direction_score": "79",
                "candidate_action": "recommend",
            }
        ],
    )
    _write_slot(
        day_dir,
        slot="095000_run2",
        reference_dt="2026-05-15T13:50:00+00:00",
        run_id="run-2",
        hashes={
            "market": "market-b",
            "scoring": "scoring-a",
            "decision_output": "decision-a",
            "heuristic_decision_output": "heuristic-a",
        },
        scoring_rows=[
            {
                "ticker": "AMD",
                "final_opportunity_score": "82",
                "data_confidence_score": "89",
                "direction_score": "81",
                "candidate_action": "recommend",
            }
        ],
    )
    _write_slot(
        day_dir,
        slot="101000_run3",
        reference_dt="2026-05-15T14:10:00+00:00",
        run_id="run-3",
        hashes={
            "market": "market-b",
            "scoring": "scoring-a",
            "decision_output": "decision-b",
            "heuristic_decision_output": "heuristic-a",
        },
        scoring_rows=[
            {
                "ticker": "AMD",
                "final_opportunity_score": "82",
                "data_confidence_score": "89",
                "direction_score": "81",
                "candidate_action": "recommend",
            }
        ],
    )
    _write_slot(
        day_dir,
        slot="103000_run4",
        reference_dt="2026-05-15T14:30:00+00:00",
        run_id="run-4",
        hashes={
            "market": "market-b",
            "scoring": "scoring-a",
            "decision_output": "decision-b",
            "heuristic_decision_output": "heuristic-a",
        },
        scoring_rows=[
            {
                "ticker": "AMD",
                "final_opportunity_score": "82",
                "data_confidence_score": "89",
                "direction_score": "81",
                "candidate_action": "recommend",
            }
        ],
        replay_consistent=False,
    )

    comparison = QACompareService().compare_day(day_dir=day_dir)

    assert comparison.summary_csv.exists()
    assert comparison.adjacent_diffs_csv.exists()
    assert comparison.candidate_score_diffs_csv.exists()
    assert comparison.daily_report_md.exists()

    with comparison.adjacent_diffs_csv.open("r", encoding="utf-8", newline="") as handle:
        adjacent = list(csv.DictReader(handle))
    assert [row["classification"] for row in adjacent] == [
        "market_data_drift",
        "decision_layer_drift",
        "determinism_regression",
    ]

    with comparison.candidate_score_diffs_csv.open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        candidate_diffs = list(csv.DictReader(handle))
    assert candidate_diffs[0]["ticker"] == "AMD"
    assert candidate_diffs[0]["before_final_score"] == "80"
    assert candidate_diffs[0]["after_final_score"] == "82"

    report = comparison.daily_report_md.read_text(encoding="utf-8")
    assert "market_data_drift" in report
    assert "decision_layer_drift" in report
    assert "determinism_regression" in report


def test_get_qa_runtime_secrets_requires_all_keys() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.services.qa_runtime import get_qa_runtime_secrets

    settings = get_settings().model_copy(
        update={
            "qa_openrouter_api_key": "",
            "qa_alpha_vantage_api_key": "",
            "qa_alpaca_api_key": "",
            "qa_alpaca_api_secret": "",
        }
    )

    with pytest.raises(ValueError, match="Missing QA credentials in .env"):
        get_qa_runtime_secrets(settings=settings, require_all=True)


def test_get_qa_runtime_secrets_partial_allowed_when_not_required() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.services.qa_runtime import get_qa_runtime_secrets

    settings = get_settings().model_copy(
        update={
            "qa_openrouter_api_key": "  router-key  ",
            "qa_alpha_vantage_api_key": "",
            "qa_alpaca_api_key": "",
            "qa_alpaca_api_secret": "",
        }
    )

    secrets = get_qa_runtime_secrets(settings=settings, require_all=False)

    # Whitespace stripped, optional fields left empty.
    assert secrets.openrouter_api_key == "router-key"
    assert secrets.alpha_vantage_api_key == ""
    assert secrets.alpaca_api_key == ""
    assert secrets.alpaca_api_secret == ""

    user_secrets = secrets.as_user_secrets()
    assert user_secrets.openrouter_api_key == "router-key"
    assert user_secrets.alpha_vantage_api_key is None
    assert user_secrets.alpaca_api_key is None
    assert user_secrets.alpaca_api_secret is None


def test_qa_reference_datetime_normalizes_inputs() -> None:
    pytest.importorskip("pandas_market_calendars")

    from zoneinfo import ZoneInfo

    from app.services.qa_runtime import qa_reference_datetime

    aware = qa_reference_datetime(
        datetime(2026, 5, 15, 9, 30, tzinfo=ZoneInfo("America/New_York"))
    )
    assert aware.tzinfo == UTC
    assert aware == datetime(2026, 5, 15, 13, 30, tzinfo=UTC)

    naive = qa_reference_datetime(datetime(2026, 5, 15, 13, 30))
    assert naive.tzinfo == UTC
    assert naive == datetime(2026, 5, 15, 13, 30, tzinfo=UTC)

    default = qa_reference_datetime()
    assert default.tzinfo == UTC


def test_qa_reference_trading_date_rolls_after_hours_utc() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.services.qa_runtime import qa_reference_trading_date

    # 2026-05-15T01:00:00Z is still the evening of 2026-05-14 in NY.
    rolled = qa_reference_trading_date(datetime(2026, 5, 15, 1, 0, tzinfo=UTC))
    assert rolled == date(2026, 5, 14)


def test_qa_day_dir_uses_new_york_calendar_date(tmp_path: Path) -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.services.qa_runtime import qa_day_dir

    settings = get_settings().model_copy(update={"qa_root_dir": str(tmp_path)})

    # 2026-05-15T01:00Z is 2026-05-14 in America/New_York.
    day_dir = qa_day_dir(
        settings=settings,
        reference_dt=datetime(2026, 5, 15, 1, 0, tzinfo=UTC),
    )
    assert day_dir == tmp_path / "2026-05-14"

    midday = qa_day_dir(
        settings=settings,
        reference_dt=datetime(2026, 5, 15, 16, 0, tzinfo=UTC),
    )
    assert midday == tmp_path / "2026-05-15"


@pytest.mark.asyncio
async def test_noop_notifier_returns_none() -> None:
    pytest.importorskip("pandas_market_calendars")

    from app.services.qa_runtime import NoopNotifier

    notifier = NoopNotifier()
    assert await notifier.send_text("qa", "hello") is None
    assert await notifier.send_text("qa", "hello", reply_markup={"x": 1}) is None


def _write_slot(
    day_dir: Path,
    *,
    slot: str,
    reference_dt: str,
    run_id: str,
    hashes: dict[str, str],
    scoring_rows: list[dict[str, str]],
    replay_consistent: bool | None = True,
    replay_skipped: bool = False,
) -> None:
    slot_dir = day_dir / slot
    slot_dir.mkdir(parents=True, exist_ok=True)
    scoring_path = slot_dir / "scoring.csv"
    _write_scoring_csv(scoring_path, scoring_rows)
    manifest = {
        "run_id": run_id,
        "reference_dt_utc": reference_dt,
        "status": "success",
        "decision_action": "recommend",
        "selected_ticker": "AMD",
        "decision_engine": "heuristic",
        "replay_consistent": replay_consistent,
        "replay_skipped": replay_skipped,
        "files": {"scoring": str(scoring_path)},
        "hashes": hashes,
    }
    (slot_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_scoring_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
