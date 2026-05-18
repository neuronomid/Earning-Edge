# QA Intraday Drift Harness

## Summary

Build a production-parity QA harness that runs the real recommendation workflow every 20 minutes during NYSE hours, suppresses Telegram delivery, captures step-level and run-level artifacts, and immediately replays frozen inputs to separate live market drift from application nondeterminism.

The harness uses:

- A dedicated QA user profile
- Local `.env` QA credentials only
- The production pipeline path with a `NoopNotifier`
- Windows Task Scheduler for automation

## Fixed QA Profile

- Account size: `$10,000`
- Risk profile: `Balanced`
- Timezone: `ET` / `America/Toronto`
- Broker: `Wealthsimple`
- Strategy permission: `long_and_short`
- Max contracts: `3`

The QA user is identified by `QA_USER_CHAT_ID` and is kept separate from normal user history.

## Secret Handling

Use `.env` variables only:

- `QA_OPENROUTER_API_KEY`
- `QA_ALPACA_API_KEY`
- `QA_ALPACA_API_SECRET`
- `QA_ALPHA_VANTAGE_API_KEY`

Do not store plaintext secrets in:

- Git-tracked files
- Markdown docs
- CSV or JSON QA artifacts
- Database user rows

The QA runner overlays these secrets at runtime onto the in-memory QA execution path.

## Automation

Schedule `scripts/run_qa_intraday.ps1` with Windows Task Scheduler:

- Weekdays only
- Start at `9:30 AM ET`
- Repeat every `20 minutes`
- Last launch at `3:50 PM ET`

The script performs its own NYSE market-hours guard so holidays, early closes, DST edges, or accidental off-hours launches exit cleanly.

## Artifact Layout

Each run writes to:

`var/qa/<YYYY-MM-DD>/<HHMMSS>_<runid>/`

Artifacts include:

- Production-style run artifacts:
  - `run_summary.json`
  - `candidate_cards.json`
  - `option_contracts.json`
  - `recommendation_card.json`
  - `telegram_message.txt`
- Production CSV exports in `results/`
- QA step CSV exports in `qa_csv/`
- Decision artifacts:
  - `decision_input.json`
  - `decision_output.json`
  - `heuristic_decision_output.json`
- Replay artifacts:
  - `replay_input.json`
  - `replay_1.json`
  - `replay_2.json`
  - `replay_diff.json`
- Snapshot artifacts:
  - `news_briefs/<TICKER>.json`
  - `scoring_snapshots/<TICKER>.json`
- Run manifest:
  - `manifest.json`

## Step CSV Exports

The QA CSV layer writes:

- `inputs.csv`
- `strategies.csv`
- `candidates.csv`
- `market.csv`
- `news_summary.csv`
- `news_articles.csv`
- `scoring.csv`
- `scoring_factors.csv`
- `options.csv`
- `decision.csv`
- `final_option.csv`
- `final_target_option.csv`

Each file carries stable metadata columns:

- `run_id`
- `lane`
- `reference_dt_utc`
- `reference_trading_date`
- `qa_user_id`
- `qa_user_chat_id`

## Replay Design

After each live run:

1. Capture the frozen candidate batch, market snapshots, news bundles, option chains, and user profile into `replay_input.json`.
2. Run `replay_1` from the captured in-memory snapshot.
3. Deserialize `replay_input.json` and run `replay_2`.
4. Compare both outputs in `replay_diff.json`.

Replays use the deterministic heuristic decision step so the replay lane isolates structural application drift instead of LLM variance.

## Drift Classification

`scripts/compare_qa_day.py` produces:

- `summary.csv`
- `adjacent_diffs.csv`
- `candidate_score_diffs.csv`
- `daily_report.md`

Adjacent runs are classified as:

- `screening_source_drift`
- `market_data_drift`
- `news_drift`
- `options_data_drift`
- `determinism_regression`
- `decision_layer_drift`
- `mixed_input_drift`
- `no_material_change`

## Implementation Notes

- Options fetching is pinned to the run's frozen trading date so replay does not depend on wall-clock `date.today()`.
- The QA runner reuses the existing workflow run lock. If a prior QA run is still active, the launch is recorded as `already_running` instead of a failure.
- `scripts/ensure_qa_user.py` is idempotent and pauses any default cron rows for the QA user.

## Test Coverage

Add focused tests for:

- Frozen-date threading into options fetching
- QA replay determinism
- QA diff classification
- QA runtime bootstrap behavior
