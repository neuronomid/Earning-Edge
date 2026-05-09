# PRD: Earning Edge — Telegram Options Recommendation Agent

**Version:** V2.0
**Status:** Live system specification, derived from the current codebase.

## 1. Product Summary

Earning Edge is a Telegram-based agent that scans the U.S. equity market on a
user-defined schedule, runs two complementary Finviz screening strategies,
scores each candidate with a deterministic engine, asks a heavy LLM route to
choose at most one trade, and sends the user a single options recommendation
(or a No Trade message) per run. After the user reports a fill, the system
tracks the open position in real time, sends target / stop / expiry alerts,
and updates the user's account balance with realized P/L when the position
closes.

The system never executes trades. Every recommendation is a structured note
the user manually reviews and acts on inside their own broker.

Default scheduled run:

```text
Monday 10:30 AM in the user's local timezone
```

Manual runs are triggered from the persistent main menu.

---

## 2. Core Product Objective

Across catalyst-driven and structure-driven setups, the agent answers one
question per run:

> "Which option contract has the strongest opportunity right now, considering
> trend, catalyst, market context, option-chain liquidity, pricing, and
> expected move?"

The output gives the user:

- ticker and company
- direction (bullish/bearish)
- option contract (strategy, type, position side)
- strike and expiry
- suggested entry premium
- target option price, stock target, stop-loss option price
- exit-by date and expected holding days
- suggested quantity (or watchlist-only status)
- estimated max loss and account-risk percentage
- earnings date snapshot
- confidence score and risk level
- concise reasoning, key evidence, and key concerns

After delivery, the recommendation message carries inline actions for
follow-up: explanation, risk breakdown, alternatives, save note, "I bought
it", and "I skipped it".

---

## 3. End-to-End Workflow

### 3.1 Scheduled Run

```text
APScheduler cron tick (user timezone)
   ↓
Acquire per-user run lock (Redis, 900 s TTL)
   ↓
Create workflow_runs row (status=running)
   ↓
Run Strategy A (Catalyst Confluence — Finviz)
Run Strategy B (Coiled Setup — Finviz)
   ↓ ↓ (concurrent, asyncio.gather)
Merge by ticker, A wins ties → up to 10 candidates
   ↓
For each candidate (concurrent):
  Fetch market snapshot (yfinance + optional Alpha Vantage)
  Fetch news bundle (web search → article fetch → Gemini summary)
  Fetch option chain (Alpaca preferred, yfinance fallback)
  Score direction, contract, confidence
  Compute Greek-based exit target with deterministic fallbacks
  Size position
   ↓
Pick top 4 finalists by final_score, confidence, direction_score
   ↓
Heavy LLM (Claude Opus 4.7 Thinking) chooses: recommend / watchlist / no_trade
   ↓
Persist candidates, contracts, recommendation
   ↓
Send Telegram status + main recommendation (or No Trade message)
   ↓
Archive run summary, candidate cards, contract logs, recommendation card
   ↓
Release run lock
```

### 3.2 Manual Run

Tap **🚀 Run Scan Now** in the main menu. The same pipeline runs and the
same lock guards prevent concurrent runs for the same user.

### 3.3 Position Monitoring Loop

Independent of scans, a background job polls open positions every two
minutes during U.S. market hours (Mon–Fri, 09:00–16:59 America/New_York). For
each ticker the monitor batches OCC symbols into one Alpaca call and falls
back to yfinance, then evaluates target / stop / exit-by / expiry-1-day
alert conditions.

---

## 4. Product Boundaries

### 4.1 The agent must

1. Run two Finviz screens (Strategy A + Strategy B) per scan via Playwright.
2. Cache Finviz query results in Redis for 600 seconds.
3. Validate Finviz tickers against yfinance and Finnhub before scoring.
4. Merge and dedupe candidates by ticker, with Strategy A winning ties.
5. Tag every candidate with its `strategy_source`.
6. Pull option chains from Alpaca first, fall back to yfinance.
7. Restrict allowed strategies to the user's `strategy_permission`.
8. Choose only one direction per stock per run (no simultaneous call + put).
9. Produce one recommendation, one watchlist setup, or one no-trade result.
10. Send the result through Telegram with the matching inline keyboard.
11. Persist the full evidence trail (run summary, candidate cards, contract
    logs, recommendation card, Telegram message text).
12. Track open positions, send TP / SL / exit-by / expiry alerts, and apply
    realized P/L to the user's stored account balance.
13. Allow user-configurable account size, risk profile, broker, timezone,
    strategy permission, max contracts, alert mute duration, API keys, and
    cron schedules.

### 4.2 The agent must not

1. Place trades or manage broker orders.
2. Use Finviz private/internal APIs.
3. Use the lightweight model for the final decision route.
4. Fabricate prices, contracts, earnings dates, or LLM outputs.
5. Start a second run for the same user while one is already active.
6. Send recommendations without a valid OpenRouter API key.

---

## 5. Finviz Dual-Strategy Screener

### 5.1 Browser Automation Method

- Playwright headless browser (`finviz_headless` setting).
- Each query is a fully encoded Finviz URL — `page.goto(url)` only.
- HTML table parsed via the accessibility tree / DOM extractor.
- Redis cache keyed by `screener:{strategy_source}:{hash}:{date}`, TTL 600 s.
- Concurrency limited to 2 simultaneous Finviz fetches via an `asyncio.Semaphore`.
- No private APIs or persistent login.

### 5.2 Strategy A — Catalyst Confluence

Targets stocks with an upcoming earnings catalyst. Implemented in
`app/services/finviz/strategies.py`:

- Filters: `earningsdate_nextweek`, `geo_usa`
- Sort: `-marketcap` (largest market cap first)
- Variants run: `earningsdate_nextweek`
- `strategy_source = "catalyst_confluence"`

Strategy A includes a backup-source pipeline (yfinance + Finnhub earnings
calendars) that fills in missing rows when Finviz returns thin results, with
ticker reconciliation handled by `CandidateReconciler`.

### 5.3 Strategy B — Coiled Setup

Targets large-cap U.S. names trading above key moving averages with healthy
RSI, bullish beta, and 52-week-high proximity:

- Filters: `cap_midover`, `geo_usa`, `sh_avgvol_o1000`, `sh_opt_option`,
  `sh_price_o20`, `ta_sma50_pa`, `ta_sma200_pa`, `ta_highlow52w_b20h`,
  `ta_beta_o1`, `ta_rsi_40to70`
- Sort: `-relativevolume`
- Variants run: `ta_beta_o1`
- `strategy_source = "coiled_setup"`

Strategy B does not require an earnings date and does not consult backup
earnings calendars.

### 5.4 Merge Rule

The two strategies execute concurrently. Results are merged into a single
deduped list, Strategy A winning ticker ties, capped at 10 candidates total
(5 per strategy before merge).

### 5.5 Screener Status Reporting

Every run records one of:

| Value | Meaning |
|---|---|
| `success` | Both A and B returned candidates |
| `partial` | Only one strategy returned candidates |
| `failed` | Both strategies returned no candidates |

Partial / failed runs surface a warning string in the Telegram message:

- "Coiled-setup screen returned no candidates this scan…"
- "Catalyst screen returned no setups this scan…"
- "Coiled-setup screen failed this scan…"
- "Catalyst screen failed this scan…"
- "Both screening strategies failed to return candidates."

### 5.6 Required Extracted Fields

For each row returned by either strategy, the extractor captures (when
present): ticker, company name, market cap, current price, daily change %,
volume, sector, screener rank, and earnings date (Strategy A only). Missing
fields are filled in by backup data sources or remain null with downgraded
confidence.

---

## 6. Data Sources

### 6.1 Primary Source Matrix

| Data Need | Primary | Backup |
|---|---|---|
| Screener candidates | Finviz dual-strategy via Playwright | Finnhub + yfinance earnings calendars |
| Earnings date verification | Finviz (Strategy A) | yfinance, Finnhub |
| Market cap, current price | Finviz, yfinance | Alpha Vantage |
| Historical OHLCV | yfinance | Alpha Vantage |
| Option chains | Alpaca Options Snapshots API | yfinance |
| Option Greeks | Alpaca | yfinance / estimated |
| Option bid/ask/mid | Alpaca indicative quotes | yfinance |
| Live position quotes | Alpaca (batched per ticker) | yfinance |
| News + catalysts | Web search → article fetcher | Company IR pages |
| News summarization | OpenRouter (lightweight model) | — |
| Final decision | OpenRouter (heavy model) | Heuristic finalist selection |

### 6.2 Alpaca Role

Alpaca is the preferred options provider when both `alpaca_api_key` and
`alpaca_api_secret` are set on the user. The options service iterates ticker
variants (e.g. `BRK.B` ↔ `BRK-B`) and falls back to yfinance when:

- credentials are missing
- authentication fails
- the chain is empty
- the ticker variant resolves nothing usable

### 6.3 yfinance and Alpha Vantage Roles

- yfinance is the default market-data and options-fallback source.
- Alpha Vantage is optional, used as a supporting overview / price-history
  cross-check, never as the primary option-chain provider.

### 6.4 News Pipeline

```text
Search → Article fetch → Lightweight LLM summary → Coverage policy → NewsBrief
```

The news service is Redis-cached (key prefix `news:<TICKER>`, TTL 7200 s).
When coverage is thin or relies on company IR pages, the brief's news
confidence is capped (45 / 50 / 60 / 70 depending on severity) and a
contextual note is appended.

### 6.5 Cache and Fallback Rule

```text
Try primary → Try secondary → Use Redis cache when service supports it →
If critical fields still fail, downgrade confidence or return No Trade.
```

Current Redis-backed caches:

- Finviz screener results (`finviz_query_cache_ttl_seconds`, default 600 s)
- News bundles (TTL 7200 s)

---

## 7. LLM Routing

### 7.1 OpenRouter

Each user must provide an OpenRouter API key during onboarding. The key is
validated with a live test call, stored encrypted at rest, and used for
both LLM routes. Without a valid key, the agent skips news summarization
and the heavy decision step.

### 7.2 Heavy Reasoning Route — `decide()`

- Default model: `anthropic/claude-opus-4.7`
- Reasoning effort: `medium` (configurable via
  `market_analysis_reasoning_effort`)
- Reasoning tokens are captured but excluded from billing where possible
  (`reasoning.exclude=True`)
- Receives a structured `DecisionInput` payload (top finalists with
  pre-scored contracts, sizing context, news brief, market snapshot)
- Must return a strict JSON schema with `recommend / watchlist / no_trade`,
  `chosen_ticker`, `chosen_contract`, `reasoning`, `key_evidence`,
  `key_concerns`, `final_score`, `watchlist_tickers`
- On transient failure → heuristic top-of-list selection
- On authentication failure → blocked no-trade result

### 7.3 Lightweight Route — `summarize()`

- Default model: `google/gemini-3.1-flash-lite-preview`
- Used for news article summarization and lightweight synthesis tasks
- Returns plain text

### 7.4 Hard Separation Rule

`LLMRouter.decide()` raises `ValueError` if it would point at the lightweight
model. The two routes cannot be swapped at runtime.

### 7.5 Decision Finalist Cap

The pipeline analyzes up to 10 candidates but only forwards the top 4
(`DECISION_FINALIST_LIMIT = 4`) to the heavy decision route, sorted by
final score → confidence → direction score.

---

## 8. User Settings

### 8.1 Editable Fields

| Setting | UX Surface | Required |
|---|---|---:|
| Telegram chat ID | automatic | Yes |
| Account size | Settings | Yes |
| Risk profile | Settings | Yes |
| Broker | Settings | Yes |
| Timezone (label + IANA) | Settings | Yes |
| Strategy permission | Settings | Yes |
| Max contracts | Settings | Yes |
| Alert mute duration | Settings | Yes |
| OpenRouter API key | API Keys | Yes |
| Alpaca API key + secret | API Keys | Optional |
| Alpha Vantage API key | API Keys | Optional |
| Cron jobs | Manage Schedule | Yes (default created) |

Persisted but not currently exposed in Telegram:

- `custom_risk_percent`
- `max_option_premium`

### 8.2 Timezone Options

| Label | IANA |
|---|---|
| PT | America/Vancouver |
| MT | America/Edmonton |
| CT | America/Winnipeg |
| ET | America/Toronto |
| AT | America/Halifax |
| NT | America/St_Johns |

### 8.3 Defaults

| Setting | Default |
|---|---|
| Timezone | ET / America/Toronto |
| Risk profile | Balanced |
| Strategy permission | long_and_short |
| Max contracts | 3 |
| Alert mute duration | 1 day |
| Default cron job | Monday 10:30 |
| Recommendation threshold | final score ≥ 68 with no blockers |

### 8.4 Alert Mute Duration Options

The user controls how long a TP/SL alert stays muted after they tap "Mute":

| Value | Behavior |
|---|---|
| `2h` | Suppress for 2 hours |
| `1d` | Suppress for 24 hours (default) |
| `1d_before_expire` | Suppress until 09:30 ET on (expiry − 1 day) |
| `3d_before_expire` | Suppress until 09:30 ET on (expiry − 3 days) |
| `forever` | Suppress until after expiry (effectively dismissed) |

Tapping "Okay" on a TP/SL alert dismisses it permanently for that side
of the position (`target_dismissed` / `stop_dismissed`).

---

## 9. Risk Profile and Position Sizing

### 9.1 Risk Profile Defaults

| Risk Profile | Long Risk Budget | Short Notional Cap |
|---|---:|---:|
| Conservative | 1% | 10% of account |
| Balanced | 2% | 20% of account |
| Aggressive | 4% | 35% of account |

`custom_risk_percent` overrides the long risk budget when set.

### 9.2 Long Option Sizing

```text
trade_budget          = account_size × risk_percent
max_loss_per_contract = ask × 100
quantity              = floor(trade_budget / max_loss_per_contract)
quantity              = min(quantity, max_contracts)
quantity              = 0 if ask > max_option_premium
```

Quantity 0 → watchlist-only.

### 9.3 Short Option Sizing

```text
max_short_notional    = account_size × short_notional_cap_pct
per_contract_exposure = strike × 100
quantity              = floor(max_short_notional / per_contract_exposure)
quantity              = min(quantity, max_contracts)
```

- `short_put`: max-loss text shows approximate notional exposure.
- `short_call`: max-loss text reads "Undefined for naked short call".
- Both flag `broker_verification_required = true` and use
  `Broker/margin dependent` margin language.

### 9.4 Strategy Permission Enforcement

Sizing raises `SizingPermissionError` if the contract violates the user's
permission (e.g. short contract under `long`-only permission). The pipeline
catches this and falls back to a watchlist-only sizing result.

---

## 10. Telegram Bot UX

### 10.1 General Rules

- Persistent reply keyboard for the main menu — no slash commands required
  for normal use.
- Inline keyboards for recommendation actions, schedule actions, position
  alerts, settings, and confirmations.
- Tone: friendly, concise, cautious around risk. The orchestrator runs
  `enforce_tone()` on every outgoing message body.

### 10.2 Main Menu (8 buttons)

```text
🚀 Run Scan Now            📊 Last Recommendation
📂 Positions               📜 History
🗓 Manage Schedule         ⚙️ Settings
🔑 API Keys                ❓ Help
```

### 10.3 Recommendation Inline Keyboard

```text
🔍 Why this?            ⚖️ Risk / Sizing
📈 Alternatives         📘 Save Note
✅ I bought it          ❌ I skipped it
```

- "Alternatives" walks the chain of next-best setups using
  `parent_recommendation_id` linkage.
- "I bought it" starts an FSM that captures fill price → quantity → opens
  an `OpenPosition` row and starts position tracking.
- "I skipped it" stores a `feedback_events` row with `user_action="skipped"`.
- "Why" / "Risk / Sizing" / "Save Note" reveal stored evidence, sizing
  detail, or a savable note string.

### 10.4 Position Alert Keyboards

For TP / SL alerts:

```text
Sold    Mute    Okay
```

- **Sold** → FSM: capture sell price, compute P/L, close the position,
  apply realized P/L to user's account size, log a `feedback_events` row
  with `user_action="closed"`.
- **Mute** → suppress further TP or SL alerts for the configured duration.
- **Okay** → permanently dismiss further alerts on that side of the
  position.

For exit-by-date and expiry-T-1 alerts:

```text
Sold    Still holding
```

### 10.5 Position List Keyboard

Each `📂 Positions` card is rendered with live bid/ask and shows:

```text
🔒 Close    🗑 Delete
```

- **Close** opens the same Sold-price FSM as TP/SL "Sold".
- **Delete** wipes the position and its feedback rows without applying P/L.

### 10.6 Settings Inline Keyboard

```text
💰 Account Size
🎚 Risk Profile
🌎 Timezone
🏦 Broker
📜 Strategy Permission
🔢 Max Contracts
🔔 Alert Mute Duration
```

### 10.7 API Keys Inline Keyboard

```text
🔑 OpenRouter API Key
🔑 Alpaca Key + Secret      [🗑 Remove Alpaca]
🔑 Alpha Vantage API Key    [🗑 Remove Alpha Vantage]
```

The remove buttons appear only when the corresponding key is set.

### 10.8 Schedule Management

```text
Add    Edit    Delete    Pause all    Resume all
```

A run also remains triggerable from the main menu's "🚀 Run Scan Now"
button — that path uses the same workflow runner and lock as cron.

---

## 11. Onboarding Flow

```text
1.  /start                             → welcome
2.  Account size                       (numeric, $100–$100,000,000)
3.  Risk profile                       (Conservative / Balanced / Aggressive)
4.  Timezone                           (PT / MT / CT / ET / AT / NT)
5.  Broker                             (Wealthsimple / IBKR / Questrade / Other)
6.  Strategy permission                (long / short / long_and_short)
7.  OpenRouter API key                 (validated live)
8.  Alpaca API key                     (skippable)
9.  Alpaca API secret                  (validated live, skippable)
10. Alpha Vantage API key              (validated live, skippable)
11. Setup summary screen
12. Confirm                            → create user + default cron + main menu
```

The default cron `Monday 10:30` is created automatically in the user's
chosen timezone. The user can edit, add, or pause it later from
**🗓 Manage Schedule**.

---

## 12. Schedule and Cron Management

### 12.1 Default Cron

```text
Monday 10:30 AM in user.timezone_iana
```

### 12.2 Multiple Crons

Each cron row stores: `day_of_week`, `local_time` (HH:MM), `timezone_label`,
`timezone_iana`, `is_active`. Users may add as many as they like.

### 12.3 Actions

- Add / Edit / Delete a single row
- Pause all / Resume all (toggles `is_active` for every row)
- Manual run from the main menu

### 12.4 Storage and Delivery

- Rows live in PostgreSQL (`cron_jobs` table).
- APScheduler uses a SQLAlchemy job store outside test mode (test mode uses
  an in-memory job store).
- `SchedulerService.start()` on app boot syncs DB rows into runtime jobs.
- Updates to cron rows rewrite the in-memory APScheduler job.

### 12.5 Run Lock

Each user has a per-user Redis-backed run lock with TTL 900 s. While locked,
new runs return `RUN_ALREADY_ACTIVE_TEXT`:

```text
⏳ A scan is already running. I'll show the result here when it finishes.
```

---

## 13. Recommendation Output

### 13.1 Main Recommendation Template

```text
[optional warning_text — partial / failed screener]

Weekly Earnings Options Signal

Best setup: 🥇 TICKER

📈 Direction: Bullish | Bearish
📃 Contract: <Long/Short> <Call/Put>
🏷️ Strike: $XX.XX
💵 Suggested entry: up to $X.XX premium
📎 Suggested quantity: N contract(s) | Watchlist only
🗓️ Expiry: YYYY-MM-DD

🟢 Target sell price: $X.XX
🛑 Stop loss: $X.XX
🎯 Stock target: $XX.XX
🗓️ Exit by: YYYY-MM-DD

Estimated max loss: <text>
Account risk: NN.NN%
Earnings date: YYYY-MM-DD
Confidence: NN/100
Risk level: Moderate | High

✅ Action:
Manually review the contract in your broker before buying.
```

For watchlist-only setups, the action line becomes:

```text
⚠️ Action:
Keep this on the watchlist and only size it if the setup improves.
```

The setup label becomes "2nd best setup" / "3rd best setup" / "Alternative
setup #N" when surfaced via the Alternatives chain.

### 13.2 No-Trade Template

```text
[optional warning_text]
📊 Scan complete.

No trade looks strong enough this time.
<reason>

Watchlist: TICKER1, TICKER2, …
```

### 13.3 Short Option Output Note

Short-option recommendations display:

- `Short Put` or `Short Call` in the contract field
- `Broker/margin dependent` margin text
- `Undefined for naked short call` max-loss text for naked calls
- Risk level forced to `High`

---

## 14. Candidate Selection Logic

### 14.1 Candidate Universe

Strategy A returns up to 5 rows, Strategy B returns up to 5 rows. Both run
concurrently, then merge and dedupe by ticker (Strategy A wins ties),
yielding up to 10 candidates.

### 14.2 Candidate Validation (Strategy A only)

1. Take the top Finviz rows.
2. Look up each ticker in yfinance + Finnhub for earnings-date validation.
3. Reconcile conflicts via `CandidateReconciler`.
4. If a Finviz row's earnings date cannot be backed up, allow it through
   with `earnings_date_verified = False` and a downgraded confidence note.
5. Backfill missing rows from backup sources (yfinance, Finnhub) so the
   batch is at least the requested size when possible.

### 14.3 Candidate Validation (Strategy B)

Strategy B candidates are passed through unmodified — they have no earnings
date and no backup-source filling.

### 14.4 Hard Exclusions

A candidate is dropped before scoring if:

- ticker cannot be reconciled
- Strategy A row has no supportable next-week earnings date
- option chain is unavailable after both Alpaca and yfinance attempts
- current price cannot be determined

The scoring engine prefers a confidence downgrade over silent loss for any
non-critical missing field.

---

## 15. Scoring and Recommendation Engine

### 15.1 Candidate Inputs

Per candidate, the engine receives:

- `CandidateRecord` (from screener)
- `MarketSnapshot` (yfinance + indicators + relative strength)
- `NewsBundle` and `NewsBrief`
- Expanded option chain
- `UserContext` (account, risk, permission, max contracts, OpenRouter
  validity)

### 15.2 Direction Classification

Deterministic, not LLM-driven:

- `bullish` if bias ≥ 0.12
- `bearish` if bias ≤ −0.12
- `neutral` otherwise
- `avoid` if price missing or data confidence < 40

Direction-score factors include: trend alignment, relative strength, volume
confirmation, news/catalyst quality, earnings expectation context, market
and sector environment, price structure, and data confidence.

### 15.3 Contract Opportunity Score

Per contract, the engine evaluates:

- breakeven feasibility
- liquidity (volume, open interest, spread)
- expiry fit
- strike / moneyness
- IV setup (longs prefer low IV, shorts prefer rich IV)
- premium / risk fit
- direction compatibility

Hard vetoes zero out the contract score:

- unverified earnings date (Strategy A only)
- missing current price
- empty option chain
- expiry outside the valid earnings window
- missing long ask or short bid
- unusable quote
- zero open interest and zero volume
- spread > 35%
- stale or non-tradable contract
- user sizing yields 0 contracts
- user permission disables the position side

Soft penalties (do not zero the score):

- mixed news
- weak sector alignment
- light same-day option volume
- moderate spreads (15–25%)
- elevated IV for longs / weak IV for shorts
- valid but less-ideal expiry
- earnings-history vs. implied-move mismatch

### 15.4 Final Score

```text
final_score = 0.45 × direction_score + 0.55 × contract_score
```

### 15.5 Recommendation Thresholds

| Condition | Action |
|---|---|
| No viable contract or critical blockers | `no_trade` |
| Confidence < 40 | `no_trade` |
| Confidence 40–54 and final ≥ 60 | `watchlist` |
| Final 60–67 | `watchlist` |
| Final ≥ 68 with no blockers | `recommend` |

### 15.6 Strategy Selection Map

| Direction | Allowed Strategies |
|---|---|
| Bullish | `long_call`, `short_put` |
| Bearish | `long_put`, `short_call` |
| Neutral / Avoid | none |

The selector tilts toward the short-premium leg when median IV ≥ 0.60 and
direction score < 80, otherwise it prefers the long leg. Permissions are
applied first.

---

## 16. Expiry and Strike Selection

### 16.1 Valid Expiry Window

- Not before earnings date.
- Not more than 30 calendar days after earnings.
- Same-day expiry is only valid when `earnings_timing == "BMO"`.
- Even for BMO, same-day long expiries receive a soft penalty.

### 16.2 Expiry Preference

- Long strategies score highest in the 3–21 day post-earnings window.
- Short strategies score highest in the 0–14 day post-earnings window.

### 16.3 Strike Sampling

The strike scorer does not score the entire chain. It first picks a small,
representative set per expiry — near-ATM, slight ITM, slight OTM, best
breakeven, best liquidity for longs; slight OTM, moderate OTM, strongest
buffer, best liquidity for shorts — deduplicates them, and scores the
focused set.

---

## 17. IV, Expected Move, and Exit Targets

### 17.1 Required Per-Contract Calculations

Premium, midpoint, breakeven price, breakeven move %, target stock price,
target option price, stop-loss option price, planned holding days, exit-by
date, spread %, premium collected (shorts), and contract capacity.

### 17.2 Breakeven Math

```text
Long Call  breakeven = strike + premium
Long Put   breakeven = strike − premium
Short Put  buffer    = premium below strike
Short Call buffer    = premium above strike
```

### 17.3 IV Interpretation

- Longs prefer lower IV.
- Shorts prefer richer IV.
- Missing IV is allowed but lowers confidence rather than blocking the
  trade.

### 17.4 Long-Option Exit Target

Greek-based formula when `delta`, `gamma`, `theta`, `vega`, IV, and a
quote (bid/ask/mid) are all available:

```text
stock_move          = target_stock_price − current_stock_price
target_option_price = current_mid
                    + delta · stock_move
                    + 0.5 · gamma · stock_move²
                    + theta · planned_holding_days
                    + vega  · expected_iv_change
```

Signed delta is used (puts contribute positively when the target is below
the current price).

### 17.5 Fallback Order

```text
If full Greeks + quote available           → target_method = "full_greeks"
Else if delta + quote available            → target_method = "delta_fallback"
Else                                       → target_method = "intrinsic_fallback"
```

For earnings trades, IV crush is modeled through `vega · expected_iv_change`
when both are available; otherwise a conservative haircut is applied to
extrinsic value rather than fabricating precision.

### 17.6 Required Long-Option Output

Every long-option recommendation stores:

- `target_option_price`
- `target_stock_price`
- `target_gain_percent`
- `stop_loss_option_price`
- `exit_by_date`
- `expected_holding_days`
- `target_method`

---

## 18. Liquidity and Spread Parameters

### 18.1 Hard Rejects

- Zero open interest **and** zero same-day volume.
- Unusable quote (no bid or no ask).
- Spread > 35% with no cheap-contract exception.
- Stale or non-tradable contract.

### 18.2 Liquidity Scoring Bias

| Signal | Strong |
|---|---|
| Open interest | ≥ 100 |
| Volume | ≥ 25 |
| Spread | ≤ 15% |
| Spread (usable) | ≤ 25% |

### 18.3 Cheap-Contract Exception

Cheap contracts can survive a wide percentage spread when the absolute
spread is reasonable:

| Mid premium | Preferred absolute spread |
|---|---|
| < $0.50 | $0.10 |
| ≤ $2.00 | $0.25 |
| > $2.00 | $0.50 |

### 18.4 Spread Penalties

- > 15%: moderate penalty
- > 25%: strong penalty
- > 35%: hard veto

### 18.5 Watchlist Preference

When a candidate is interesting but not strong enough for a full
recommendation, the engine prefers `watchlist` over silent rejection.

### 18.6 Option Chain Retrieval Order

1. Alpaca by ticker variants when credentials exist
2. yfinance by ticker variants
3. In-memory per-day yfinance chain cache

---

## 19. Recommendation Engine

### 19.1 Per-Candidate Output

Each `CandidateEvaluation` carries:

- direction result
- confidence result
- considered contracts (with vetoes, penalties, exit target)
- chosen best contract (or none)
- final candidate score
- candidate action (`recommend` / `watchlist` / `no_trade`)

### 19.2 Final Cross-Candidate Selection

1. Sort all candidates by final score → confidence → direction score.
2. Take the top 4 finalists (`DECISION_FINALIST_LIMIT`).
3. Build a structured `DecisionInput` payload.
4. Call `LLMRouter.decide()` (Claude Opus 4.7 Thinking).
5. Validate the response against the actual candidate / contract IDs that
   were submitted.
6. If the LLM call fails transiently → fall back to heuristic top-of-list
   selection.
7. If the LLM call fails for authentication → return blocked no-trade.

### 19.3 Alternatives Chain

If the user taps `📈 Alternatives`, the
`AlternativeRecommendationService` walks the run's other viable candidates,
persists each new recommendation row with `parent_recommendation_id`
pointing at the prior one, and renders it with the appropriate "2nd best /
3rd best / Alternative #N" label.

### 19.4 No-Trade Persistence Rule

When the final action is `no_trade`:

- No `recommendations` row is created.
- `workflow_runs.status` becomes `no_trade`.
- Candidate cards and contract logs are still persisted.
- The user receives the no-trade message with watchlist tickers and the
  reasoning summary.

---

## 20. Position Tracking

### 20.1 Lifecycle

```text
Recommendation delivered
   ↓
User taps "✅ I bought it"
   ↓
Capture fill price + quantity
   ↓
Insert open_positions row (status = "active")
   ↓
PositionMonitor polls every 2 minutes during U.S. market hours
   ↓
Alerts fire on TP / SL / exit-by / expiry-1-day events
   ↓
User taps "Sold" → capture sell price → compute P/L → apply to user.account_size
   ↓
Position status = "closed_sold" (or "closed_expired" on expiry)
```

### 20.2 Polling Schedule

- APScheduler cron: `mon-fri 09–16 */2` minutes, timezone
  `America/New_York`.
- Job ID: `poll_open_positions`.

### 20.3 Quote Fetching

`PositionMonitor` groups all active positions by ticker, then per ticker:

1. Build OCC option symbols (e.g. `AAPL241115C00150000`) for every position.
2. If the user has Alpaca credentials, batch-fetch the chain in one call
   constrained to those OCC symbols.
3. Otherwise fall back to yfinance.
4. Extract the best premium from each contract using
   `mid → last_trade_price → ask → bid` priority.

### 20.4 Alert Conditions

For each polled position:

| Alert | Trigger |
|---|---|
| `target_hit` | `current_premium ≥ recommendation.target_option_price` (first crossing uses `>=`; later crossings require crossing from below) |
| `stop_hit` | `current_premium ≤ recommendation.stop_loss_option_price` (first crossing uses `<=`; later crossings require crossing from above) |
| `exit_by_date` | `today ≥ recommendation.exit_by_date` (one-shot) |
| `expiry_t_minus_1` | `(expiry − today).days ≤ 1` (one-shot) |
| Auto-expire | `today > recommendation.expiry` → status = `closed_expired`, P/L applied automatically with `close_price = 0` |

Crossings increment per-side counters (`target_alert_count`,
`stop_alert_count`) so repeated noise around the level does not spam the
user.

### 20.5 Mute and Dismiss

- "Mute" sets `target_muted_until` or `stop_muted_until` based on the
  user's `alert_mute_duration` setting.
- "Okay" sets `target_dismissed` or `stop_dismissed` permanently.
- A muted level resumes alerting once the mute window passes.

### 20.6 Account Size Auto-Update

When a position closes (either via "Sold" or auto-expire), the system:

1. Computes realized P/L (`(close − entry) × 100 × qty` for longs;
   `(entry − close) × 100 × qty` for shorts).
2. Adds the P/L to `user.account_size`.
3. Sets `pnl_applied = true` (idempotent — repeated calls are no-ops).
4. Logs a `feedback_events` row with `user_action = "closed"` and the
   captured exit price and P/L.

### 20.7 Manual Modification and Deletion

- Editing a closed position's exit price reverses the previous P/L and
  re-applies the new P/L (`reapply_pnl_after_modification`).
- Deleting a position removes it without applying P/L; any feedback rows
  for the same recommendation/user are cleaned up.

---

## 21. Logging System

### 21.1 Storage Layers

Per workflow run, the system persists to `workflow_runs`:

- `run_summary_json`
- `candidate_cards_json`
- `option_contracts_json`
- `recommendation_card_json`
- `telegram_message_text`

Outside test mode, the same artifacts are also archived as files under:

```text
var/runs/<run_id>/
```

### 21.2 Recommendation Card Fields

Stored in `recommendations`: card / user / run IDs, ticker, company, strategy,
option type, position side, strike, expiry, suggested entry, target stock /
option / gain %, stop-loss option price, exit-by date, expected holding days,
target method, suggested quantity, max-loss text, account-risk %, confidence,
risk level, reasoning summary, key evidence JSON, key concerns JSON,
Telegram message ID, parent recommendation ID, created-at.

### 21.3 Per-Candidate Logs

Stored in `candidates`: ticker, company, market cap, earnings date, earnings
timing, current price, direction classification, candidate direction score,
best strategy, final opportunity score, data confidence score,
selected_for_final, strategy_source.

### 21.4 Per-Contract Logs

Stored in `option_contracts`: ticker, option type, position side, strike,
expiry, bid, ask, mid, volume, open interest, IV, delta, gamma, theta, vega,
breakeven, target stock / option / gain %, stop-loss option price, exit-by
date, expected holding days, target method, spread %, liquidity score,
contract opportunity score, hard-filter pass/fail, rejection reason.

### 21.5 Feedback Events

Stored in `feedback_events`: recommendation ID, user ID, user action
(`bought` / `skipped` / `closed`), entry price, exit price, P/L, optional
note. These rows are the foundation of the future feedback agent.

---

## 22. Database Schema

### 22.1 `users`

`id`, `telegram_chat_id`, `account_size`, `risk_profile`,
`custom_risk_percent`, `broker`, `timezone_label`, `timezone_iana`,
`strategy_permission`, `max_contracts`, `max_option_premium`,
`alert_mute_duration`, `openrouter_api_key_encrypted`,
`alpaca_api_key_encrypted`, `alpaca_api_secret_encrypted`,
`alpha_vantage_api_key_encrypted`, `is_active`, `created_at`, `updated_at`.

### 22.2 `cron_jobs`

`id`, `user_id`, `day_of_week`, `local_time`, `timezone_label`,
`timezone_iana`, `is_active`, `created_at`, `updated_at`.

### 22.3 `workflow_runs`

`id`, `user_id`, `trigger_type` (cron/manual), `status`
(running/success/failed/no_trade), `started_at`, `finished_at`,
`screener_status` (success/partial/failed), `selected_candidate_count`,
`final_recommendation_id`, `error_message`, `run_summary_json`,
`candidate_cards_json`, `option_contracts_json`, `recommendation_card_json`,
`telegram_message_text`.

### 22.4 `candidates`

`id`, `run_id`, `ticker`, `company_name`, `market_cap`, `earnings_date`,
`earnings_timing`, `current_price`, `direction_classification`,
`candidate_direction_score`, `best_strategy`, `final_opportunity_score`,
`data_confidence_score`, `selected_for_final`, `strategy_source`,
`created_at`.

### 22.5 `option_contracts`

`id`, `candidate_id`, `ticker`, `option_type`, `position_side`, `strike`,
`expiry`, `bid`, `ask`, `mid`, `volume`, `open_interest`,
`implied_volatility`, `delta`, `gamma`, `theta`, `vega`, `breakeven`,
`target_stock_price`, `target_option_price`, `target_gain_percent`,
`stop_loss_option_price`, `exit_by_date`, `expected_holding_days`,
`target_method`, `spread_percent`, `liquidity_score`,
`contract_opportunity_score`, `passed_hard_filters`, `rejection_reason`,
`created_at`.

### 22.6 `recommendations`

`id`, `user_id`, `run_id`, `parent_recommendation_id`, `ticker`,
`company_name`, `strategy`, `option_type`, `position_side`, `strike`,
`expiry`, `suggested_entry`, `target_stock_price`, `target_option_price`,
`target_gain_percent`, `stop_loss_option_price`, `exit_by_date`,
`expected_holding_days`, `target_method`, `suggested_quantity`,
`estimated_max_loss`, `account_risk_percent`, `confidence_score`,
`risk_level`, `reasoning_summary`, `key_evidence_json`,
`key_concerns_json`, `telegram_message_id`, `created_at`.

### 22.7 `open_positions`

`id`, `recommendation_id`, `user_id`, `entry_price`, `entry_quantity`,
`entry_at`, `status` (`active` / `closed_sold` / `closed_expired`),
`close_price`, `close_at`, `last_premium`, `last_polled_at`,
`last_data_source`, `alerts_sent` (JSONB list), `pnl_applied`,
`target_alert_count`, `stop_alert_count`, `target_dismissed`,
`stop_dismissed`, `target_muted_until`, `stop_muted_until`, `created_at`.

### 22.8 `feedback_events`

`id`, `recommendation_id`, `user_id`, `user_action`
(`bought`/`skipped`/`still_holding`/`closed`), `entry_price`, `exit_price`,
`pnl`, `note`, `created_at`.

---

## 23. Backend Architecture

### 23.1 Stack

| Layer | Choice |
|---|---|
| Language | Python 3.12 |
| App framework | FastAPI |
| Telegram bot | aiogram 3 |
| Scheduler | APScheduler (SQLAlchemy job store outside tests) |
| Database | PostgreSQL 16 |
| Cache + locks + FSM storage | Redis 7 |
| ORM | SQLAlchemy async + Alembic migrations |
| Browser automation | Playwright (headless Chromium) |
| Screener | Finviz |
| Market data | yfinance (+ optional Alpha Vantage) |
| Options data | Alpaca primary, yfinance fallback |
| LLM routing | OpenRouter |
| Encryption | Fernet (encrypted API key columns) |
| Container runtime | Docker Compose (Postgres, Redis, app, optional playwright) |

### 23.2 Service Components

| Component | Module |
|---|---|
| Telegram bot | `app/telegram/*` (handlers, keyboards, templates, FSM) |
| Scheduler service | `app/scheduler/scheduler.py` |
| Workflow runner + run lock | `app/scheduler/jobs.py`, `app/services/run_lock.py` |
| Pipeline orchestrator | `app/pipeline/orchestrator.py` |
| Pipeline steps | `app/pipeline/steps/*` (candidates, market_data, news, options, scoring, sizing, decide) |
| Multi-strategy candidate service | `app/services/multi_strategy_service.py` |
| Catalyst-confluence (Strategy A) | `app/services/candidate_service.py` |
| Coiled-setup (Strategy B) | `app/services/coiled_setup_service.py` |
| Finviz browser + cache + runner | `app/services/finviz/*` |
| Earnings backups | `app/services/earnings_calendar/*` (Finnhub, yfinance, reconciler) |
| Market data service | `app/services/market_data/*` |
| News service | `app/services/news/*` |
| Options service | `app/services/options/*` (Alpaca, yfinance, OCC symbol builder) |
| Scoring engine | `app/scoring/*` (direction, contract, expiry, strike, vetoes, penalties, exit target) |
| Sizing service | `app/services/sizing.py` |
| LLM router | `app/llm/router.py` |
| Logging service | `app/services/logging_service.py` |
| Position monitor | `app/services/positions/*` (monitor, account, quotes) |
| Alternative recommendation service | `app/services/alternative_recommendation_service.py` |
| API key validators | `app/services/api_key_validators.py` |
| User service + onboarding payload | `app/services/user_service.py` |

---

## 24. Error Handling

### 24.1 Finviz Failures

1. Per-variant failures are logged and tolerated when at least one variant
   succeeds.
2. If Strategy A fails entirely but Strategy B succeeds → continue with
   `screener_status = "partial"`, surface a warning.
3. If Strategy B fails entirely but Strategy A succeeds → same, with the
   complementary warning.
4. If both fail → fall back to backup earnings calendars (Strategy A path);
   `screener_status = "failed"`.
5. The Telegram message always includes the appropriate warning when a
   degradation occurred.

### 24.2 Option Chain Failures

1. Try Alpaca by ticker variants when credentials exist.
2. Fall back to yfinance by ticker variants.
3. If both return nothing usable → keep the candidate analyzable but emit
   no contract; the engine downgrades to `watchlist` or `no_trade`.

### 24.3 Market Data Failures

`MarketDataFetchStep` failures fall back to a `_fallback_market_snapshot`
constructed from the candidate row, with `confidence_adjustment = -20` and a
`pipeline / market_data / warning` confidence note. The candidate stays in
the run.

### 24.4 News Failures

- `LLMAuthenticationError` → fallback news bundle, news confidence 25,
  user's effective `has_valid_openrouter_api_key` flipped off so the rest
  of the pipeline knows the key is bad.
- Other exceptions → fallback news bundle with the error string captured
  in `key_uncertainty`.

### 24.5 Sizing Failures

`SizingError` or `SizingPermissionError` → fallback sizing result with
`quantity = 0`, `watch_only = True`, and broker/margin-dependent text for
shorts.

### 24.6 LLM Decision Failures

- Transient (network / 5xx / non-JSON) → heuristic top-of-list selection.
- Authentication → blocked no-trade.
- Schema validation → blocked no-trade with an error log entry.

### 24.7 Position Monitor Failures

Alpaca and yfinance failures inside the monitor are logged at `warning`
level and swallowed. A failed poll cycle leaves the next cycle to try
again.

### 24.8 Critical Blockers

The following cause `no_trade` regardless of numeric scores:

- missing ticker
- unverified earnings date for a Strategy A row
- missing current price
- missing expiry / strike
- unusable quote
- invalid user account size
- invalid or missing OpenRouter key for the heavy decision route

---

## 25. Data Confidence System

### 25.1 Component Weights

| Component | Weight |
|---|---:|
| Earnings-date confidence | 25% |
| Options-data confidence | 22% |
| Market-data confidence | 20% |
| Identity confidence | 13% |
| Cross-source agreement | 10% |
| Calculation integrity | 7% |
| News coverage | 3% |

### 25.2 Score Bands

| Score | Label | Action |
|---|---|---|
| 85–100 | strong | recommendation allowed |
| 70–84 | good | recommendation allowed |
| 55–69 | partial | recommendation allowed only if final score is strong |
| 40–54 | weak | watchlist or no trade |
| < 40 | critical | no trade |

### 25.3 Critical Field Override

Even if the numeric confidence is above 40, the system blocks the
recommendation when any critical field is missing:

- ticker
- `strategy_source`
- verified earnings date (Strategy A only)
- current price
- contract type
- position side
- strike
- expiry
- usable bid/ask or mid
- account size
- risk profile
- valid OpenRouter API key

### 25.4 Missing Greeks

Missing Greeks do not block the trade. The exit-target service falls back
through `delta_fallback` → `intrinsic_fallback`, and the contract scorer
substitutes moneyness, premium, spread quality, and liquidity for the
missing Greeks while applying a confidence penalty.

### 25.5 Source Conflicts

Cross-source conflicts:

- create confidence notes
- lower the confidence adjustment
- become hard blockers only when they affect critical fields

### 25.6 Telegram Surface

The main recommendation message stays readable; confidence detail belongs
in logs and the Risk / Sizing breakdown unless a data issue materially
affects the decision.

---

## 26. Acceptance Criteria

### 26.1 Workflow

- The scheduled scan fires at the correct cron time in the user's timezone.
- A manual scan can be triggered from Telegram and is covered by the same
  run lock.
- Both Finviz strategies execute, results are merged and deduped.
- `screener_status` is recorded for every run.
- Up to 10 candidates flow through the scoring pipeline.
- Option chains are retrieved (Alpaca → yfinance), or the failure is
  logged and the candidate is downgraded.
- One recommendation, one watchlist setup, or one no-trade result is
  produced.
- The Telegram message is delivered with the appropriate warning text
  when applicable.
- The full evidence trail is persisted to PostgreSQL and to
  `var/runs/<run_id>/`.

### 26.2 Recommendation

A recommendation includes ticker, direction, contract, strike, expiry,
suggested entry, target option price, stock target, stop-loss option price,
exit-by date, suggested quantity (or watchlist marker), estimated max loss,
account risk %, earnings date, confidence, risk level, and reasoning.

### 26.3 Schedule

The user can add, edit, delete, pause, and resume schedules; schedules
display in local time; manual runs honor the run lock.

### 26.4 Logging

Every completed run stores: run summary, candidate cards, option contract
logs, recommendation card (or no-trade context), and the Telegram message
text.

### 26.5 Position Tracking

- The user can register a fill via "I bought it".
- The polling job runs every 2 minutes during U.S. market hours.
- TP / SL / exit-by / expiry alerts arrive with the correct keyboard.
- "Sold" closes the position, captures price, computes P/L, applies P/L
  to `user.account_size`, and logs a `feedback_events` row.
- "Mute" / "Okay" suppress further alerts according to the user's mute
  duration setting.
- Auto-expire converts `active` → `closed_expired` and applies P/L with
  `close_price = 0`.

---

## 27. Definition of Done

The system is considered done for V2 when:

- A user can onboard end-to-end from Telegram (12 steps) and land on the
  persistent main menu.
- Account size, risk, broker, timezone, strategy permission, max contracts,
  alert mute duration, OpenRouter key, Alpaca key+secret, and Alpha Vantage
  key are all editable.
- The user can manage cron jobs (add / edit / delete / pause / resume) and
  trigger manual runs.
- The default Monday 10:30 AM schedule fires in the user's timezone.
- The agent runs Strategy A and Strategy B concurrently, merges them, and
  produces up to 10 candidates.
- The agent retrieves option chains from Alpaca first (when configured)
  and yfinance otherwise.
- The lightweight model summarizes news; the heavy model picks the final
  setup; the two routes are hard-separated.
- Long calls, long puts, short puts, and short calls are all supported.
- The agent sends one main recommendation, one no-trade message, or a
  watchlist-only setup, with the appropriate inline keyboard.
- "I bought it" opens a position; the position monitor sends alerts on
  TP / SL / exit-by / expiry; "Sold" updates `account_size` with realized
  P/L; "Mute" / "Okay" honor the alert mute duration; "Delete" cleans up
  feedback rows.
- "Alternatives" walks the parent recommendation chain and persists each
  alternative recommendation row.
- Every run stores a complete recommendation card, candidate logs, contract
  logs, and Telegram message text in PostgreSQL and on disk.

---

## 28. Out of Scope (V2)

- Broker execution / auto-trading
- Public web dashboard
- Multi-leg option strategies
- Subscription / payment flow
- Automatic strategy self-modification

---

## 29. Future Enhancements

- Post-trade feedback agent that compares realized outcomes against the
  original thesis using the existing `feedback_events` table.
- Performance dashboard surfacing realized P/L, win rate, and alert
  hit-rate per strategy_source.
- Multi-leg support (verticals, calendars, diagonals, IC/butterflies).
- Stronger options data providers and intraday option-flow context.
- Historical replay / backtest tools that reuse the scoring engine.
- Configurable scoring weights per user.
