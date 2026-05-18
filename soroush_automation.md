# Soroush — QA Intraday Drift Harness: Setup & Deployment

This document explains how to set up the **QA intraday drift harness** that runs the production recommendation pipeline every 20 minutes during NYSE hours, captures step-level + run-level artifacts, replays frozen inputs, and emits a daily drift-classification report. The harness uses a dedicated QA user, suppresses Telegram delivery via a `NoopNotifier`, and reads its credentials from `.env` only (never the database).

Design spec: [`docs/PLAN_QA_intraday_drift.md`](docs/PLAN_QA_intraday_drift.md).

## 1. What was implemented

### Code (in this repo, already merged)

| Path | Role |
|---|---|
| `app/services/qa_runtime.py` | QA config + secrets resolution, `NoopNotifier`, `ensure_qa_user`, `qa_day_dir`, `qa_reference_datetime`, `qa_reference_trading_date`. |
| `app/services/qa_replay_service.py` | Captures frozen replay inputs, runs deterministic heuristic replay, diffs results. |
| `app/services/qa_compare_service.py` | Compares adjacent runs in a day, classifies drift, writes daily report. |
| `app/services/qa_export_service.py` | Writes per-step CSV + JSON artifacts under `var/qa/<date>/<HHMMSS>_<runid>/`. |
| `scripts/run_qa_intraday.py` | One-shot harness CLI invoked per scheduled tick. |
| `scripts/run_qa_intraday.ps1` | Windows Task Scheduler wrapper. Logs to `var/qa/_scheduler/<YYYY-MM-DD>.log`. |
| `scripts/ensure_qa_user.py` | Idempotent. Creates the QA user row and pauses its default cron. |
| `scripts/compare_qa_day.py` | Emits `summary.csv`, `adjacent_diffs.csv`, `candidate_score_diffs.csv`, `daily_report.md` for a day. |
| `tests/test_qa_services.py` | 9 tests covering replay determinism, frozen-trading-date threading, drift classification, helpers. |

### Configuration

QA-only env vars live in `.env` (committed `.env.example` shows the keys):

```dotenv
QA_USER_CHAT_ID=qa_intraday
QA_ACCOUNT_SIZE=10000
QA_RISK_PROFILE=Balanced
QA_TIMEZONE_LABEL=ET
QA_TIMEZONE_IANA=America/Toronto
QA_BROKER=Wealthsimple
QA_STRATEGY_PERMISSION=long_and_short
QA_MAX_CONTRACTS=3
QA_OPENROUTER_API_KEY=
QA_ALPACA_API_KEY=
QA_ALPACA_API_SECRET=
QA_ALPHA_VANTAGE_API_KEY=
```

Secrets stay `.env`-only. They are **never** written to git-tracked files, the QA user row, or any CSV/JSON artifact.

### Verification

```bash
uv run pytest tests/test_qa_services.py -q          # → 9 passed
uv run pytest -q --ignore=tests/e2e                  # → 352 passed, 44 db-skipped
```

## 2. Prerequisites (any host)

- Python 3.12 with `uv`
- Postgres 16 + Redis 7 reachable to the app
- `.env` filled in (all `QA_*` values + the regular DB/Redis/Bot config)
- Dependencies installed:
  ```bash
  uv sync                              # installs from uv.lock (frozen)
  ```
  The harness depends on `pandas-market-calendars` for NYSE session math — already in `pyproject.toml`.
- DB schema up to date: `alembic upgrade head`
- The QA user row exists: `python scripts/ensure_qa_user.py` (idempotent)

## 3. Local Windows setup (Task Scheduler)

### One-time

1. Clone the repo, fill in `.env`, bring up the dev stack:
   ```powershell
   cp .env.example .env       # then edit
   .\dev.sh                   # brings up postgres + redis + migrations
   ```
2. Create the QA user:
   ```powershell
   .\.venv\Scripts\python.exe .\scripts\ensure_qa_user.py
   ```
3. Smoke-test the wrapper:
   ```powershell
   .\scripts\run_qa_intraday.ps1 --help
   ```
   It should write `var/qa/_scheduler/<today>.log` and exit 0.

### Schedule it

Open **Task Scheduler → Create Task** (not "Create Basic Task"):

- **General** → name `EarningEdge QA Intraday`. Run whether user is logged in or not.
- **Triggers** → New trigger:
  - Begin: On a schedule, Weekly, days Mon–Fri.
  - Start: today's date at `09:30:00`. **Set the time zone to `(UTC-05:00) Eastern Time (US & Canada)`** so the trigger fires at 9:30 AM ET regardless of your local timezone.
  - Repeat task every: `20 minutes` for a duration of: `7 hours` (covers 9:30 AM → 3:50 PM ET).
- **Actions** → Start a program:
  - Program: `powershell.exe`
  - Arguments: `-ExecutionPolicy Bypass -File "C:\path\to\Earning-Edge-main\scripts\run_qa_intraday.ps1"`
  - Start in: `C:\path\to\Earning-Edge-main`
- **Conditions** → check **"Wake the computer to run this task"** (only matters from sleep, not shutdown).
- **Settings** → "If the task is already running, do not start a new instance" (the Python script also takes a per-user Redis lock).

### Power requirements (laptop only)

Task Scheduler cannot start a job on a **powered-off** machine. For a laptop:

- Keep it plugged in and prevent sleep during market hours:
  ```powershell
  powercfg /change standby-timeout-ac 0
  ```
- The screen can still turn off — only sleep blocks scheduled tasks.

If you want true 24/7 automation, run the harness on a VPS instead (next section).

## 4. VPS / Linux deployment

The whole stack is Linux-friendly; only the PowerShell wrapper is Windows-specific. On Linux you use `cron` directly and skip the `.ps1` file.

### Recommended host

Any small Linux VPS works: DigitalOcean / Hetzner / Vultr ~$5–10/month. 1 vCPU, 2 GB RAM, 20 GB disk is plenty. Pin the timezone to UTC or ET — the harness handles both.

### One-time setup

```bash
# 1. clone
git clone <your-fork-url> /opt/earning-edge
cd /opt/earning-edge

# 2. install python + uv
curl -LsSf https://astral.sh/uv/install.sh | sh
uv sync                                  # frozen install from uv.lock

# 3. set up env
cp .env.example .env
$EDITOR .env                             # fill in DB + QA_* values

# 4. bring up postgres + redis (compose) — or point .env at managed services
docker compose up -d postgres redis
docker compose run --rm --no-deps app alembic upgrade head

# 5. create QA user
uv run python scripts/ensure_qa_user.py
```

### Cron entry

NYSE hours are 9:30 AM – 4:00 PM ET. The harness already does its own market-hours guard (NYSE calendar via `pandas-market-calendars`, respects holidays + early closes), so a slightly wider cron window is safe — out-of-hours ticks exit cleanly without spending API budget.

```cron
# /etc/cron.d/earning-edge-qa
# m   h          dom mon dow      command
CRON_TZ=America/New_York
30,50 9-15  *   *   1-5    earningedge  cd /opt/earning-edge && .venv/bin/python scripts/run_qa_intraday.py >> var/qa/_scheduler/$(date +\%F).log 2>&1
10    16    *   *   1-5    earningedge  cd /opt/earning-edge && .venv/bin/python scripts/compare_qa_day.py >> var/qa/_scheduler/$(date +\%F).compare.log 2>&1
```

What this does:

- `30,50 9-15 …` → fires at 9:30, 9:50, 10:10, … 3:50 ET on weekdays (the `%` in `strftime` is escaped because cron treats `%` specially).
- The 4:10 PM ET `compare_qa_day.py` writes the daily drift report.
- `CRON_TZ` makes the times read literally as Eastern Time (Debian/Ubuntu's `vixie-cron` supports this; on Alpine/`busybox-cron` invert the times to UTC instead).

### Systemd timer (alternative to cron)

If you prefer systemd timers:

```ini
# /etc/systemd/system/earning-edge-qa.service
[Service]
Type=oneshot
User=earningedge
WorkingDirectory=/opt/earning-edge
ExecStart=/opt/earning-edge/.venv/bin/python scripts/run_qa_intraday.py
StandardOutput=append:/opt/earning-edge/var/qa/_scheduler/service.log
StandardError=inherit
```

```ini
# /etc/systemd/system/earning-edge-qa.timer
[Unit]
Description=EarningEdge QA every 20 min on NYSE weekdays

[Timer]
OnCalendar=Mon..Fri *-*-* 09:30,09:50,10:10,10:30,10:50,11:10,11:30,11:50,12:10,12:30,12:50,13:10,13:30,13:50,14:10,14:30,14:50,15:10,15:30,15:50 America/New_York
Persistent=false

[Install]
WantedBy=timers.target
```

```bash
systemctl enable --now earning-edge-qa.timer
```

## 5. Verifying it works

### After one tick

```bash
ls var/qa/$(date -u +%F)/                 # one subdir per tick, e.g. 133000_<runid>/
cat var/qa/$(date -u +%F)/*/manifest.json | jq .status
tail -50 var/qa/_scheduler/$(date +%F).log
```

A healthy tick contains:

- `run_summary.json`, `candidate_cards.json`, `option_contracts.json`, `recommendation_card.json`
- `telegram_message.txt` (the message the bot **would** have sent, captured because `NoopNotifier` swallowed delivery)
- `qa_csv/` with per-step exports
- `decision_input.json`, `decision_output.json`, `heuristic_decision_output.json`
- `replay_input.json`, `replay_1.json`, `replay_2.json`, `replay_diff.json`
- `manifest.json` with hashes and replay status

### At end of day

```bash
python scripts/compare_qa_day.py --day $(date +%F)
cat var/qa/$(date +%F)/daily_report.md
```

The report classifies adjacent runs into:
`screening_source_drift`, `market_data_drift`, `news_drift`, `options_data_drift`, `determinism_regression`, `decision_layer_drift`, `mixed_input_drift`, `no_material_change`.

## 6. Operating notes

- **Concurrency** — `WorkflowRunner` takes a per-user Redis lock (TTL 900s). If a previous tick is still running, the new tick records `already_running` and exits without colliding.
- **Holidays / early closes** — `pandas-market-calendars` is consulted inside `run_qa_intraday.py`; non-trading days return immediately with no artifacts.
- **Secret hygiene** — `get_qa_runtime_secrets(require_all=True)` aborts the run if any `QA_*` key is missing. Real user credentials are never read.
- **Cost** — Each tick calls the heavy LLM (Opus 4.7) once via the production decision step. Budget ~20 ticks/day × 5 days = 100 decision calls/week, plus news summaries on Gemini Flash. The replay step uses the deterministic heuristic engine — no extra LLM cost.
- **Disk** — Roughly 1–2 MB of artifacts per tick. `var/qa/` grows by ~200 MB/week. Rotate or archive periodically (`tar` + delete old dates).

## 7. Common failures and fixes

| Symptom | Cause | Fix |
|---|---|---|
| `ModuleNotFoundError: pandas_market_calendars` | Dependency missing from venv | `uv sync` (it's in `pyproject.toml`) |
| `ValueError: Missing QA credentials in .env: …` | `QA_*` key blank in `.env` | Fill in the listed key |
| `DecryptionError: ciphertext could not be decrypted` | Running orchestrator against a non-QA user without a `user_secrets_resolver` | Use `scripts/run_qa_intraday.py` only — it routes through `qa_runtime` |
| Telegram chat receiving QA messages | `NoopNotifier` not wired | Confirm the wrapper invokes `scripts/run_qa_intraday.py`, not the production runner |
| Empty `var/qa/<date>/` | Market was closed (weekend/holiday/early-close) | Check `var/qa/_scheduler/<date>.log` — should show "market closed, skipping" |

## 8. Quick command reference

```bash
# Local Windows
.\.venv\Scripts\python.exe .\scripts\ensure_qa_user.py
.\scripts\run_qa_intraday.ps1
.\.venv\Scripts\python.exe .\scripts\compare_qa_day.py

# Linux / VPS
uv run python scripts/ensure_qa_user.py
uv run python scripts/run_qa_intraday.py
uv run python scripts/compare_qa_day.py

# Tests
uv run pytest tests/test_qa_services.py -q
```

---

**Spec:** `docs/PLAN_QA_intraday_drift.md`
**Build conventions:** `CLAUDE.md` (async everywhere, Decimal for money, frozen dataclasses, fallbacks beat aborts, config via `get_settings()`)
