# Plan: Active Position Management After "I Bought It"

## Context

Today the Telegram bot sends an options recommendation, the user clicks **"✅ I bought it"**, and the only thing that happens is a `FeedbackEvent` row with `user_action="bought"` is logged (`app/telegram/handlers/recommendation.py:70-83`). The bot then forgets about the trade.

The user wants the bot to **manage** the trade after purchase: capture the actual fill, poll the option's current premium, and proactively warn the user when action is needed (target hit, stop hit, exit-by-date reached, expiry imminent). The recommendation already stores `target_option_price`, `stop_loss_option_price`, `exit_by_date`, and `expiry` (`app/db/models/recommendation.py`), so all the thresholds are available — we just need a tracker, a poller, and an alert dispatcher.

**Polling strategy (per user request):** Use the existing yfinance client (delayed data) by default. Switch to a real-time source when the position is close to expiry **or** the delayed price is approaching a threshold. Real-time source = **Alpaca options API** (the codebase already encrypts Alpaca keys in the user table — legitimate API path, no scraping). TradingView via Playwright is left out of scope for v1 because Alpaca already covers the use case and is more reliable than scraping.

## Recommended Approach

### 1. New DB model — `OpenPosition`

Create `app/db/models/open_position.py` with:

| Field | Type | Notes |
|---|---|---|
| `id` | PK | |
| `recommendation_id` | FK → recommendations.id | |
| `user_id` | FK → users.id | |
| `entry_price` | Numeric(14,4) | Captured from user via FSM |
| `entry_quantity` | Integer | Captured from user (defaults to `suggested_quantity`) |
| `entry_at` | TIMESTAMPTZ | |
| `status` | String(16) | `active` / `closed_sold` / `closed_expired` |
| `close_price` | Numeric(14,4), nullable | |
| `close_at` | TIMESTAMPTZ, nullable | |
| `last_premium` | Numeric(14,4), nullable | Most recent polled mid |
| `last_polled_at` | TIMESTAMPTZ, nullable | |
| `last_data_source` | String(16), nullable | `yfinance` / `alpaca` |
| `alerts_sent` | JSONB, default `[]` | Dedup, e.g. `["target_hit","exit_by_date"]` |
| `created_at` | TIMESTAMPTZ | |

Add `OpenPositionRepository` next to existing repos in `app/db/repositories/`.

**Migration:** `alembic/versions/0006_open_positions.py` (follows existing pattern in `alembic/versions/0005_exit_targets.py`).

### 2. Capture the fill — FSM after "I bought it"

Modify `app/telegram/handlers/recommendation.py` (the `bought` branch, lines 70-83):

- Replace the immediate `FeedbackEvent` write with an aiogram FSM flow:
  1. Reply: *"What was your fill price per contract?"* — store as `entry_price`.
  2. Reply: *"How many contracts? (default: {suggested_quantity})"* — store as `entry_quantity`.
  3. Persist both a `FeedbackEvent(user_action="bought", entry_price=...)` (keep existing log) **and** a new `OpenPosition(status="active", ...)` row.
  4. Confirm: *"Tracking this position. I'll alert you on target/stop/exit/expiry."*
- Use `aiogram.fsm.context.FSMContext` and a `BoughtPositionStates` group. aiogram FSM is already used elsewhere — see `app/telegram/handlers/schedule.py` for the pattern.
- Keep `skipped` branch unchanged.

### 3. Real-time data source — Alpaca options client

Create `app/services/options/alpaca_options_client.py`:

- Use `httpx.AsyncClient` (already a dep) against Alpaca's `/v1beta1/options/snapshots/{symbol}` endpoint.
- Method: `async def fetch_premium(user, ticker, strike, expiry, option_type) -> Decimal | None`.
- Uses the encrypted Alpaca key already on the `users` table (the existing encryption helper — find via grep for `decrypt`/`fernet` in `app/services` or `app/core`).
- OCC option symbol builder (e.g. `AAPL250620C00200000`) — small pure helper, unit-testable.

Extend `app/services/options/yfinance_client.py` with a thin convenience method `async def fetch_premium(ticker, strike, expiry, option_type) -> Decimal | None` that calls existing `fetch_chain()` and filters — keeps the new poller agnostic of source.

### 4. Position monitor — single periodic APScheduler job

Create `app/services/positions/monitor.py` with `async def poll_open_positions()`:

1. Query all `OpenPosition` rows with `status="active"`.
2. For each, decide source:
   - **Default:** yfinance (delayed).
   - **Real-time (Alpaca)** if any of:
     - `expiry - today <= 1 day`
     - last yfinance premium within 10% of `target_option_price` or `stop_loss_option_price`
     - last yfinance premium just crossed a threshold (re-confirm before alerting)
3. Update `last_premium`, `last_polled_at`, `last_data_source`.
4. Evaluate four alerts (only fire if not already in `alerts_sent`):
   - `target_hit` — `current >= target_option_price`
   - `stop_hit` — `current <= stop_loss_option_price`
   - `exit_by_date` — `today >= exit_by_date`
   - `expiry_t_minus_1` — `expiry - today <= 1 day`
5. Send via `AiogramNotifier.send_text()` (`app/pipeline/orchestrator.py:83-104`) with the new alert keyboard (see §5). Append the alert key to `alerts_sent`.
6. If `today > expiry` and still active → set `status="closed_expired"` and stop polling.

Wire into `app/scheduler/scheduler.py` alongside `sync_jobs()`:

```python
self.scheduler.add_job(
    poll_open_positions,
    trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/15", timezone="America/New_York"),
    id="poll_open_positions",
    replace_existing=True,
    coalesce=True, max_instances=1, misfire_grace_time=300,
)
```

A single job over all positions (instead of per-position jobs) avoids thrashing the APScheduler `SQLAlchemyJobStore` when positions open/close.

### 5. Alert keyboard + handler — "Sold" / "Still holding"

- Add to `app/telegram/keyboards/settings.py` next to `RecCB`:
  ```python
  class PosCB(CallbackData, prefix="pos"):
      action: str   # "sold" | "holding"
      position_id: int
  ```
  with a `position_alert_keyboard(position_id)` factory (mirrors `recommendation_keyboard`).
- New handler `app/telegram/handlers/position.py`:
  - `sold` → FSM asks for sell price → set `status="closed_sold"`, fill `close_price`/`close_at`, compute pnl, write a `FeedbackEvent(user_action="closed", exit_price=..., pnl=...)` (the model already supports this).
  - `holding` → just acks; `alerts_sent` already prevents re-spamming until next threshold.
- Register the router in `app/telegram/handlers/__init__.py` (see how `recommendation.py`'s router is registered).

### 6. Optional: `/positions` command

A small `/positions` command listing the user's active positions (ticker, strike/expiry, entry, last premium, P&L, status). Reuses `OpenPositionRepository.list_active(user_id)`. Nice-to-have; not blocking.

## Critical Files

**New:**
- `app/db/models/open_position.py`
- `app/db/repositories/open_position.py`
- `alembic/versions/0006_open_positions.py`
- `app/services/options/alpaca_options_client.py`
- `app/services/positions/monitor.py`
- `app/telegram/handlers/position.py`
- `tests/services/test_position_monitor.py`

**Modified:**
- `app/telegram/handlers/recommendation.py` — FSM for fill capture on `bought`
- `app/telegram/keyboards/settings.py` — add `PosCB` + `position_alert_keyboard`
- `app/services/options/yfinance_client.py` — add `fetch_premium()` convenience
- `app/scheduler/scheduler.py` — register `poll_open_positions` job
- `app/telegram/handlers/__init__.py` — register new router
- `app/db/models/__init__.py` — export `OpenPosition`

**Reused (do not duplicate):**
- `AiogramNotifier.send_text()` — `app/pipeline/orchestrator.py:83-104`
- `FeedbackEvent` — already supports `closed`/`exit_price`/`pnl`, used as the canonical event log
- yfinance chain fetch — `app/services/options/yfinance_client.py:fetch_chain`
- Alembic migration pattern — `alembic/versions/0005_exit_targets.py`
- aiogram FSM pattern — `app/telegram/handlers/schedule.py`

## Verification

1. **Migration:** `alembic upgrade head` — confirm `open_positions` table created.
2. **Unit tests:**
   - `tests/services/test_position_monitor.py` — alert thresholds, dedup via `alerts_sent`, source-switching logic, expiry auto-close. Mock both option clients.
   - OCC symbol builder roundtrip.
3. **End-to-end manual test (staging bot, paper Alpaca key):**
   - Trigger a recommendation with a near-dated expiry.
   - Click **I bought it** → enter fill price + quantity → confirm `OpenPosition` row created with `status=active`.
   - Manually update `last_premium`/`target_option_price` in DB to force `target_hit` → run `poll_open_positions()` once → confirm Telegram alert with **Sold/Still holding** buttons.
   - Click **Sold** → enter sell price → confirm `status=closed_sold`, `pnl` populated, no further alerts.
   - Repeat for `stop_hit`, `exit_by_date`, `expiry_t_minus_1` paths.
4. **Polling source switch:** Set a position `expiry = today + 1 day` and watch `last_data_source` flip from `yfinance` to `alpaca` on the next poll.
5. **Dedup:** Force the same threshold twice in a row — second poll must NOT re-send the alert.
