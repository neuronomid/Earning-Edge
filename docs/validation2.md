# Position Validation v2 - Critical Review and Implementation Plan

Status: proposed implementation plan
Date: 2026-05-12
Scope: open-position thesis validation after a user confirms a trade
Source reviewed: `docs/validation.md` plus the current codebase

## 1. Bottom line

I agree with the problem in `docs/validation.md`: the current position monitor
only tells the user where the option premium is relative to target, stop, exit
date, and expiry. It does not answer whether the original reason for the trade
is still valid.

I also agree with the high-level four-layer design:

1. Freeze the entry thesis when a user buys.
2. Compute deterministic drift without an LLM.
3. Escalate material drift to a heavy LLM revalidation.
4. Show the result in Telegram with history.

I would not implement the Opus proposal verbatim. The design is directionally
right, but it assumes data that the current repo does not actually have in the
position monitor, and it creates a few contradictions:

- It says entry option premium should come from a fresh option-chain pull, but
  this app already asks the user for the real fill. The actual fill must be the
  canonical entry premium.
- It assumes the monitor can compare underlying, IV, and delta, but
  `PositionMonitor` currently stores only `premium` and `source`.
- It treats the thesis table as fully immutable, but also proposes fields such
  as `catalyst_passed` that are inherently current-state values.
- It proposes changing `StructuredDecision` for the initial recommendation
  flow. That is not necessary for v1 and would increase regression risk in the
  most important pipeline path.
- It says manual validation is uncapped, then proposes a global daily cap that
  may also affect manual validations.
- It does not address existing active positions that were opened before this
  feature exists.
- It does not provide a clean way to apply target/stop adjustments without
  mutating the immutable `recommendations` row or leaving the existing alert
  monitor on stale thresholds.

The best implementation is still the same product idea, but with one extra
foundation layer: a reusable position quote snapshot service. Without that,
the validation feature will be built on incomplete data.

## 2. Current codebase facts

These are the implementation anchors I verified in the repo.

### 2.1 Current position state is intentionally small

`app/db/models/open_position.py` stores:

- `recommendation_id`, `user_id`
- `entry_price`, `entry_quantity`, `entry_at`
- `status`, `close_price`, `close_at`
- `last_premium`, `last_polled_at`, `last_data_source`
- threshold alert bookkeeping: `alerts_sent`, target/stop counts, dismissals,
  and mute timestamps

It does not store underlying entry price, IV, delta, gamma, theta, vega,
entry bid/ask, entry market snapshot, news baseline, or thesis criteria.

### 2.2 Closed status values are already known

The current code uses:

- `active`
- `closed_sold`
- `closed_expired`

`OpenPositionRepository.list_active()` and
`OpenPositionRepository.list_active_with_recommendations_for_user()` filter on
`OpenPosition.status == "active"`, so the core closed-position behavior is
already correct.

### 2.3 Recommendations are scanner outputs, not active trade plans

`app/db/models/recommendation.py` stores the recommended contract and plan:

- ticker, strategy source, strategy, option type, side, strike, expiry
- suggested entry
- target/stop option prices
- underlying stop
- exit-by date
- expected holding days
- expected move percent
- reasoning, key evidence, key concerns
- news coverage and stale-news flags

It does not store contract greeks, option bid/ask at decision time, contract
score, direction score, or the full news article timestamp baseline.

That means a thesis builder must combine data from `recommendations`,
`workflow_runs.*_json`, `candidates`, and `option_contracts`, not just the
recommendation row.

### 2.4 Option greeks exist, but not through the position monitor

`app/db/models/option_contract.py` stores:

- bid, ask, mid
- volume, open interest
- implied volatility
- delta, gamma, theta, vega
- target/stop metadata and contract score

But `OptionContract` is linked to `Candidate`, not directly to
`Recommendation`. The selected recommendation can be matched by
`run_id + ticker + option_type + position_side + strike + expiry`, or by the
run JSON artifacts. A naive "last OptionContract row" fallback is too
ambiguous.

### 2.5 Current monitor fetches only option premium

`app/services/positions/monitor.py` has:

```python
@dataclass(slots=True, frozen=True)
class PremiumQuote:
    premium: Decimal
    source: str
```

The monitor:

- groups active positions by ticker
- fetches option premiums from Alpaca if the first user in that ticker group
  has credentials
- otherwise falls back to yfinance
- updates `last_premium`, `last_polled_at`, and `last_data_source`
- fires target, stop, exit-date, and expiry alerts

This is not enough for thesis validation. Validation needs a richer current
snapshot:

- option bid, ask, mid, and liquidation premium
- underlying price
- IV
- greeks when available
- quote source and data quality
- quote timestamp/staleness when available

### 2.6 yfinance and Alpaca have different quote quality

The current `YFinanceOptionsClient` can provide bid, ask, mid, last price, IV,
volume, and open interest. It does not currently provide greeks.

The current `AlpacaOptionsClient` can parse bid, ask, mid, last trade, IV, and
greeks from the options snapshots response.

Therefore, validation criteria must treat IV and greeks as optional. Missing
IV/delta cannot be allowed to fire false invalidations.

### 2.7 Scheduler market-hours gating is incomplete

`SchedulerService.sync_position_monitor_job()` currently schedules:

```python
CronTrigger(
    day_of_week="mon-fri",
    hour="9-16",
    minute="*/2",
    timezone=ZoneInfo("America/New_York"),
)
```

This fires at 9:00, 9:02, etc. before regular market open, and it also fires
at 16:00, 16:02, ..., 16:58. The service itself needs a market-hours guard.
Do not rely on APScheduler cron syntax alone.

### 2.8 Existing Telegram position surfaces are simple

Active positions are shown through:

- `app/telegram/handlers/menu.py`
- `app/telegram/templates/positions.py`
- `app/telegram/keyboards/settings.py::position_list_keyboard`

Closed trades are already shown and editable through:

- `app/telegram/handlers/history.py`
- `app/telegram/templates/history.py`
- `app/telegram/keyboards/history.py`

Validation history should integrate with both surfaces: active position cards
for action, closed trade history for read-only review.

### 2.9 The existing LLM router already supports a separate schema

`LLMRouter.decide()` accepts any Pydantic `response_schema`.

That means position validation can use the heavy model route without adding
fields to the initial recommendation `StructuredDecision` model. A new
`StructuredPositionValidation` schema is enough for v1.

## 3. External references checked

These are the practical constraints I used while revising the plan.

- NYSE regular hours are 9:30 AM to 4:00 PM ET, with early close days listed by
  NYSE. Source: `https://www.nyse.com/markets/hours-calendars`
- NYSE 2026-2028 holiday/early-close calendar exists as an official NYSE Group
  calendar. Source:
  `https://s2.q4cdn.com/154085107/files/doc_news/NYSE-Group-Announces-2026-2027-and-2028-Holiday-and-Early-Closings-Calendar-2025.pdf`
- Alpaca option snapshots expose latest quote/trade data and greeks in the
  public data API shape already used by this repo. Source:
  `https://docs.alpaca.markets/reference/optionsnapshots`
- `pandas_market_calendars` exposes exchange schedules, early closes, and
  market open/close timestamps through `calendar.schedule(...)` and
  `early_closes(...)`. Source:
  `https://pandas-market-calendars.readthedocs.io/`
- SQLAlchemy JSON/JSONB ORM fields do not automatically persist in-place
  mutations unless using mutable extensions; replacing the entire JSON value is
  safe and matches patterns already used in this repo. Source:
  `https://docs.sqlalchemy.org/en/20/core/type_basics.html#sqlalchemy.types.JSON`
- Pydantic v2 `model_json_schema()`, `ConfigDict(extra="forbid")`, and
  `default_factory` match the repo's existing LLM schema pattern. Source:
  `https://docs.pydantic.dev/latest/concepts/json_schema/`

## 4. Revised architecture

The Opus plan has four layers. I recommend five layers:

```text
Layer 0 - Market hours + position quote snapshots
Layer 1 - Thesis card captured at actual fill
Layer 2 - Deterministic drift engine
Layer 3 - Heavy LLM revalidation service
Layer 4 - Telegram UX and history
```

Layer 0 is the important addition. Without it, Layer 2 and Layer 3 will be
forced to infer thesis drift from one number: option premium.

## 5. Non-negotiable behavioral rules

### 5.1 No auto-trading

The system never places, closes, rolls, or modifies a broker position.
Validation messages are advisory only.

### 5.2 Active positions only

Validation actions only run when `OpenPosition.status == "active"`.

Closed positions keep validation history read-only.

### 5.3 Market-hours gate

Auto drift checks, heavy LLM validation, and validation Telegram alerts run
only when the relevant US market session is open.

For v1, use the regular NYSE equity session:

- open: 9:30 AM ET
- close: 4:00 PM ET
- early close: use the exchange calendar, usually 1:00 PM ET

The user's "2:30" note should be treated as a possible personal notification
cutoff, not as market hours. If wanted, add a later `validation_notify_until`
user setting. Do not mix it into the market calendar helper.

### 5.4 Thesis capture is not market-hours gated

If the user confirms a purchase outside market hours, still create the active
position and a thesis card. Mark live entry quote fields as partial/stale if a
fresh snapshot cannot be fetched. The drift and LLM layers will stay idle until
the next market open.

### 5.5 Manual validation is uncapped, but not duplicated in flight

Manual button presses during market hours should run the heavy LLM every time
the previous validation has completed.

Use a short in-flight lock per position so double taps do not create duplicate
simultaneous LLM calls. This is not a cap; it is idempotency.

### 5.6 Auto validation is throttled

Auto validation needs cooldown and a daily auto cap. Manual validation bypasses
auto cooldown and auto cap.

Recommended v1 settings:

- `position_validation_auto_cooldown_minutes = 30`
- `position_validation_auto_daily_cap = 20`
- `position_validation_shadow_mode = true` for first rollout

## 6. Data model

### 6.1 New table: `position_theses`

Purpose: one thesis card per open position, created when tracking begins.

This table should be treated as immutable after creation except for one
pragmatic case: if we create a partial thesis and then immediately enrich it
with an entry quote snapshot, a controlled one-time update is acceptable. After
that, do not update it. Current state belongs in drift snapshots and
revalidation rows.

Recommended schema:

```sql
CREATE TABLE position_theses (
  id                              UUID PRIMARY KEY,

  open_position_id                UUID NOT NULL UNIQUE
                                  REFERENCES open_positions(id) ON DELETE CASCADE,
  recommendation_id               UUID NOT NULL
                                  REFERENCES recommendations(id) ON DELETE CASCADE,
  user_id                         UUID NOT NULL
                                  REFERENCES users(id) ON DELETE CASCADE,

  schema_version                  VARCHAR(16) NOT NULL DEFAULT 'v1',

  -- Contract identity copied from recommendation so the card is self-contained.
  ticker                          VARCHAR(16) NOT NULL,
  company_name                    VARCHAR(255),
  strategy_source                 VARCHAR(32) NOT NULL,
  strategy                        VARCHAR(32) NOT NULL,
  option_type                     VARCHAR(8) NOT NULL,
  position_side                   VARCHAR(8) NOT NULL,
  strike                          NUMERIC(14,4) NOT NULL,
  expiry                          DATE NOT NULL,

  -- Actual user fill. This is canonical.
  entered_at                      TIMESTAMPTZ NOT NULL,
  entry_option_premium            NUMERIC(14,4) NOT NULL,
  entry_quantity                  INTEGER NOT NULL,
  entry_price_source              VARCHAR(16) NOT NULL DEFAULT 'user_fill',

  -- Best-effort entry market snapshot.
  entry_underlying_price          NUMERIC(14,4),
  entry_option_bid                NUMERIC(14,4),
  entry_option_ask                NUMERIC(14,4),
  entry_option_mid                NUMERIC(14,4),
  entry_implied_volatility        NUMERIC(10,6),
  entry_delta                     NUMERIC(10,6),
  entry_gamma                     NUMERIC(10,6),
  entry_theta                     NUMERIC(10,6),
  entry_vega                      NUMERIC(10,6),
  entry_snapshot_source           VARCHAR(32),
  entry_snapshot_status           VARCHAR(16) NOT NULL DEFAULT 'partial',
  entry_snapshot_notes_json       JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- Original plan copied from recommendation.
  target_option_price             NUMERIC(14,4),
  target_stock_price              NUMERIC(14,4),
  stop_loss_option_price          NUMERIC(14,4),
  underlying_stop_price           NUMERIC(14,4),
  exit_by_date                    DATE,
  expected_holding_days           INTEGER,
  expected_move_percent           NUMERIC(10,6),
  expected_trajectory_json        JSONB NOT NULL,

  -- Catalyst baseline.
  catalyst_kind                   VARCHAR(16) NOT NULL DEFAULT 'none',
  catalyst_event_date             DATE,
  catalyst_baseline_json          JSONB NOT NULL DEFAULT '{}'::jsonb,

  -- Deterministic criteria frozen at entry.
  invalidation_criteria_json      JSONB NOT NULL,

  -- Scores and reasoning, if resolvable.
  direction_score                 INTEGER,
  final_score                     INTEGER,
  contract_score                  INTEGER,
  data_confidence_score           INTEGER,
  reasoning_summary               TEXT,
  key_evidence_json               JSONB NOT NULL DEFAULT '[]'::jsonb,
  key_concerns_json               JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- News baseline. Keep this lightweight; do not store full article bodies.
  news_brief_json                 JSONB NOT NULL DEFAULT '{}'::jsonb,
  news_articles_baseline_json     JSONB NOT NULL DEFAULT '[]'::jsonb,
  news_coverage                   VARCHAR(16),
  stale_news                      BOOLEAN,
  news_published_max_at           TIMESTAMPTZ,
  news_baseline_status            VARCHAR(16) NOT NULL DEFAULT 'unknown',

  -- Decision provenance.
  decision_engine                 VARCHAR(32),
  heavy_model_used                VARCHAR(64),

  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_position_theses_user_created
  ON position_theses(user_id, created_at DESC);

CREATE INDEX ix_position_theses_recommendation
  ON position_theses(recommendation_id);
```

Differences from `validation.md`:

- `entry_option_premium` comes from `OpenPosition.entry_price`, not a fresh
  quote.
- The strategy and contract identity are duplicated into the thesis for audit
  safety.
- Entry snapshot fields are explicitly best-effort.
- `catalyst_passed` is not stored as a mutable boolean. Current catalyst state
  is computed in drift.
- News baseline status is explicit.
- `user_id` is stored to make user-scoped history queries cheap.

### 6.2 New table: `position_revalidations`

Purpose: one row per actual LLM revalidation event.

Recommended schema:

```sql
CREATE TABLE position_revalidations (
  id                              UUID PRIMARY KEY,

  open_position_id                UUID NOT NULL
                                  REFERENCES open_positions(id) ON DELETE CASCADE,
  position_thesis_id              UUID NOT NULL
                                  REFERENCES position_theses(id) ON DELETE CASCADE,
  user_id                         UUID NOT NULL
                                  REFERENCES users(id) ON DELETE CASCADE,

  fired_at                        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  trigger                         VARCHAR(8) NOT NULL, -- auto | manual
  trigger_codes_json              JSONB NOT NULL DEFAULT '[]'::jsonb,

  market_session_date             DATE,
  market_open_at                  TIMESTAMPTZ,
  market_close_at                 TIMESTAMPTZ,

  -- Current quote snapshot at validation time.
  current_underlying_price        NUMERIC(14,4),
  current_option_premium          NUMERIC(14,4),
  current_option_bid              NUMERIC(14,4),
  current_option_ask              NUMERIC(14,4),
  current_option_mid              NUMERIC(14,4),
  current_implied_volatility      NUMERIC(10,6),
  current_delta                   NUMERIC(10,6),
  current_gamma                   NUMERIC(10,6),
  current_theta                   NUMERIC(10,6),
  current_vega                    NUMERIC(10,6),
  quote_source                    VARCHAR(32),
  quote_status                    VARCHAR(16) NOT NULL,

  drift_snapshot_json             JSONB NOT NULL,
  new_headlines_json              JSONB NOT NULL DEFAULT '[]'::jsonb,

  -- Heavy model output after system-side normalization.
  llm_action_raw                  VARCHAR(32),
  llm_action_final                VARCHAR(32) NOT NULL,
  llm_confidence_band             VARCHAR(16),
  llm_summary                     TEXT,
  llm_evidence_json               JSONB NOT NULL DEFAULT '[]'::jsonb,
  proposed_adjustment_json        JSONB,
  normalization_notes_json        JSONB NOT NULL DEFAULT '[]'::jsonb,

  llm_model_used                  VARCHAR(64),
  llm_call_duration_ms            INTEGER,
  delivered_telegram_message_id   VARCHAR(64),

  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_position_revalidations_position_fired
  ON position_revalidations(open_position_id, fired_at DESC);

CREATE INDEX ix_position_revalidations_user_fired
  ON position_revalidations(user_id, fired_at DESC);

CREATE INDEX ix_position_revalidations_auto_cooldown
  ON position_revalidations(open_position_id, trigger, fired_at DESC);
```

I would not add a GIN index on `trigger_codes_json` in v1. Revalidation rows
per position will be low, and cooldown can fetch recent rows by position/time
then inspect trigger codes in Python. Add GIN later if data volume proves it is
needed.

### 6.3 Optional later table: `position_plan_overrides`

If "adjust target" and "adjust stop" should change future threshold alerts,
do not mutate `recommendations`. That table is scanner output.

Use a separate mutable active-plan table:

```sql
CREATE TABLE position_plan_overrides (
  id                              UUID PRIMARY KEY,
  open_position_id                UUID NOT NULL
                                  REFERENCES open_positions(id) ON DELETE CASCADE,
  position_revalidation_id        UUID
                                  REFERENCES position_revalidations(id) ON DELETE SET NULL,
  target_option_price             NUMERIC(14,4),
  stop_loss_option_price          NUMERIC(14,4),
  underlying_stop_price           NUMERIC(14,4),
  exit_by_date                    DATE,
  reason                          TEXT,
  created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_position_plan_overrides_position_created
  ON position_plan_overrides(open_position_id, created_at DESC);
```

For the first implementation, I would ship validation without auto-applying
adjustments. Show proposed adjustments in Telegram. Add "Apply adjustment" as
a follow-up once validation quality is proven. Until then, existing target/stop
alerts should remain based on the original recommendation.

## 7. Layer 0 - market hours

Create `app/services/market_hours.py`.

Add dependency:

```toml
pandas-market-calendars
```

Use a small wrapper around the NYSE calendar:

```python
@dataclass(frozen=True, slots=True)
class MarketSession:
    session_date: date
    open_at: datetime
    close_at: datetime

def current_market_session(now: datetime | None = None) -> MarketSession | None:
    ...

def is_market_open(now: datetime | None = None) -> bool:
    ...

def next_market_open(after: datetime | None = None) -> datetime:
    ...
```

Implementation notes:

- Convert every input to `America/New_York`.
- Ask the exchange calendar for a schedule window covering `after` through at
  least the next 10 calendar days.
- Return `True` only if `open_at <= now < close_at`.
- Respect early closes from the calendar.
- Cache schedule lookups per date range in memory; the same process calls this
  every two minutes.
- Keep this helper independent of Telegram and positions.

Tests:

- normal weekday before open: false, next open same day at 9:30 ET
- normal weekday during market: true
- normal weekday exactly at 16:00 ET: false
- weekend: false, next open Monday or next exchange session
- official holiday: false
- early close day: false after early close
- timezone-aware and naive input handling

Scheduler change:

- Keep the APScheduler job simple, but do not trust it.
- At the top of `PositionMonitor.poll_open_positions()`, return immediately if
  `not is_market_open()`.
- Also gate `RevalidationService.validate_position()` so manual Telegram calls
  cannot bypass the rule.

## 8. Layer 0 - quote snapshots

Create `app/services/positions/snapshots.py`.

This service is the foundation for both existing alerts and validation.

### 8.1 Domain model

```python
@dataclass(frozen=True, slots=True)
class PositionQuoteSnapshot:
    ticker: str
    option_type: str
    position_side: str
    strike: Decimal
    expiry: date
    underlying_price: Decimal | None
    option_bid: Decimal | None
    option_ask: Decimal | None
    option_mid: Decimal | None
    liquidation_premium: Decimal | None
    implied_volatility: Decimal | None
    delta: Decimal | None
    gamma: Decimal | None
    theta: Decimal | None
    vega: Decimal | None
    source: str
    status: Literal["complete", "partial", "unavailable"]
    notes: tuple[str, ...] = ()
```

`liquidation_premium` is the important value:

- long position: use bid, because that is the likely exit sale price
- short position: use ask, because that is the likely buyback price
- if bid/ask is missing, fall back to mid/last with a data-quality note

The current monitor uses a generic premium. Validation should be more precise.

### 8.2 Fetch strategy

For current snapshots:

1. If the user has Alpaca credentials, fetch targeted OCC symbols through
   `AlpacaOptionsClient.fetch_chain(..., symbols=[...])`.
2. Fetch underlying price through `MarketDataService.fetch(..., refresh=True)`.
3. If Alpaca fails or credentials are absent, fetch the option chain through
   `YFinanceOptionsClient`.
4. Match the exact contract by OCC symbol first, then by
   `option_type + strike + expiry`.
5. Return partial snapshots instead of raising when only some fields exist.

For entry snapshots:

- Use the same service, but with short timeouts and best-effort behavior.
- Failure must never block creating the open position.

Important correction to the existing monitor:

- Do not group all users for a ticker behind the first user's Alpaca
  credentials. Public market data is not account-specific, but this creates
  confusing behavior when one user has credentials and another does not.
- For validation snapshots, fetch per user or group by `(ticker, credential
  availability)` with clear ownership.

### 8.3 Tests

Unit-test snapshot building without live network:

- long positions choose bid as liquidation premium
- short positions choose ask as liquidation premium
- Alpaca greeks are preserved
- yfinance snapshots mark greeks missing but still usable
- no matching contract returns `status="unavailable"`
- fallback from Alpaca to yfinance preserves notes
- OCC symbol matching handles standard contracts

## 9. Layer 1 - thesis capture

### 9.1 Trigger point

Modify `app/telegram/handlers/recommendation.py::capture_entry_quantity`.

Current flow:

1. user taps "I bought it"
2. bot asks entry price
3. bot asks quantity
4. code writes `FeedbackEvent(user_action="bought")`
5. code writes `OpenPosition(status="active")`

New flow:

1. Verify user, recommendation, and no active position in a short DB read.
2. Copy the needed recommendation fields into a local dataclass.
3. Outside the DB transaction, attempt a best-effort entry quote snapshot.
4. Open a new transaction.
5. Re-verify no active position for the recommendation.
6. Write `FeedbackEvent`, `OpenPosition`, and `PositionThesis` atomically.
7. Confirm tracking to the user.

Reason: do not hold a database transaction open while doing live network calls.

### 9.2 Canonical entry premium

Use `OpenPosition.entry_price` as:

```text
position_theses.entry_option_premium
```

The user fill is the actual trade. A fresh quote is supporting context only.

### 9.3 Resolving selected contract metadata

Create `app/services/positions/thesis_builder.py`.

Contract metadata resolution order:

1. `WorkflowRun.option_contracts_json` matching:
   - ticker
   - option type
   - position side
   - strike
   - expiry
2. SQL query joining `Candidate` and `OptionContract` by:
   - `Candidate.run_id == Recommendation.run_id`
   - candidate ticker
   - candidate strategy source
   - matching contract fields
3. Recommendation fields only, with missing scores/greeks marked as unknown.

Do not use "most recent OptionContract row for this ticker"; it can select the
wrong strike, expiry, strategy, or run.

### 9.4 News baseline

The current persisted artifacts do not reliably preserve full article metadata
for the selected recommendation. They preserve the brief and user-facing card,
but not necessarily every article timestamp.

Recommended v1 behavior:

- Store whatever is already available from the workflow run:
  `recommendation_card_json`, `candidate_cards_json`, and selected news brief
  fields.
- Add a future enhancement to persist selected candidate article metadata
  during the scan.
- At thesis capture, if article metadata is unavailable, mark
  `news_baseline_status="metadata_missing"` and disable deterministic
  `new_material_news` auto-fire for that position.
- Manual validation can still fetch current headlines and give them to the LLM,
  but it should be honest that exact "since entry" comparison is unavailable.

This is safer than pretending we know the article timestamp baseline.

### 9.5 Existing active positions

Add lazy backfill:

```python
async def ensure_thesis_for_position(position, recommendation, user) -> PositionThesis:
    ...
```

When validation is requested for an active position without a thesis:

- create a thesis using `OpenPosition.entry_price`, `entry_at`, and the
  recommendation row
- resolve contract metadata from run artifacts if possible
- set `entry_snapshot_status="backfilled"`
- set `news_baseline_status="backfilled_or_unknown"`
- mark criteria that require missing entry fields as disabled

This prevents the feature from only working for new trades.

## 10. Expected trajectory

Use a simple plan curve in v1, but compute it over market sessions rather than
calendar days.

Inputs:

- entry date/time
- exchange sessions from entry to exit-by date or expiry
- entry option premium
- target option price
- entry underlying price
- target stock price

If target values are missing, store an empty trajectory with:

```json
{"method": "unavailable", "reason": "missing target"}
```

If available:

```json
{
  "method": "linear_market_sessions",
  "points": [
    {
      "session_index": 0,
      "session_date": "2026-05-12",
      "expected_premium": "1.85",
      "expected_underlying": "145.00"
    }
  ]
}
```

This is still not a pricing model. It is a plan curve: "where would the trade
need to be by now for the original plan to remain on pace?"

Do not use Black-Scholes in v1. The inputs are too noisy and the value added
does not justify complexity yet.

## 11. Invalidation criteria

Represent criteria as JSON generated by typed Pydantic domain models, then
stored in `position_theses.invalidation_criteria_json`.

Recommended shape:

```json
{
  "code": "underlying_stop_breach",
  "severity": "kill",
  "enabled": true,
  "source": "deterministic",
  "field_requirements": ["current_underlying_price", "underlying_stop_price"],
  "condition_human": "Underlying breaches the original stop level.",
  "params": {"side": "bullish", "stop": "142.50"},
  "rationale": "The underlying stop was part of the original risk plan."
}
```

Do not store executable operator JSON as the primary contract. It is too easy
to create a mini query language with ambiguous Decimal/date behavior. Store
typed criterion params and evaluate them in Python functions.

### 11.1 Direction helpers

Map strategy to directional exposure:

- `long_call`: bullish
- `short_put`: bullish
- `long_put`: bearish
- `short_call`: bearish

This matters because "underlying drift" is not an absolute-value check. A
bullish thesis is harmed by downside drift; a bearish thesis is harmed by
upside drift.

### 11.2 Recommended v1 criteria

#### `option_stop_breach`

Severity: kill

Enabled when `stop_loss_option_price` exists.

Logic:

- long: liquidation premium <= stop loss option price
- short: liquidation premium >= stop loss option price

This overlaps with current stop alerts but becomes an explicit thesis
invalidation trigger.

#### `underlying_stop_breach`

Severity: kill

Enabled when `underlying_stop_price` exists.

Logic:

- bullish exposure: current underlying <= underlying stop
- bearish exposure: current underlying >= underlying stop

#### `adverse_underlying_drift`

Severity: degrade

Enabled when entry underlying and expected move exist.

Logic:

- bullish exposure: current underlying is below entry by at least
  `0.75 * expected_move_percent`
- bearish exposure: current underlying is above entry by at least
  `0.75 * expected_move_percent`

Do not make this a kill by default. If it is truly fatal, the stop criteria
should catch it.

#### `premium_trajectory_lag`

Severity: degrade

Enabled when expected trajectory exists and current premium exists.

Logic:

- long: current liquidation premium < 0.75x expected premium for the current
  market-session index
- short: current buyback premium is materially above the expected buyback path

For short positions, the trajectory should be expressed as premium decay from
entry toward target buyback. Do not reuse the long formula blindly.

#### `iv_adverse_move`

Severity: degrade

Enabled when entry IV and current IV exist.

Logic:

- long options: current IV / entry IV < 0.65
- short options: current IV / entry IV > 1.50

Do not mirror "IV crush" onto short options as a negative. IV crush is usually
favorable to short premium.

#### `time_decay_overshoot`

Severity: degrade

Enabled for long options only when expected holding days and premium exist.

Logic:

- days/sessions used > 50% of expected holding window
- current liquidation premium < 50% of entry premium
- target has not been reached

For short premium positions, time decay is not a thesis break by itself.

#### `catalyst_passed_no_follow_through`

Severity: degrade or kill depending on strategy

Enabled when catalyst kind is `earnings` and the catalyst date is before the
current session date.

Logic:

- bullish exposure: post-catalyst underlying did not move favorably by at
  least half expected move
- bearish exposure: same, with direction inverted

Make this degrade in v1 unless the option premium is also below trajectory or
near stop. Earnings reactions can be delayed or IV-driven; one signal alone is
not reliable enough to auto-close.

#### `expiry_imminent_unresolved`

Severity: kill

Enabled when expiry exists and current premium exists.

Logic:

- two or fewer market sessions remain to expiry
- target has not been reached
- position is not already being closed or sold

This is not saying "close now" automatically. It is saying the original
5-10 day thesis no longer has time to play out normally.

#### `new_material_news_candidate`

Severity: degrade

Enabled only when news baseline article metadata exists.

Logic:

- new company, SEC, exchange, regulatory, or major-source headline appears
  after `news_published_max_at`
- headline/source passes a deterministic keyword/source filter:
  guidance, downgrade, upgrade, offering, investigation, lawsuit, SEC,
  FDA, merger, acquisition, bankruptcy, restatement, CEO/CFO resignation,
  analyst target cut/raise, earnings preannouncement

This criterion should trigger LLM review; the deterministic layer should not
decide materiality by itself.

#### `data_unavailable`

Severity: informational

Enabled always.

Logic:

- current option premium unavailable
- current underlying unavailable
- quote source stale/partial

Manual validation can still call the heavy model with the data gap. Auto
validation should not fire solely on this unless the same active position has
failed quote fetches across multiple consecutive market polls.

### 11.3 Informational signals that should not auto-fire alone

Do not auto-trigger the heavy LLM on these alone in v1:

- `premium_above_trajectory`
- `near_target`
- `iv_favorable_move`
- `underlying_favorable_drift`

They are useful context if another trigger fires or if the user manually asks,
but they are not thesis breakage.

## 12. Layer 2 - drift engine

Create `app/services/positions/drift.py`.

The drift engine should be pure and testable:

```python
def evaluate_position_drift(
    *,
    thesis: PositionThesis,
    current: PositionQuoteSnapshot,
    session: MarketSession,
    new_headlines: Sequence[NewsHeadline],
) -> DriftEvaluation:
    ...
```

Return:

```python
@dataclass(frozen=True, slots=True)
class DriftEvaluation:
    fired: tuple[FiredCriterion, ...]
    snapshot: dict[str, Any]
    data_quality: tuple[str, ...]
```

The snapshot should include:

- price drift percent, direction-aware
- premium return percent
- premium versus expected trajectory
- IV ratio
- sessions held
- sessions to expiry
- time used percent
- target/stop distance
- catalyst status
- new headline count and ids

Do not call Telegram, LLM, DB, or network from the drift engine.

## 13. Layer 2 integration with existing monitor

Modify `app/services/positions/monitor.py` carefully.

Recommended integration:

1. At the top of `poll_open_positions()`, return if market closed.
2. Continue doing current target/stop/exit/expiry alerts.
3. Use the new snapshot service instead of `PremiumQuote` when practical.
4. Ensure or backfill a thesis for each active position.
5. Evaluate drift.
6. In shadow mode, log `position_drift_shadow` with fired codes and snapshot.
7. When shadow mode is disabled, call `RevalidationService` for auto-fired
   criteria that pass cooldown.

Do not block existing threshold alerts if validation fails. Existing alerts are
already useful and should be preserved.

## 14. Layer 3 - LLM validation schema

Add a new schema. It can live in `app/llm/schemas.py` beside the existing LLM
contracts, or in `app/services/positions/validation_schemas.py` if we want to
keep position-specific models out of the initial recommendation schemas.

Recommended output:

```python
ValidationAction = Literal[
    "hold",
    "adjust_target",
    "adjust_stop",
    "close",
    "insufficient_data",
]

class ValidationEvidence(_Frozen):
    code: str
    observation: str
    significance: Literal["material", "marginal"]
    source_ref: str | None = None

class ProposedAdjustment(_Frozen):
    target_option_price: Decimal | None = None
    stop_loss_option_price: Decimal | None = None
    underlying_stop_price: Decimal | None = None
    reason: str

class StructuredPositionValidation(_Frozen):
    action: ValidationAction
    confidence_band: Literal["low", "standard", "strong"]
    evidence: list[ValidationEvidence] = Field(min_length=1)
    summary: str = Field(min_length=1, max_length=1200)
    proposed_adjustment: ProposedAdjustment | None = None
```

Use the existing `_Frozen` pattern:

- `extra="forbid"`
- `frozen=True`
- list fields use `default_factory`
- schema generated by `model_json_schema()` through the existing router

Do not add `invalidation_criteria` to the existing `StructuredDecision` in v1.
That would modify the initial recommendation flow and its prompt/tests for a
feature that can work without it.

## 15. Layer 3 - validation service

Create `app/services/positions/revalidation_service.py`.

Public methods:

```python
async def validate_position_manual(user_id: UUID, position_id: UUID) -> ValidationResult:
    ...

async def validate_position_auto(
    position_id: UUID,
    trigger_codes: Sequence[str],
    drift_snapshot: Mapping[str, Any],
) -> ValidationResult:
    ...
```

Responsibilities:

1. Gate market hours.
2. Load user, active position, recommendation, and thesis.
3. Return a market-closed response for manual validation outside hours.
4. Return inactive response if `status != "active"`.
5. Acquire an in-flight lock per position.
6. Fetch a current quote snapshot.
7. Fetch new headline metadata when needed.
8. Evaluate or accept drift snapshot.
9. For auto, enforce cooldown and auto daily cap.
10. Build the LLM input.
11. Call `LLMRouter.decide()` with `StructuredPositionValidation`.
12. Normalize/guardrail the model output.
13. Persist `position_revalidations`.
14. Send Telegram result when appropriate.

### 15.1 In-flight locking

Use one of:

- Redis lock with key `position_validation:{position_id}`
- Postgres advisory lock scoped to the transaction
- A small DB row with status if we later need resumability

Recommended v1: Redis if already configured; fallback to no lock in tests.

Lock behavior:

- manual duplicate while running: answer "A review is already running for this
  position."
- auto duplicate while running: silently skip
- always release in `finally`

### 15.2 Cooldown

For auto only:

- Fetch recent revalidation rows for the position where `trigger="auto"` and
  `fired_at > now - cooldown`.
- If all currently fired codes were recently handled and no material worsening
  occurred, skip.
- If any new code appears, allow.

Material worsening examples:

- underlying stop breach: underlying moved another 1% adverse from last fired
  snapshot
- IV adverse move: IV ratio worsened by another 10%
- premium trajectory lag: trajectory ratio worsened by another 20%
- new material news candidate: at least one new headline id not in last row
- expiry imminent: do not refire more than once per position per day

### 15.3 Auto cap

Apply to auto rows only:

- If auto count for position/session date >= cap, skip auto validation.
- Manual still works.
- Log the cap event once per session.

## 16. LLM prompt

Create `app/llm/prompts/validate_position.md`.

Key prompt rules:

- This is not a new trade recommendation.
- Do not re-run the screener.
- Review only the open position and the frozen thesis.
- Return exactly one schema-valid action.
- Every action, including hold, requires evidence.
- "I cannot tell" is acceptable and should be used when data is insufficient.
- Do not claim live broker execution.
- Do not invent quote fields or news facts.
- For news evidence, cite the provided headline id/title/source.

Hard rules:

```text
1. HOLD requires evidence that no kill criteria fired and current drift is
   within the original plan tolerance.
2. CLOSE requires either:
   a. at least one fired kill criterion, or
   b. a provided new headline whose content directly invalidates the thesis.
3. ADJUST_STOP requires a numeric proposed stop. In v1, it may only tighten
   risk, not widen maximum loss.
4. ADJUST_TARGET requires a numeric proposed target and evidence that the
   original target is no longer realistic or should be harvested sooner.
5. INSUFFICIENT_DATA is required when current option premium and underlying
   price are both unavailable, or when evidence is too thin for any other
   action.
6. HOLD-regret and CLOSE-regret are equal. Do not default to either.
```

## 17. System-side normalization

Prompts are not enough. Add deterministic validation after the model returns.

Recommended rules:

### 17.1 Close guardrail

If final action is `close`, require one of:

- fired criterion with severity `kill`
- evidence code referencing a provided new headline id that the model marks as
  material thesis invalidation

If missing, downgrade:

- to `adjust_stop` if a valid tightening stop is present
- otherwise to `insufficient_data`

Do not blindly downgrade close to `adjust_stop`; an invalid stop proposal is
worse than saying we cannot tell.

### 17.2 Hold guardrail

If any fired kill criterion exists and model returns `hold`, require explicit
evidence explaining why the kill criterion is false-positive or stale.

If not present, normalize to `insufficient_data` and include a note:

```text
Model returned HOLD while a kill criterion fired without explaining the
conflict.
```

### 17.3 Adjustment guardrail

For `adjust_stop`:

- proposed stop must be present
- long option stop must be > 0 and normally below current liquidation premium
- short option stop must be above current buyback premium
- v1 should only tighten risk, not widen it

For `adjust_target`:

- proposed target must be present
- long option target should be above current liquidation premium unless the
  action is effectively "take profit now", which should be `close`
- short option target should be below current buyback premium unless it is
  effectively "close now"

If invalid, normalize to `insufficient_data`.

### 17.4 Evidence guardrail

Every evidence code must be one of:

- a fired deterministic criterion code
- a drift signal key present in `drift_snapshot_json`
- a provided headline id
- `data_quality:*`

Reject generic evidence like "market looks weak" unless it maps to supplied
data.

## 18. Telegram UX

### 18.1 Active position card

Extend `position_list_keyboard(position_id)` to include:

```text
[Validate now] [Validation history]
[Close]        [Delete]
```

Do not remove existing close/delete behavior.

The current `PosCB` callback action enum comment should be updated to include:

- `validate`
- `validation_history`

or create a separate `ValCB` callback to keep validation actions isolated. I
prefer `ValCB` because validation will have more actions later.

### 18.2 Manual validation flow

When user taps Validate:

- if market closed: callback answer plus message with next market open
- if inactive: answer `That position is no longer active.`
- if no thesis: backfill thesis, then validate
- if validation already running: answer `A review is already running.`
- otherwise: answer `Reviewing...` and run service

Telegram should not fake a disabled inline button. Telegram inline keyboards
are static once sent. It is enough to answer the callback and send the
market-closed message when pressed.

### 18.3 Result message

Suggested format:

```text
Position review - AAPL 150 Call exp 2026-05-19

Action: HOLD
Confidence: standard

Why:
- drift_signal:no_breach - No kill criteria fired. Premium is 0.96x plan.
- iv_change - IV is 0.98x entry, inside tolerance.

Summary:
The original thesis is still intact. Price and premium are slightly behind the
ideal plan curve but not enough to invalidate the setup.

Current:
- Underlying: $148.50
- Exit premium: $1.95
- Entry: $1.85
- Target: $3.00
- Stop: $0.90
```

For `close`, use careful language:

```text
Action: REVIEW CLOSE
```

Avoid making it sound like the system has closed anything.

For `insufficient_data`:

```text
Action: INSUFFICIENT DATA

I could not validate the thesis confidently because the current option quote
was unavailable. The position is still being tracked for target, stop, exit
date, and expiry alerts.
```

### 18.4 History view

For active positions:

- show last 5 validation rows
- include timestamp, trigger, final action, and trigger codes
- allow expanding a single full review later

For closed trade history:

- add a "Validation history" button to closed trade cards
- read-only only

### 18.5 Auto-fire message

Auto validation should include why it spoke:

```text
Triggered by: underlying_stop_breach, premium_trajectory_lag
```

This is important because unexpected bot messages are more likely to be trusted
when the trigger is explicit.

## 19. Market-closed behavior

Manual press outside market hours:

```text
Market is closed. Position reviews resume at the next market open:
2026-05-13 09:30 ET.
```

No row should be written to `position_revalidations`.

Auto job outside market hours:

- no drift check
- no LLM call
- no Telegram message
- no row

Position capture outside market hours:

- create open position
- create thesis with partial/backfilled snapshot
- no LLM validation

## 20. Applying adjustments

This is the main product ambiguity in the Opus plan.

If the LLM can say `adjust_stop`, the user will expect something to change.
But the existing threshold monitor reads from `Recommendation`, not a mutable
position plan.

Recommended phased behavior:

### v1

- Show proposed target/stop adjustments in the validation message.
- Do not mutate thresholds automatically.
- Do not add "Apply adjustment" yet.
- Copy says "Suggested adjustment" rather than "Adjusted".

### v1.1

- Add `position_plan_overrides`.
- Add Telegram buttons:
  - `Apply stop`
  - `Apply target`
  - `Ignore`
- Update monitor to read an `active_position_plan()` helper:
  1. latest override if present
  2. fallback to recommendation fields
- Keep original thesis unchanged.

This preserves the audit trail and avoids mutating scanner output.

## 21. Build sequence

The implementation should be split so each PR is verifiable.

### Phase 1 - Market hours helper

Files:

- add `app/services/market_hours.py`
- update `pyproject.toml` and `uv.lock` with `pandas-market-calendars`
- add `tests/test_market_hours.py`
- update `PositionMonitor.poll_open_positions()` top-level guard
- add scheduler tests for monitor trigger or service guard

Ship gate:

- all market-hours tests pass
- existing `test_position_monitor.py` still passes with injected open market
  or helper monkeypatch

### Phase 2 - Position quote snapshots

Files:

- add `app/services/positions/snapshots.py`
- add tests for snapshot source fallback and liquidation premium
- gradually adapt `PositionMonitor` internals to use snapshot where possible

Ship gate:

- current target/stop/exit/expiry behavior is unchanged from the user's
  perspective
- snapshot unit tests cover Alpaca/yfinance field differences

### Phase 3 - Thesis schema and capture

Files:

- add Alembic migration for `position_theses`
- add `app/db/models/position_thesis.py`
- export model in `app/db/models/__init__.py`
- add `app/db/repositories/position_thesis_repo.py`
- add `app/services/positions/thesis_builder.py`
- update `capture_entry_quantity`
- update migration tests expected tables

Tests:

- new position creates thesis
- actual fill becomes `entry_option_premium`
- missing quote creates partial thesis, not failure
- selected contract metadata resolves from run JSON/OptionContract
- existing active position can be backfilled lazily

Ship gate:

- every newly tracked position has a thesis row
- no LLM or auto validation yet

### Phase 4 - Drift engine in shadow mode

Files:

- add `app/services/positions/drift.py`
- add config settings for thresholds and shadow mode
- call drift engine from monitor when market is open
- log `position_drift_shadow`

Tests:

- each deterministic criterion
- direction-aware bullish/bearish drift
- long vs short IV behavior
- trajectory lag for long and short
- missing IV/underlying disables dependent criteria

Ship gate:

- shadow logs are produced
- no Telegram validation alerts yet
- no LLM calls yet

### Phase 5 - LLM revalidation service

Files:

- add `StructuredPositionValidation`
- add `app/llm/prompts/validate_position.md`
- add `app/db/models/position_revalidation.py`
- add `app/db/repositories/position_revalidation_repo.py`
- add `app/services/positions/revalidation_service.py`
- add Telegram template for validation result

Tests:

- manual validation hold
- manual validation close with kill criterion
- close without kill normalizes to insufficient data or valid adjustment
- hold with unexplained kill normalizes
- missing current quote returns insufficient data
- LLM auth/rate-limit failure persists a safe failure or sends safe message
- inactive positions rejected
- market closed rejected

Ship gate:

- manual service can be called from tests without live LLM by stub router

### Phase 6 - Telegram manual UX

Files:

- add validation callback data and keyboard buttons
- update active position cards
- add handlers for validate/history
- add tests in `tests/test_position_handlers.py` or a new validation handler
  test file

Ship gate:

- user can press Validate during market hours
- history shows prior validation rows
- closed positions reject new validation but can show history

### Phase 7 - Auto-fire

Files:

- connect drift fired codes to `RevalidationService.validate_position_auto`
- implement cooldown
- implement auto daily cap
- keep shadow-mode config as a kill switch

Tests:

- auto fires once on new kill criterion
- cooldown suppresses same criterion
- new criterion bypasses cooldown
- materially worse same criterion bypasses cooldown
- auto cap suppresses auto only
- manual bypasses auto cap/cooldown

Ship gate:

- run one week with `position_validation_shadow_mode=true`
- inspect logs and tune thresholds
- then disable shadow mode

### Phase 8 - Optional adjustment application

Files:

- add `position_plan_overrides`
- add active plan resolver
- update monitor to use active plan
- add Telegram "Apply adjustment" actions

Ship gate:

- adjustment is explicit user action
- original thesis remains unchanged
- threshold alerts use latest applied override

## 22. Test strategy

### Unit tests

- market hours helper
- snapshot service
- thesis builder
- contract metadata resolver
- expected trajectory builder
- every deterministic criterion
- validation output normalization
- cooldown policy
- Telegram rendering functions

### Integration tests

- bought flow writes feedback event, open position, and thesis
- monitor guard does nothing outside market hours
- monitor shadow drift logs without LLM
- manual validation persists a row and sends a message
- inactive/closed position cannot be manually validated
- closed trade history can display validation rows

### Regression tests

Run at minimum:

```bash
uv run pytest tests/test_position_monitor.py tests/test_position_handlers.py tests/test_recommendation_handlers.py tests/test_scheduler.py tests/test_migrations.py
```

Then full suite before merge:

```bash
uv run pytest
```

## 23. Code-quality rules for this feature

- Keep deterministic drift pure and independent from DB/network.
- Keep current snapshots as dataclasses; serialize to JSON only at persistence
  boundaries.
- Use Pydantic for LLM input/output schemas.
- Use `extra="forbid"` for model output contracts.
- Store JSONB values as whole replacements, not in-place mutations.
- Do not mutate `recommendations`.
- Do not let quote fetch failures block position creation.
- Do not let validation failures break existing target/stop alerts.
- Keep all Decimal math as Decimal until final JSON formatting.
- Avoid hidden Finviz/private APIs; this feature should not use Finviz at all.

## 24. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Missing entry greeks for yfinance/backfilled positions | Disable criteria that require missing fields; record data-quality notes. |
| LLM action bias | Require evidence for every action, add normalization, allow insufficient data. |
| Close recommendation without real evidence | Enforce close guardrail with kill criterion or referenced material headline. |
| Spam/cost from auto-fire | Shadow mode, cooldown, auto-only daily cap, in-flight lock. |
| Manual double-tap duplicate LLM calls | Per-position in-flight lock. |
| Market holiday/early-close mistakes | Use exchange calendar instead of hand-coded weekdays. |
| Target/stop adjustment confusion | v1 shows suggestions only; v1.1 adds explicit user-applied overrides. |
| Existing active positions lack theses | Lazy backfill on first validation or monitor pass. |
| Network calls inside DB transaction | Fetch best-effort snapshots outside long transactions; persist atomically after. |
| Current threshold alerts regress | Keep current alert tests and migrate monitor in a compatibility phase. |

## 25. Final recommendation

Use the Opus plan as the product direction, not as the implementation spec.

The practical v1 should ship in this order:

1. Market hours helper.
2. Rich quote snapshot service.
3. Thesis capture with actual user fill as canonical entry premium.
4. Deterministic drift in shadow mode.
5. Manual LLM validation.
6. Auto-fire after threshold tuning.
7. Optional explicit adjustment application.

This sequence protects the existing pipeline and position alerts while adding
real thesis validation in a way the current codebase can support.
