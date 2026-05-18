from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.db.repositories.recommendation_repo import RecommendationRepository
from app.db.repositories.run_repo import WorkflowRunRepository
from app.db.repositories.user_repo import UserRepository
from app.db.session import get_sessionmaker
from app.pipeline.orchestrator import (
    PipelineOrchestrator,
    build_user_context,
    select_decision_finalists,
)
from app.pipeline.steps.decide import HeuristicDecisionStep, build_decision_input
from app.scheduler.jobs import WorkflowRunner
from app.services.logging_service import LoggingService
from app.services.market_hours import NEW_YORK_TZ, is_market_open
from app.services.qa_export_service import (
    QAArtifactMetadata,
    QAExportService,
    QAInputSnapshot,
)
from app.services.qa_replay_service import (
    capture_replay_input,
    compare_replay_results,
    replay_input_from_json,
    replay_input_to_json,
    replay_result_to_json,
    run_replay,
)
from app.services.qa_runtime import (
    NoopNotifier,
    ensure_qa_user,
    get_qa_runtime_secrets,
    qa_day_dir,
    qa_reference_datetime,
    qa_reference_trading_date,
)
from app.services.run_lock import get_run_lock_service


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the intraday QA harness once.")
    parser.add_argument(
        "--reference-dt",
        help="Override the run reference timestamp in ISO-8601 format.",
    )
    parser.add_argument(
        "--skip-replay",
        action="store_true",
        help="Skip the deterministic replay lanes.",
    )
    return parser.parse_args()


async def _main() -> int:
    args = _parse_args()
    settings = get_settings()
    secrets = get_qa_runtime_secrets(settings, require_all=True)
    reference_dt = qa_reference_datetime(
        None if args.reference_dt is None else datetime.fromisoformat(args.reference_dt)
    )
    trading_date = qa_reference_trading_date(reference_dt)
    day_dir = qa_day_dir(settings=settings, reference_dt=reference_dt)
    day_dir.mkdir(parents=True, exist_ok=True)
    slot_prefix = reference_dt.astimezone(NEW_YORK_TZ).strftime("%H%M%S")

    if not is_market_open(reference_dt):
        slot_dir = day_dir / f"{slot_prefix}_market_closed"
        slot_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            slot_dir / "manifest.json",
            {
                "status": "market_closed",
                "reference_dt_utc": reference_dt.isoformat(),
                "reference_trading_date": trading_date.isoformat(),
                "slot_dir": str(slot_dir.resolve()),
            },
        )
        print("status=market_closed")
        print(f"manifest={slot_dir / 'manifest.json'}")
        return 0

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        user = await ensure_qa_user(session, settings=settings)
        await session.commit()
        qa_user_id = user.id

    async def pipeline(session, run) -> None:
        run_dir = day_dir / f"{slot_prefix}_{str(run.id)[:8]}"
        run_dir.mkdir(parents=True, exist_ok=True)
        logging_service = LoggingService(
            archive_root=run_dir,
            results_root=run_dir / "results",
            append_run_id=False,
        )
        orchestrator = PipelineOrchestrator(
            notifier=NoopNotifier(),
            logging_service=logging_service,
            user_secrets_resolver=lambda _: secrets.as_user_secrets(),
        )
        try:
            outcome = await orchestrator.run(
                session,
                run,
                reference_dt=reference_dt,
            )
            user = await UserRepository(session).get(run.user_id)
            if user is None:
                raise LookupError(f"QA user {run.user_id} disappeared during the run")

            recommendation = (
                None
                if run.final_recommendation_id is None
                else await RecommendationRepository(session).get(run.final_recommendation_id)
            )
            metadata = QAArtifactMetadata(
                run_id=run.id,
                lane="live",
                reference_dt_utc=reference_dt,
                reference_trading_date=trading_date,
                qa_user_id=str(user.id),
                qa_user_chat_id=user.telegram_chat_id,
            )
            inputs = QAInputSnapshot(
                account_size=user.account_size,
                risk_profile=user.risk_profile,
                timezone_label=user.timezone_label,
                timezone_iana=user.timezone_iana,
                broker=user.broker,
                strategy_permission=user.strategy_permission,
                max_contracts=user.max_contracts,
                openrouter_key_present=bool(secrets.openrouter_api_key),
                alpha_vantage_key_present=bool(secrets.alpha_vantage_api_key),
                alpaca_key_present=bool(secrets.alpaca_api_key),
                alpaca_secret_present=bool(secrets.alpaca_api_secret),
            )
            decision_candidates = select_decision_finalists(list(outcome.candidates))
            qa_csv_dir = run_dir / "qa_csv"
            qa_paths = QAExportService(results_root=qa_csv_dir).export_run(
                run=run,
                user=user,
                outcome=outcome,
                recommendation=recommendation,
                decision_candidates=decision_candidates,
                metadata=metadata,
                inputs=inputs,
            )
            user_context = build_user_context(
                user,
                has_valid_openrouter_api_key=bool(secrets.openrouter_api_key),
            )
            actual_decision_payload = {
                "engine": outcome.decision_trace.engine,
                "heavy_model_used": outcome.decision_trace.heavy_model_used,
                "notes": list(outcome.decision_trace.notes),
                "decision": outcome.decision.model_dump(mode="json"),
            }
            decision_input = build_decision_input(decision_candidates, user_context)
            heuristic = await HeuristicDecisionStep().execute(
                decision_candidates,
                user_context,
                openrouter_api_key="",
            )
            heuristic_payload = {
                "engine": heuristic.trace.engine,
                "heavy_model_used": heuristic.trace.heavy_model_used,
                "notes": list(heuristic.trace.notes),
                "decision": heuristic.decision.model_dump(mode="json"),
            }
            _write_json(run_dir / "decision_input.json", decision_input.model_dump(mode="json"))
            _write_json(run_dir / "decision_output.json", actual_decision_payload)
            _write_json(run_dir / "heuristic_decision_output.json", heuristic_payload)

            for item in outcome.candidates:
                logging_service.write_news_brief(
                    run_id=run.id,
                    ticker=item.record.ticker,
                    brief=item.news_bundle.model_dump(mode="json"),
                )
                logging_service.write_scoring_snapshot(
                    run_id=run.id,
                    ticker=item.record.ticker,
                    snapshot=_scoring_snapshot(item),
                )

            replay_input = capture_replay_input(
                outcome=outcome,
                user=user,
                reference_dt=reference_dt,
                has_openrouter_key=bool(secrets.openrouter_api_key),
            )
            _write_text(run_dir / "replay_input.json", replay_input_to_json(replay_input))

            replay_consistent: bool | None = None
            replay_skipped = bool(args.skip_replay)
            replay_paths: dict[str, Path] = {"replay_input": run_dir / "replay_input.json"}
            if not args.skip_replay:
                replay_one = await run_replay(replay_input, lane="replay_1")
                replay_paths["replay_1"] = run_dir / "replay_1.json"
                _write_text(replay_paths["replay_1"], replay_result_to_json(replay_one))

                replay_roundtrip = replay_input_from_json(
                    replay_paths["replay_input"].read_text(encoding="utf-8")
                )
                replay_two = await run_replay(replay_roundtrip, lane="replay_2")
                replay_paths["replay_2"] = run_dir / "replay_2.json"
                _write_text(replay_paths["replay_2"], replay_result_to_json(replay_two))

                replay_diff = compare_replay_results(replay_one, replay_two)
                replay_paths["replay_diff"] = run_dir / "replay_diff.json"
                _write_json(replay_paths["replay_diff"], replay_diff)
                replay_consistent = bool(replay_diff["matches"])

            files = {
                "decision_input": run_dir / "decision_input.json",
                "decision_output": run_dir / "decision_output.json",
                "heuristic_decision_output": run_dir / "heuristic_decision_output.json",
                **qa_paths,
                **replay_paths,
            }
            for json_path in (
                run_dir / "run_summary.json",
                run_dir / "candidate_cards.json",
                run_dir / "option_contracts.json",
                run_dir / "recommendation_card.json",
                run_dir / "telegram_message.txt",
            ):
                if json_path.exists():
                    files[json_path.stem] = json_path
            for exported in (run_dir / "results").glob("*.csv"):
                files[f"results_{exported.stem}"] = exported

            manifest = {
                "run_id": str(run.id),
                "qa_user_id": str(user.id),
                "qa_user_chat_id": user.telegram_chat_id,
                "reference_dt_utc": reference_dt.isoformat(),
                "reference_trading_date": trading_date.isoformat(),
                "status": run.status,
                "decision_action": outcome.decision.action,
                "selected_ticker": outcome.decision.chosen_ticker,
                "decision_engine": outcome.decision_trace.engine,
                "replay_consistent": replay_consistent,
                "replay_skipped": replay_skipped,
                "slot_dir": str(run_dir.resolve()),
                "files": {name: str(path.resolve()) for name, path in files.items()},
                "hashes": {name: _sha256(path) for name, path in files.items() if path.exists()},
            }
            _write_json(run_dir / "manifest.json", manifest)
        except Exception as exc:
            failure_manifest = {
                "run_id": str(run.id),
                "reference_dt_utc": reference_dt.isoformat(),
                "reference_trading_date": trading_date.isoformat(),
                "status": "failed",
                "error": str(exc),
                "slot_dir": str((day_dir / f"{slot_prefix}_{str(run.id)[:8]}").resolve()),
            }
            _write_json(day_dir / f"{slot_prefix}_{str(run.id)[:8]}" / "manifest.json", failure_manifest)
            raise

    runner = WorkflowRunner(
        sessionmaker,
        get_run_lock_service(),
        pipeline=pipeline,
    )
    result = await runner.run_workflow(qa_user_id, trigger_type="qa_intraday")

    if result.outcome == "already_running":
        slot_dir = day_dir / f"{slot_prefix}_already_running"
        slot_dir.mkdir(parents=True, exist_ok=True)
        _write_json(
            slot_dir / "manifest.json",
            {
                "status": "already_running",
                "reference_dt_utc": reference_dt.isoformat(),
                "reference_trading_date": trading_date.isoformat(),
                "qa_user_id": str(qa_user_id),
                "slot_dir": str(slot_dir.resolve()),
            },
        )
        print("status=already_running")
        print(f"manifest={slot_dir / 'manifest.json'}")
        return 0

    if result.outcome == "failed":
        async with sessionmaker() as session:
            run = None if result.run_id is None else await WorkflowRunRepository(session).get(result.run_id)
            slot_dir = day_dir / f"{slot_prefix}_{'' if result.run_id is None else str(result.run_id)[:8]}"
            slot_dir.mkdir(parents=True, exist_ok=True)
            _write_json(
                slot_dir / "manifest.json",
                {
                    "run_id": "" if result.run_id is None else str(result.run_id),
                    "status": "failed",
                    "reference_dt_utc": reference_dt.isoformat(),
                    "reference_trading_date": trading_date.isoformat(),
                    "error": result.error_message,
                    "workflow_error": None if run is None else run.error_message,
                    "slot_dir": str(slot_dir.resolve()),
                },
            )
        print("status=failed")
        print(f"run_id={result.run_id}")
        print(f"error={result.error_message}")
        return 1

    run_dir = day_dir / f"{slot_prefix}_{str(result.run_id)[:8]}"
    print("status=success")
    print(f"run_id={result.run_id}")
    print(f"manifest={run_dir / 'manifest.json'}")
    return 0


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _write_text(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(payload, encoding="utf-8")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scoring_snapshot(candidate) -> dict[str, Any]:
    chosen = candidate.evaluation.chosen_contract
    return {
        "ticker": candidate.record.ticker,
        "strategy_source": candidate.record.strategy_source,
        "final_score": candidate.evaluation.final_score,
        "candidate_action": candidate.evaluation.action,
        "direction": {
            "classification": candidate.evaluation.direction.classification,
            "bias": str(candidate.evaluation.direction.bias),
            "score": candidate.evaluation.direction.score,
            "factors": [
                {
                    "name": factor.name,
                    "score": factor.score,
                    "weight": factor.weight,
                    "detail": factor.detail,
                }
                for factor in candidate.evaluation.direction.factors
            ],
            "reasons": list(candidate.evaluation.direction.reasons),
        },
        "confidence": {
            "score": candidate.evaluation.confidence.score,
            "label": candidate.evaluation.confidence.label,
            "blockers": list(candidate.evaluation.confidence.blockers),
            "notes": list(candidate.evaluation.confidence.notes),
        },
        "chosen_contract": None
        if chosen is None
        else {
            "strategy": chosen.strategy,
            "score": chosen.score,
            "strike": format(chosen.contract.strike, "f"),
            "expiry": chosen.contract.expiry.isoformat(),
            "option_type": chosen.contract.option_type,
            "position_side": chosen.contract.position_side,
            "vetoes": [veto.reason for veto in chosen.vetoes],
        },
        "reasons": list(candidate.evaluation.reasons),
        "calculation_errors": list(candidate.context.calculation_errors),
    }


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
