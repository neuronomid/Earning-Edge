# Position Validation — Design & Implementation Plan

**Status:** Proposal / pre-implementation. No code changes yet.
**Date:** 2026-05-12
**Owner:** Omid
**Related code:** `app/services/positions/monitor.py`, `app/db/models/open_position.py`, `app/db/models/recommendation.py`, `app/llm/schemas.py`, `app/scoring/`.

---

## 1. Problem

A user receives a recommendation, opens an options position with a 5–10 day window to expiry, and is then **kept in the dark** for the entire hold. The only feedback signals today are:

- Proximity-to-target / proximity-to-stop alerts (price-threshold based).
- Exit-by-date and T-1-to-expiry alerts.

These tell the user *where price is*. They do not answer the only question that actually matters mid-hold:

> **"Is the setup that justified this entry still valid?"**

If the directional thesis breaks, news invalidates the catalyst, IV crushes, or the time-vs-target ratio degrades, the user has no way to know. Currently the only response is hope.

## 2. Goals

1. Give the user, on demand, a structured re-assessment of an open position: *hold, adjust target, adjust stop, close, or insufficient data*.
2. Proactively surface meaningful thesis breakage between scans without spamming.
3. Compare the **state at user's actual fill time** against **current state**, using fixed numeric criteria, not vibes.
4. Avoid LLM action-bias: do not nudge the user toward changes when nothing has changed. Do not nudge toward hold when something has. Both regrets hurt equally.
5. Run only during US regular trading hours, only for active positions.

## 3. Non-goals (v1)

- Auto-closing positions. The system never trades for the user.
- Re-running the full screener. Revalidation is single-ticker, not a fresh scan.
- Multi-leg or roll suggestions. Those land in a separate feature.
- Backtesting the validator itself.

## 4. Constraints (user-stated)

- **Trading hours**: Mon–Fri, **9:30 AM – 4:00 PM ET** (see §15 Verification Needed — user wrote "2:30" but US market closes at 16:00 ET). Outside this window the system must be **completely idle** — no drift checks, no LLM calls, no auto Telegram messages. Manual button presses outside hours should respond with "market closed — try again at next open at HH:MM ET."
- **Closed positions**: Once `OpenPosition.status != "active"`, the system must stop tracking, stop firing drift checks, and stop accepting manual revalidation. The Telegram position card should still display the last revalidation history (read-only).
- **Manual button is uncapped**: User can press as many times as they want during market hours; each press calls the heavy LLM.
- **Auto-fire is allowed to spend LLM budget**: When the drift monitor crosses a real threshold, calling Opus is acceptable.

## 5. Architecture (four layers)

```
                          USER
                           │
                           ▼
              ┌─────────────────────────┐
              │  Layer 4 — Telegram UX  │   "Validate" button, history view,
              │   (button + history)    │   alert delivery
              └────────────┬────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
        ▼                  ▼                  ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Layer 3 —   │    │  Layer 2 —   │    │  Layer 1 —   │
│ LLM Reval    │◀───│ Drift Monitor│◀───│ Thesis Card  │
│ (Opus, on    │auto│ (every 2 min,│reads│  (frozen     │
│  demand or   │fire│  no LLM)     │    │  at fill)    │
│  triggered)  │    │              │    │              │
└──────────────┘    └──────────────┘    └──────────────┘
                           │                  │
                           └────────┬─────────┘
                                    ▼
                        ┌───────────────────────┐
                        │  position_revalidations│  audit log,
                        │       (history)        │  cooldown source
                        └───────────────────────┘
```

- **Layer 1 — Thesis Card** (`position_theses` table): immutable snapshot of the entry thesis, captured at user-confirm time. Contains the falsification rubric.
- **Layer 2 — Drift Monitor**: piggybacks on the existing `poll_open_positions` job. For each active position, computes deterministic drift signals and checks against the rubric. No LLM here.
- **Layer 3 — LLM Revalidation**: invoked on rubric breach OR user button press. Heavy LLM (`decide` route). Output is structured and evidence-bound.
- **Layer 4 — Telegram UX**: button, alert template, history view, post-revalidation actions.

All four layers are **market-hours gated** at the top.

## 6. Schema

### 6.1 New table: `position_theses`

1:1 with `open_positions`. Created when the user confirms purchase. Immutable after creation (no UPDATE).

```sql
CREATE TABLE position_theses (
  id                          UUID PRIMARY KEY,
  open_position_id            UUID NOT NULL UNIQUE
                              REFERENCES open_positions(id) ON DELETE CASCADE,
  recommendation_id           UUID NOT NULL
                              REFERENCES recommendations(id) ON DELETE CASCADE,

  -- entry state (captured at user-confirm via fresh chain pull, NOT scan)
  entered_at                  TIMESTAMPTZ NOT NULL,
  entry_option_premium        NUMERIC(14,4) NOT NULL,
  entry_underlying_price      NUMERIC(14,4),
  entry_implied_volatility    NUMERIC(10,6),
  entry_delta                 NUMERIC(10,6),
  entry_bid                   NUMERIC(14,4),
  entry_ask                   NUMERIC(14,4),

  -- plan (denormalized for self-contained card)
  target_option_price         NUMERIC(14,4),
  target_stock_price          NUMERIC(14,4),
  stop_loss_option_price      NUMERIC(14,4),
  underlying_stop_price       NUMERIC(14,4),
  exit_by_date                DATE,
  expected_holding_days       INTEGER,
  expected_move_percent       NUMERIC(10,6),
  expected_trajectory_json    JSONB,             -- daily expected premium curve

  -- catalyst
  catalyst_kind               VARCHAR(16),       -- earnings|filing|technical|macro|none
  catalyst_event_date         DATE,
  catalyst_passed             BOOLEAN NOT NULL DEFAULT FALSE,

  -- falsification rubric
  invalidation_criteria_json  JSONB NOT NULL,

  -- thesis fingerprint
  direction                   VARCHAR(16),
  direction_score             INTEGER,
  final_score                 INTEGER,
  contract_score              INTEGER,
  data_confidence_score       INTEGER,
  reasoning_summary           TEXT,
  key_evidence_json           JSONB,
  key_concerns_json           JSONB,

  -- news fingerprint
  news_brief_json             JSONB,
  news_coverage               VARCHAR(16),
  stale_news                  BOOLEAN,
  news_published_max_at       TIMESTAMPTZ,

  -- llm context
  decision_engine             VARCHAR(32),
  heavy_model_used            VARCHAR(64),

  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_position_theses_recommendation ON position_theses(recommendation_id);
```

**`invalidation_criteria_json` shape:**

```json
[
  {
    "code": "underlying_breach",
    "condition_human": "Underlying below 142.50",
    "machine_check": {"op": "<", "field": "underlying_price", "value": 142.50},
    "severity": "kill",
    "source": "deterministic",
    "rationale": "Below the 20-day support that anchored the bullish thesis."
  },
  {
    "code": "iv_crush",
    "condition_human": "IV drops more than 35% from entry (0.43)",
    "machine_check": {"op": "<", "field": "iv_ratio_to_entry", "value": 0.65},
    "severity": "degrade",
    "source": "deterministic"
  },
  {
    "code": "guidance_cut",
    "condition_human": "Company issues negative guidance revision",
    "machine_check": null,
    "severity": "kill",
    "source": "llm",
    "rationale": "Thesis priced a guidance raise; a cut inverts the catalyst."
  }
]
```

**`expected_trajectory_json` shape (v1, linear baseline):**

```json
{
  "method": "linear",
  "points": [
    {"day": 0, "expected_premium": 1.85, "expected_underlying": 145.00},
    {"day": 1, "expected_premium": 2.10, "expected_underlying": 145.80},
    ...
    {"day": 5, "expected_premium": 3.20, "expected_underlying": 150.00}
  ]
}
```

### 6.2 New table: `position_revalidations`

N:1 with `open_positions`. One row per revalidation event (auto or manual).

```sql
CREATE TABLE position_revalidations (
  id                          UUID PRIMARY KEY,
  open_position_id            UUID NOT NULL
                              REFERENCES open_positions(id) ON DELETE CASCADE,
  fired_at                    TIMESTAMPTZ NOT NULL DEFAULT NOW(),

  trigger                     VARCHAR(8) NOT NULL,   -- 'auto' | 'manual'
  trigger_codes               JSONB NOT NULL DEFAULT '[]'::jsonb,  -- e.g. ["underlying_breach"]

  -- inputs at fire time
  current_underlying_price    NUMERIC(14,4),
  current_option_premium      NUMERIC(14,4),
  current_iv                  NUMERIC(10,6),
  current_delta               NUMERIC(10,6),
  drift_snapshot_json         JSONB NOT NULL,

  -- llm output
  llm_action                  VARCHAR(24) NOT NULL,  -- hold|adjust_target|adjust_stop|close|insufficient_data
  llm_message                 TEXT,
  llm_evidence_json           JSONB,
  llm_model_used              VARCHAR(64),
  llm_call_duration_ms        INTEGER,

  delivered_telegram_message_id VARCHAR(64),

  created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX ix_position_revalidations_position ON position_revalidations(open_position_id, fired_at DESC);
```

### 6.3 Extension to `StructuredDecision` (LLM contract)

Add an optional field to [app/llm/schemas.py:91](app/llm/schemas.py#L91):

```python
class InvalidationCriterion(_Frozen):
    code: str                           # snake_case identifier
    condition_human: str                # human-readable
    severity: Literal["kill", "degrade"]
    rationale: str
    # No machine_check for LLM-emitted ones; v1 leaves machine evaluation to deterministic.

class StructuredDecision(_Frozen):
    ...
    invalidation_criteria: list[InvalidationCriterion] = Field(default_factory=list)
```

The decide-step prompt is updated to ask for 2–4 thesis-specific invalidation criteria. If the LLM omits them, the system still has the deterministic Layer A criteria.

### 6.4 What NOT to change

- `recommendations` table: untouched. The thesis card lives separately because: (a) most recommendations never become positions; (b) recommendations participate in `parent_recommendation_id` chains and can mutate; (c) thesis = user's committed state, recommendation = scanner output.
- `open_positions` table: untouched. Status, alerts, mute/dismiss state remain as-is.

## 7. Capture: building the Thesis Card at user-confirm

### 7.1 Trigger point

When the user presses "I bought it" in Telegram (existing flow that creates `OpenPosition`), the handler must additionally:

1. Pull a **fresh option chain quote** for the chosen contract (Alpaca primary, yfinance fallback — same clients as the position monitor).
2. Snapshot: `underlying_price`, `implied_volatility`, `delta`, `bid`, `ask`. If the fresh pull fails, fall back to the most recent `OptionContract` row for this contract; mark `entry_*` fields as best-effort and add a `data_confidence` note.
3. Build the **deterministic invalidation criteria** (see §8.1).
4. Compute the **expected trajectory** (see §7.2).
5. Resolve the **catalyst** (see §7.3).
6. Freeze the news brief from `var/runs/<run_id>/news_briefs/<TICKER>.json` (or the in-memory `NewsBundle` if still available); compute `news_published_max_at` = max `published_at` across the bundle's articles.
7. Persist `position_theses` row in the same transaction as `open_positions`.

### 7.2 Expected trajectory (v1)

Linear interpolation between entry and target across `expected_holding_days`:

```
for d in 0..expected_holding_days:
    expected_premium[d] = entry_option_premium
                          + (target_option_price - entry_option_premium) * d / expected_holding_days
    expected_underlying[d] = entry_underlying_price
                          + (target_stock_price - entry_underlying_price) * d / expected_holding_days
```

Not a Black-Scholes model. Not pretending to be accurate. It's the *plan curve* — the answer to "if everything goes as expected, where should we be on day N?" v2 can swap to a Greeks-based decay model.

### 7.3 Catalyst resolution

```
if recommendation.earnings_date is not None:
    catalyst_kind = "earnings"
    catalyst_event_date = recommendation.earnings_date
elif recommendation.strategy_source == "coiled_setup":
    catalyst_kind = "technical"
    catalyst_event_date = None
else:
    # inspect news_brief.named_actions for filing/guidance/macro keywords; else "none"
    catalyst_kind = derive_from_news_brief(...)
    catalyst_event_date = extracted_date or None
catalyst_passed = (catalyst_event_date is not None and catalyst_event_date < today)
```

## 8. Invalidation criteria

### 8.1 Layer A — Deterministic (always present)

Computed at thesis-card-creation time and re-evaluated on every drift tick. The shipped v1 set:

| Code | Severity | Machine check (computed from card + current quote) |
|---|---|---|
| `underlying_breach` | kill | `current_underlying < underlying_stop_price` (if set) |
| `underlying_extreme_drift` | kill | `|current_underlying - entry_underlying_price| / entry_underlying_price > 2 * expected_move_percent` |
| `iv_crush` | degrade | `current_iv / entry_iv < 0.65` (long positions only) |
| `iv_spike` | degrade | `current_iv / entry_iv > 1.50` (short positions only) |
| `premium_below_trajectory` | degrade | `current_premium < 0.75 * expected_trajectory[today_day]` |
| `premium_above_trajectory` | informational | `current_premium > 1.25 * expected_trajectory[today_day]` (signals "consider taking profit early") |
| `catalyst_passed_no_move` | kill | `catalyst_passed AND |current_underlying - entry_underlying| / entry_underlying < expected_move_percent / 2` |
| `time_decay_overshoot` | degrade | `days_held > expected_holding_days * 0.5 AND current_premium < entry_premium * 0.5` (long) |
| `new_material_news` | degrade | any article in fresh news pull with `published_at > news_published_max_at` |
| `expiry_imminent_unrealized` | kill | `(expiry - today).days <= 2 AND current_premium / target_option_price < 0.6` (long) |

The list is **mirrored for short positions** (signs flip).

These thresholds are first-cut. They should be configurable via `app/core/config.py` and tuned against actual position outcomes once the system runs for a few weeks.

### 8.2 Layer B — LLM-emitted (qualitative)

The heavy LLM, at decision time, also emits 2–4 thesis-specific criteria via the new `invalidation_criteria` field on `StructuredDecision`. These have no `machine_check`; they're evaluated qualitatively by the revalidation LLM at fire-time.

**Example LLM-emitted criteria:**
- `guidance_revision` (kill): "Company issues guidance revision in either direction before earnings."
- `competitor_negative_surprise` (degrade): "A peer in the same sub-industry pre-announces weak results."
- `sector_rotation_against` (degrade): "Sector ETF underperforms SPY by >2% over a 5-day window."

Layer B is **not blocking**. If the LLM doesn't emit any (or the call failed), Layer A criteria are sufficient to ship.

### 8.3 Re-evaluation

On every drift tick (during market hours, every 2 min), for each active position:

1. Pull a fresh quote (existing logic in `_fetch_quotes_for_group`).
2. For each criterion in `invalidation_criteria_json` with a `machine_check`, evaluate against current state.
3. Build `drift_snapshot` dict: `{price_drift_pct, iv_change_pct, time_used_pct, premium_vs_trajectory_pct, catalyst_passed, new_news_count}`.
4. Collect `fired_codes` = list of criteria that matched this tick.
5. If `fired_codes` non-empty AND cooldown not active (see §10), trigger Layer 3 LLM revalidation.

## 9. LLM revalidation (Layer 3)

### 9.1 Inputs

- The full `position_theses` row (JSON).
- Current snapshot: underlying price, IV, delta, premium, days held, days to expiry.
- Pre-computed `drift_snapshot` dict.
- `fired_codes` (for auto path; empty for manual).
- Any new headlines since `news_published_max_at` (titles + publish times only — no full re-summarization).

### 9.2 LLM route

`decide` route (heavy model: `MARKET_ANALYSIS_MODEL`, default `anthropic/claude-opus-4.7`). Same router as `app/pipeline/steps/decide.py`. **Not** the lightweight `summarize` route — this is a real reasoning task.

### 9.3 Output schema

New pydantic model in `app/llm/schemas.py`:

```python
ValidationAction = Literal["hold", "adjust_target", "adjust_stop", "close", "insufficient_data"]

class ValidationEvidence(_Frozen):
    code: str                # references a criterion code or "drift_signal:<name>"
    observation: str         # what was observed
    significance: Literal["material", "marginal"]

class StructuredValidation(_Frozen):
    action: ValidationAction
    evidence: list[ValidationEvidence] = Field(min_length=1)
    summary: str             # 2–4 sentences for the user
    proposed_adjustment: dict | None = None   # populated only for adjust_target / adjust_stop
    confidence_band: Literal["low", "standard", "strong"]
```

### 9.4 Symmetric guardrails (the heart of the design)

The user said HOLD-regret and CLOSE-regret hurt equally. The system enforces this structurally:

1. **No default action.** Every action — including `hold` — requires at least one `ValidationEvidence` entry.
2. **`hold` evidence example:** `{code: "drift_signal:no_breach", observation: "No invalidation criterion fired; price drift -1.2% within expected ±3.5%; premium tracking trajectory at 0.96x.", significance: "marginal"}`.
3. **`close` evidence must cite a criterion** with severity `kill`. If the LLM can't, the validator forces the action to `adjust_*` or `insufficient_data`.
4. **`insufficient_data`** is the explicit "I cannot tell" escape hatch. If the LLM can't produce evidence for any action, it must return this. The user sees the raw drift block and decides for themselves. **This breaks the "I have to say something" failure mode.**
5. **Validator-side normalization** (in code, not prompt): if `action == close` and no `kill`-severity criterion fired in `fired_codes`, downgrade to `adjust_stop`. If `action == hold` and a `kill` criterion *did* fire, force the model to either justify in evidence or escalate to `adjust_*`.

### 9.5 Prompt structure (sketch)

```
You are reviewing an OPEN options position to determine whether the original
entry thesis is still valid.

You will be given:
  - THESIS CARD: the locked-in plan from entry time
  - CURRENT STATE: live underlying, IV, premium, days held
  - DRIFT SIGNALS: pre-computed numeric deltas
  - FIRED CRITERIA: invalidation criteria that already matched (auto-fire only)
  - NEW HEADLINES: any news published since entry

You must return EXACTLY ONE action: hold | adjust_target | adjust_stop | close | insufficient_data

HARD RULES:
1. Every action (including HOLD) requires at least one piece of evidence with a code.
2. CLOSE requires citing a 'kill'-severity criterion that fired or a new material news event.
3. ADJUST_TARGET / ADJUST_STOP require evidence and a proposed_adjustment dict.
4. If you cannot find evidence for any of the four substantive actions, return insufficient_data.
5. You are NOT graded on producing a recommendation. You are graded on producing
   evidence-bound conclusions. "I cannot tell" is a fully acceptable answer.
6. HOLD-regret and CLOSE-regret are equal weight. Do not bias toward either.

Output strictly the StructuredValidation JSON schema. No prose outside the JSON.
```

### 9.6 Telegram delivery

After every revalidation (auto or manual), send a message:

```
🔍 Position review — AAPL 150 Call exp 2026-05-19

Action: HOLD
Confidence: standard

Evidence:
• drift_signal:no_breach — No invalidation criteria fired. Price drift -1.2%
  within expected ±3.5%. Premium tracking trajectory at 0.96x.

Summary:
The thesis is intact. Underlying is consolidating but within the expected
range for day 3 of a 6-day hold. IV is flat. No new material news.

[View history] [Validate again]
```

For `close` / `adjust_*`, the proposed adjustment is shown explicitly with current vs. proposed numbers.

For `insufficient_data`:

```
🔍 Position review — AAPL 150 Call

Action: I cannot tell

I lack the evidence to recommend a substantive action confidently.

Current state:
• Underlying: $148.50 (entry $147.20)
• Premium: $1.95 (entry $1.85, target $3.00)
• Days held: 3 / 6
• IV: 0.41 (entry 0.43)

The thesis card and full drift report are below. Decide based on your own read.
[View thesis card] [View drift signals]
```

## 10. Cooldown & rate-limiting

### 10.1 Auto-fire cooldown (per criterion, per position)

Once an auto-revalidation fires for criterion code `X` on position `P`, suppress further auto-fires for `(P, X)` for **30 minutes** unless:

- A *different* criterion fires (allow).
- The *same* criterion fires but with materially worse numbers (allow). Definition of "materially worse" per criterion:
  - `underlying_breach`: underlying drops another 1% from the level at last fire.
  - `iv_crush`: IV drops another 5 percentage points from last fire.
  - `new_material_news`: any new article since last fire (the timestamp moves regardless).
  - Others: same direction, 25% magnitude beyond last fire.

Implementation: query the latest row from `position_revalidations` for `(open_position_id, trigger_codes @> [X], fired_at > now() - interval '30 min')`. If present, compare current observed values against `current_underlying_price` / `current_iv` on that row.

### 10.2 Manual button — no cap

Per user instruction. Every manual press calls the heavy LLM. The button is only enabled during market hours and only for `status = 'active'` positions.

### 10.3 Global per-position max

Soft cap: 50 revalidations per position per calendar day, *combined* auto+manual. This is a safety valve against runaway cost in a bug scenario. Reaching the cap surfaces a Telegram message: "This position has been revalidated 50 times today — pausing automated reviews until tomorrow. Manual button still works." (Or strictly halt manual too — decision in §15.)

## 11. Telegram UX

### 11.1 Position card surface

Each active position in the user's "Open positions" list gets two new buttons:

```
[Validate now]  [View history]
```

- **Validate now**: enabled iff `market_open` and `status == 'active'`. Pressing it queues an immediate Layer 3 revalidation. While in-flight, button shows "Reviewing…" and is disabled.
- **View history**: shows the last 5 entries from `position_revalidations`, formatted as:
  ```
  2026-05-12 11:42 ET — auto (iv_crush)        → HOLD
  2026-05-11 14:08 ET — manual                  → ADJUST_STOP
  2026-05-11 09:55 ET — auto (premium_below_*)  → HOLD
  ```
  Each row is tappable to expand the full revalidation message.

### 11.2 Outside market hours

Pressing Validate at 8 PM ET:

> Market is closed. Position reviews are paused until the next open at 9:30 AM ET tomorrow (Mon 2026-05-13). I'll auto-review if anything material happens during the trading day.

### 11.3 Auto-fire alert

When Layer 2 fires Layer 3 automatically, the resulting message is delivered through the same `AiogramNotifier` + `enforce_tone` path used for stop/target alerts. The message includes the `trigger_codes` that fired ("triggered by: iv_crush, premium_below_trajectory") so the user understands *why* the system spoke up.

### 11.4 Re-using mute / dismiss UX?

**No.** Mute and dismiss in [open_position.py:65–86](app/db/models/open_position.py#L65-L86) are scoped to *threshold alerts* (target_hit, stop_hit). Revalidation is a separate concept and deserves separate controls if any are needed. v1: no mute on revalidation; the 30-minute per-criterion cooldown is the only throttle.

## 12. Market-hours gating

### 12.1 Single source of truth

A new helper, `app/services/market_hours.py`:

```python
from datetime import datetime, time
from zoneinfo import ZoneInfo

NY = ZoneInfo("America/New_York")
MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)   # See §15 Verification Needed

def is_market_open(now: datetime | None = None) -> bool:
    now = (now or datetime.now(NY)).astimezone(NY)
    if now.weekday() >= 5:   # Sat=5, Sun=6
        return False
    if is_us_market_holiday(now.date()):
        return False
    return MARKET_OPEN <= now.time() < MARKET_CLOSE

def next_market_open(after: datetime) -> datetime: ...
```

Holiday calendar source: `pandas_market_calendars` (already a candidate dep) or a hand-curated `app/data/us_market_holidays.py` for 2026. **Half-trading days** (early close, e.g. day after Thanksgiving, Christmas Eve) need their early-close time encoded so the system stops at 1:00 PM ET on those dates, not 4:00 PM.

### 12.2 Gate points

- **Layer 2 (drift monitor)**: the existing `poll_open_positions` cron is already gated to Mon–Fri 9–16 ET in [scheduler/jobs.py]. Tighten to `is_market_open()` check at the top of the function — single line guards both the existing threshold alerts and the new drift logic.
- **Layer 3 (LLM revalidation)**: hard-gated. Auto-fire path: refuse to run outside hours. Manual path: button response says "market closed" and creates no `position_revalidations` row.
- **Layer 4 (Telegram)**: button state reflects gate; outside hours the button shows "Validate (market closed)" and is non-functional but visible.

### 12.3 Edge case — position opened pre-market

If the user buys a position before market open (e.g. extended hours / fills overnight), the thesis card *is still created* immediately — it's just based on stale-but-recent quotes. The drift monitor will pick up the position when the market opens at 9:30 AM ET.

## 13. Closed-position handling

### 13.1 Status taxonomy

Existing `OpenPosition.status` values in code: `active`, `closed_expired`. The user-confirmed exits (Sold button) almost certainly create a `closed_sold` (or similar) value — verify during build (see §15).

**Rule:** all four layers operate **only on `status == 'active'` positions.**

### 13.2 Transition handling

When a position closes:
- Drift monitor's `OpenPositionRepository.list_active()` excludes it on next tick → no further auto-fires. Already the existing behavior.
- Any in-flight Layer 3 LLM call should still complete (we already paid for the inference) but the resulting `position_revalidations` row is written; the Telegram message is suppressed if the position is now closed.
- The Telegram "Open positions" view no longer renders the position with action buttons.

### 13.3 Closed-position history view

A separate "Closed positions" view shows previously-active positions with their full revalidation history visible (read-only). The history is preserved indefinitely — useful for self-review and for tuning the criteria thresholds. Don't garbage-collect on close.

### 13.4 Cleanup vs. retention

`position_theses` and `position_revalidations` rows are kept after position closure (cascade-delete only on `open_positions` delete, which is itself unlikely — closure is a status change, not a row delete). No automatic cleanup. Disk storage cost is negligible.

## 14. Build sequence (phased)

Each phase is independently shippable and adds value on its own.

### Phase 1 — Foundation (database + capture, no UX change)
- Alembic migration: `position_theses`, `position_revalidations`.
- `app/db/models/position_thesis.py`, `position_revalidation.py`.
- `app/db/repositories/position_thesis_repo.py`, `position_revalidation_repo.py`.
- Hook into the "I bought it" handler to build & persist the thesis card.
- Deterministic Layer A invalidation criteria builder (`app/services/positions/thesis_builder.py`).
- Linear expected_trajectory computer.
- Catalyst resolver.
- Tests: thesis card is built correctly across all strategies (long_call, long_put, short_*) and both catalyst types (earnings, coiled_setup).

Ship gate: every new position written after this PR has a thesis card.

### Phase 2 — Market hours helper
- `app/services/market_hours.py` with `is_market_open`, `next_market_open`, holiday calendar.
- Refactor the existing `poll_open_positions` cron's day/hour gate to use it (DRY win).
- Tests: holiday dates, half-trading days, weekend, pre/post market.

### Phase 3 — Drift monitor (Layer 2, no LLM yet)
- `app/services/positions/drift_monitor.py` — pure computation of `drift_snapshot` and `fired_codes`.
- Extend `PositionMonitor.poll_open_positions` to call it after the existing threshold check.
- For now, **only log** the drift snapshot — don't trigger anything. This is the dry-run phase to verify the thresholds.
- Tests: each criterion fires correctly on synthetic inputs.

Ship gate: drift snapshots logged for a week. Inspect logs, tune thresholds.

### Phase 4 — LLM revalidation (Layer 3)
- New `StructuredValidation` schema, `ValidationCriterion`, `ValidationEvidence`.
- New prompt: `app/llm/prompts/validate_position.md`.
- New service `app/services/positions/revalidation_service.py` orchestrating: input build → LLM call (decide route) → validator-side normalization → `position_revalidations` row → Telegram notification.
- Extend `StructuredDecision` with `invalidation_criteria` field (Layer B); update the decide prompt to ask for them.
- Cooldown logic.
- Tests: hold/close/adjust/insufficient_data paths, cooldown, symmetry guardrails, validator normalization.

### Phase 5 — Auto-fire wiring
- Connect drift_monitor `fired_codes` → revalidation_service.
- Per-criterion 30-min cooldown enforced.
- Daily global cap of 50 per position.
- Tests: end-to-end auto-fire scenarios.

### Phase 6 — Telegram UX
- Add "Validate" and "View history" buttons to each position card.
- Implement the validate-now handler.
- Implement the history view (paginated; last 5 with expand).
- Market-closed-state button copy.
- Tests: button visibility per status & market hours.

### Phase 7 — Polish
- Tune thresholds based on first month of real data.
- Consider richer `expected_trajectory` (Greeks-based decay model).
- Consider showing the thesis card itself in Telegram (read-only "View thesis card" button).

## 15. Verification needed (open questions for user)

1. **Market hours** — User wrote "9:30 to 2:30 NYT". US equity/options market is 9:30 AM – 4:00 PM ET. Plan assumes **9:30 AM – 4:00 PM ET**. Confirm or correct. If you genuinely want a personal cutoff (e.g., "don't alert me after 2:30 PM because I can't act on it"), that's a different concept — a *user notification window*, not market hours. We could add it as a separate setting later.
2. **Closed-position status values** — Plan says "operate only on `status == 'active'`". Currently I see `active` and `closed_expired` in code. Confirm the user-sold close path uses a similar `closed_*` value and not e.g. row deletion.
3. **Global daily cap behavior on reach** — When a position hits 50 revalidations in a day, do we pause **everything** (including manual button) or only the auto path? I'd default to pausing only auto and letting the user keep pressing manually — but it's a question.
4. **Half-day market closes** — The plan respects early-close days (Black Friday, Christmas Eve, etc.) and ends at 1 PM ET. OK to include this complexity in v1, or defer?
5. **Multi-position same ticker** — If the user holds two positions on AAPL with different strikes, each has its own thesis card and is revalidated independently. Confirmed correct?
6. **Rolled positions** — If/when rolling is supported (parent chain), should the new position inherit a fresh thesis card or carry the parent's? Recommend fresh: a rolled position is a new commitment with new entry numbers.
7. **Should the user be able to *edit* the thesis card?** E.g., raise the target after a strong move. Recommend: **no**. The card is the entry-time contract; edits would defeat the comparison. Instead, if the user wants to change target/stop, they should explicitly trigger an `adjust_*` action through the revalidation flow.

## 16. Testing strategy

- **Unit tests** for each deterministic criterion against synthetic inputs.
- **Unit tests** for the `StructuredValidation` validator's symmetry guardrails (close-without-kill, hold-with-kill, insufficient_data path).
- **Integration tests** for the auto-fire pipeline using the existing test heuristic-fallback LLM (no live LLM calls in CI).
- **Live shadow run for 1 week before Phase 5**: drift monitor logs fired_codes only, no alerts sent. Inspect logs to validate threshold sanity before going live.
- **Backtest harness (Phase 7)**: replay last N closed positions through the drift monitor against historical quotes; measure how often each criterion would have fired and how often it would have been right. Use this to tune thresholds.

## 17. Risks & mitigations

| Risk | Mitigation |
|---|---|
| LLM action-bias (recommends changes when nothing changed) | Symmetric guardrails in §9.4; `insufficient_data` escape hatch; validator-side normalization. |
| Auto-fire spam | Per-criterion 30-min cooldown; daily 50-cap; only fires when a criterion actually matched. |
| Cost blowout from manual spam | Manual is uncapped per user request, but global daily cap of 50 acts as a soft fuse. |
| Stale entry-time data (quote fetch fails at fill) | Fall back to last `OptionContract` row; mark card with degraded `data_confidence`. |
| Thresholds wrong | Shadow-log for a week (Phase 3 → Phase 5); tune from real data; thresholds in config, not hardcoded. |
| Position closes during in-flight revalidation | LLM call completes, row written, Telegram message suppressed. |
| Market holiday miscount | Use `pandas_market_calendars` rather than rolling our own; cover half-days. |
| User confused by `insufficient_data` | UX copy explains: "I lack evidence — here's the raw situation, you decide." Show full drift block. |
| Catalyst kind mis-classified | Layer A criteria don't depend critically on catalyst_kind; only `catalyst_passed_no_move` does. Mis-classification produces missing alert, not wrong alert. |

## 18. Out of scope for this plan

- Auto-execution / auto-close. The system never trades.
- Multi-leg position support.
- Roll suggestions.
- Position sizing changes mid-hold.
- Cross-position correlation alerts (e.g., "your three calls are all single-sector").
- Dashboard UI for revalidations (only Telegram in v1).
