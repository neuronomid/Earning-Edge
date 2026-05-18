# QA Intraday Drift Harness — VPS Setup Instructions

Audience: an AI agent (or operator) deploying the `soroush_v4` branch onto a Linux VPS that already runs `main`. Goal: stand up the intraday QA drift harness so it fires every 20 minutes during NYSE hours, writes artifacts to `var/qa/`, and never sends Telegram messages.

Full design: [PLAN_QA_intraday_drift.md](PLAN_QA_intraday_drift.md). Do not re-derive the design — follow this runbook.

## 0. Preconditions

Before touching anything, verify the VPS is in a known state:

- The repo is checked out, currently on `main`, and `./dev.sh` (or the equivalent prod service) is healthy.
- Postgres and Redis are reachable from the app user.
- `uv` is installed and `.venv` builds from `uv.lock`.
- The system timezone does **not** need to be ET — schedulers are configured with `America/New_York` explicitly.

If any of those is false, stop and report — do not attempt to fix prod plumbing as part of QA bring-up.

## 1. Get the branch onto the VPS

```bash
cd /srv/earning-edge          # adjust to the actual checkout path
git fetch origin
git checkout soroush_v4
git pull --ff-only origin soroush_v4
uv sync --frozen
```

No new Alembic migrations exist on this branch relative to `main`. Do **not** run `alembic upgrade head` as part of QA setup; the prod migration state is already correct.

## 2. Configure secrets in `.env`

Append the QA block to the VPS `.env` (template is at the bottom of `.env.example`). The four secret fields are required — the QA runner calls `get_qa_runtime_secrets(..., require_all=True)` and will exit if any is missing.

```
QA_USER_CHAT_ID=qa_intraday
QA_ACCOUNT_SIZE=10000
QA_RISK_PROFILE=Balanced
QA_TIMEZONE_LABEL=ET
QA_TIMEZONE_IANA=America/Toronto
QA_BROKER=Wealthsimple
QA_STRATEGY_PERMISSION=long_and_short
QA_MAX_CONTRACTS=3
QA_OPENROUTER_API_KEY=<fill in>
QA_ALPACA_API_KEY=<fill in>
QA_ALPACA_API_SECRET=<fill in>
QA_ALPHA_VANTAGE_API_KEY=<fill in>
```

Rules:

- Never commit real values. The `.env` file is gitignored — keep it that way.
- The QA secrets must be **different identities** from the prod ones if you want to avoid contaminating real usage stats and quota. If only one set of keys exists, reuse them but understand they will share rate limits.
- The QA profile knobs (`QA_ACCOUNT_SIZE`, `QA_RISK_PROFILE`, etc.) have safe defaults in `Settings` — only override if you have a reason.

## 3. Create the QA user

The QA user is a separate row in the `users` table identified by `QA_USER_CHAT_ID`. Bootstrap it once:

```bash
uv run python scripts/ensure_qa_user.py
```

This script is idempotent: it creates or updates the QA user with the fixed profile from `.env`, and pauses any default cron rows for that user so the normal weekly scheduler does not fire against it. Run it again any time you change the QA profile knobs.

## 4. Sanity-check with one manual run

Before wiring up the scheduler, fire one run by hand to confirm the pipeline works end-to-end on the VPS:

```bash
./scripts/run_qa_intraday.sh
```

Expected outcomes:

- **During NYSE hours**: a new slot directory under `var/qa/<YYYY-MM-DD>/<HHMMSS>_<runid>/` containing `manifest.json`, `run_summary.json`, `candidate_cards.json`, `option_contracts.json`, `recommendation_card.json`, `telegram_message.txt`, the `results/` CSVs, the `qa_csv/` step exports, the decision and replay artifacts, and the `news_briefs/` + `scoring_snapshots/` snapshots. (Layout: [PLAN_QA_intraday_drift.md §Artifact Layout](PLAN_QA_intraday_drift.md#artifact-layout).)
- **Outside NYSE hours**: a slot directory ending in `_market_closed` containing only `manifest.json` with `status: "market_closed"`. The script exits 0. This is healthy.
- **If a previous QA run is still active**: the run is recorded as `already_running` rather than failing. This is healthy and is the expected behavior of the shared workflow run lock.

Tail the scheduler log if something looks wrong:

```bash
tail -f var/qa/_scheduler/$(date +%F).log
```

No Telegram message should ever be sent. If the prod Telegram channel pings, stop immediately — the `NoopNotifier` wiring is broken and must be fixed before scheduling.

## 5. Schedule automatic runs

Pick **one** scheduler path. Do not install both.

### Option A — systemd timer (recommended)

Cleaner logging via `journalctl`, automatic DST handling, easier to disable.

```bash
sudo cp scripts/qa-intraday.service.example /etc/systemd/system/qa-intraday.service
sudo cp scripts/qa-intraday.timer.example   /etc/systemd/system/qa-intraday.timer
sudo $EDITOR /etc/systemd/system/qa-intraday.service
```

In the service file, set:

- `User=` — the OS user that owns the repo and the `.env` file.
- `WorkingDirectory=` — the absolute path to the repo checkout.
- `EnvironmentFile=` — the absolute path to `.env`.

Then enable:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now qa-intraday.timer
systemctl list-timers qa-intraday.timer        # confirm next-run time
journalctl -u qa-intraday.service -f           # tail live invocations
```

### Option B — cron

```bash
crontab -e
```

Paste from `scripts/qa_intraday.crontab.example` and update `REPO_ROOT` to the actual checkout path. Confirm with `crontab -l`. Cron will inherit no shell profile, which is fine — the wrapper script handles `.venv` discovery and writes its own log file.

Either way, the cron expression / `OnCalendar` is intentionally a superset of NYSE hours. The Python entry point performs its own market-hours guard (`is_market_open`), so holidays, early closes, and DST edges exit cleanly with `status=market_closed` and do not corrupt the artifact tree.

## 6. End-of-day comparison (optional, run by hand or on a daily timer)

After each trading day, produce a daily drift report:

```bash
uv run python scripts/compare_qa_day.py <YYYY-MM-DD>
```

Outputs land in `var/qa/<YYYY-MM-DD>/`:

- `summary.csv`
- `adjacent_diffs.csv`
- `candidate_score_diffs.csv`
- `daily_report.md`

Drift classifications: see [PLAN_QA_intraday_drift.md §Drift Classification](PLAN_QA_intraday_drift.md#drift-classification).

## 7. Operational hygiene

- **Artifact growth**: each slot is small but 20m × 6.5h = ~20 slots/day. Plan disk: a few hundred MB per week is typical. If retention matters, add a cron to delete `var/qa/<old date>/` directories older than N days. Do not delete the current day's directory while the scheduler is active.
- **Branch drift**: this VPS is now pinned to `soroush_v4`. If `main` advances with hotfixes that matter, merge or rebase deliberately — do not silently swap branches under a running scheduler. Stop the timer (`systemctl stop qa-intraday.timer`) or comment out the cron line before changing branches.
- **Secret rotation**: when QA keys rotate, edit `.env` and restart nothing — the script reads settings fresh on every invocation. systemd's `EnvironmentFile` is also re-read per `ExecStart`.
- **Run lock**: QA reuses `app/services/run_lock.py` keyed by the QA user. It will never collide with real users. If a QA run hangs past the lock TTL (`WORKFLOW_RUN_LOCK_TTL_SECONDS`, default 900s), the next tick will be allowed in regardless — this is intentional.

## 8. Tear-down

If you need to disable the harness:

```bash
# systemd:
sudo systemctl disable --now qa-intraday.timer

# cron:
crontab -e        # remove the two QA lines

# verify nothing is launching:
ls -lt var/qa/_scheduler/
```

You can leave the QA user and artifacts in place; they cost nothing while idle.

## 9. What to do when something breaks

1. Check `var/qa/_scheduler/<date>.log` for the most recent launch line and exit code.
2. Open the most recent slot directory and read `manifest.json` — it records the run status and any error message.
3. If the failure is in the pipeline itself (not the harness), reproduce by re-running `./scripts/run_qa_intraday.sh` manually and watching the log.
4. If the failure is in the harness wrapper (e.g. wrong Python, missing `.venv`), fix the wrapper or rebuild `.venv` with `uv sync --frozen`. Do not edit the Python entry point as a first response — the harness scripts are deliberately thin.
5. **Never** silence a failure by deleting artifacts. The artifact tree is the audit trail.

Report root causes back to the human operator with the run id, the manifest, and the relevant slice of `_scheduler/<date>.log`.
