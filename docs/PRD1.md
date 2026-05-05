# PRD: Setup-Driven Options Recommendation Agent

**Version:** V1.2  
**Update:** Replaced single TradingView screener with two complementary Finviz strategies (Strategy A — Catalyst Confluence, Strategy B — Coiled Setup). Each strategy returns up to 5 candidates; both feed the existing scoring system. `strategy_source` field added to candidates for V2 feedback attribution. Redis cache added (600 s TTL). Alpaca Options Snapshots API remains primary option-chain source; Yahoo Finance / yfinance remains fallback; Alpha Vantage remains optional supporting data.

## 1. Product Summary

The Setup-Driven Options Recommendation Agent is a Telegram-based agent that runs two complementary Finviz screening strategies, merges up to 10 candidates, scores them with the existing pipeline, and sends a friendly Telegram recommendation to the user. Strategy A ("Catalyst Confluence") targets stocks with earnings catalysts and confirmed multi-timeframe uptrends. Strategy B ("Coiled Setup") targets stocks in established uptrends with compressed volatility — no earnings dependency required. Together they surface tradeable candidates even in slow earnings weeks.

The current architecture is built around:

**Every Monday at 10:30 AM Montreal, Quebec local time**∆

The system does not place trades. It produces structured recommendations and
logged evidence so the user can review the setup manually in their broker.

---

## 2. Core Product Objective

The product should answer one practical question:

> “Across catalyst-driven and structure-driven setups, which option contract has the best opportunity based on trend, earnings setup, market context, option chain quality, pricing, and expected move?”

The output should give the user:

- the chosen ticker
- direction
- strategy and contract
- strike and expiry
- suggested entry
- suggested quantity or watchlist-only status
- estimated max loss or broker-margin warning
- confidence score
- concise reasoning
- key evidence and concerns

---

## 3. Core Workflow

### 3.1 Weekly Automated Workflow

Default run:

```text
Monday 10:30 AM America/Toronto
```

Current runtime flow:

```text
Cron Trigger
   ↓
Run Strategy A (Finviz Catalyst Confluence — earningsdate_thisweek + earningsdate_nextweek, dedupe)
   ↓
Run Strategy B (Finviz Coiled Setup — channelup2 + triangleascending, dedupe)
   ↓  ↓ (both run concurrently)
Merge results, dedupe by ticker (Strategy A wins ties)
   ↓
Up to 10 candidates → existing scoring pipeline
   ↓
Analyze each stock direction
   ↓
Analyze long and short option opportunities
   ↓
Select one best contract or return “No trade”
   ↓
Send recommendation through Telegram
   ↓
Store recommendation card and evidence logs (with strategy_source per candidate)
```

### 3.2 Manual Workflow

The current manual entry point is the Telegram main-menu button:

```text
🚀 Run Scan Now
```

Manual runs use the same pipeline as scheduled runs. The current architecture
does not yet include a separate "analyze specific ticker" path.

---

## 4. Main Requirements

### 4.1 The Agent Must

1. Use Finviz Screener through browser automation for both Strategy A and Strategy B.
2. Run Strategy A twice (earningsdate_thisweek, earningsdate_nextweek) and dedupe results.
3. Run Strategy B twice (ta_pattern_channelup2, ta_pattern_triangleascending) and dedupe results.
4. Merge both strategy results, dedupe by ticker (Strategy A wins ticker ties), yielding up to 10 candidates.
5. Gather additional market, option, chart, earnings, and news data for each candidate.
6. Analyze bullish and bearish scenarios.
7. Evaluate both long and short options.
8. Choose only one direction per stock: bullish, bearish, neutral, or avoid.
9. Never recommend both a call and a put for the same stock in the same run.
10. Select the best overall opportunity across all merged candidates.
11. Send a clear Telegram recommendation.
12. Store a compact evidence-based log card for each recommendation, including strategy_source per candidate.
13. Allow user-configurable account size, risk profile, timezone, API keys, and cron schedules.

### 4.2 The Agent Must Not

1. Execute trades.
2. Use the retired TradingView provider or phase-4 login flow.
3. Depend on persistent browser auth for the Finviz scan.
4. Use hidden or private screener APIs.
5. Invent missing prices, contracts, earnings dates, or LLM outputs.
6. Start a second run for the same user while one is already active.

---

## 5. Finviz Dual-Strategy Screener Integration

### 5.1 Purpose

Finviz Screener is used as the primary candidate source via two complementary strategies. Finviz's URL-parameter system allows full filter configuration without clicking through UI — the agent constructs the URL directly and calls `page.goto(url)`, then parses the server-rendered HTML table. No hidden APIs are used; all filters are free-tier accessible.

**Strategy A — Catalyst Confluence** targets stocks with an earnings catalyst inside the option window, confirmed multi-timeframe uptrend, EPS/revenue beat history, and institutional positioning. Sort: Relative Volume descending.

**Strategy B — Coiled Setup** targets stocks in established long-term uptrends currently consolidating in bullish chart patterns with compressed volatility. No earnings dependency. Sort: Performance (Half Year) descending.

### 5.2 Strategy A URL Template

Run twice per scan — once with `earningsdate_thisweek`, once with `earningsdate_nextweek` — and dedupe results. Finviz's earnings filter is single-value only.

```text
https://finviz.com/screener.ashx?v=111&f=cap_midover,
earningsdate_thisweek,exch_nasd,exch_nyse,fa_epsqoq_pos,
fa_epssurprise_pos,fa_revenuesurprise_pos,fa_salesqoq_pos,
geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,
sh_relvol_o1.5,an_recom_buybetter,targetprice_above,
ta_sma20_pa,ta_sma50_pa,ta_sma200_pa,
ta_perf_qup,ta_rsi_50to70&ft=4&o=-relativevolume
```

### 5.3 Strategy B URL Template

Run twice per scan — once with `ta_pattern_channelup2`, once with `ta_pattern_triangleascending` — and dedupe results.

```text
https://finviz.com/screener.ashx?v=111&f=cap_midover,exch_nasd,exch_nyse,
geo_usa,sh_avgvol_o2000,sh_opt_option,sh_price_o20,sh_short_u20,
sh_insidertrans_pos,ta_sma200_pa,ta_sma50_pa,ta_highlow52w_b10h,
ta_perf_yup,ta_perf2_hup,ta_rsi_40to60,ta_volatility_wo4,
ta_pattern_channelup2,ta_beta_o1,sh_relvol_o1
&ft=4&o=-perfhalf
```

### 5.4 Required Extracted Fields

For each row returned by either strategy, extract:

| Field | Required | Strategy |
|---|---:|---|
| Ticker | Yes | Both |
| Company name | Yes | Both |
| Market cap | Yes | Both |
| Upcoming earnings date | Yes (Strategy A only) | A |
| Current price | Preferred | Both |
| EPS Surprise | Preferred | A |
| Revenue Surprise | Preferred | A |
| Analyst Recom. | Preferred | A |
| Target Price | Preferred | A |
| RSI (14) | Preferred | Both |
| Pattern | Preferred | B |
| Volatility (Week) | Preferred | B |
| Float Short | Preferred | B |
| Insider Transactions | Preferred | B |
| Relative Volume | Preferred | Both |
| Sector/industry | Preferred | Both |

If Finviz does not expose all preferred fields, the agent should fill missing fields from backup data sources. Strategy B candidates do not have an earnings date from Finviz — leave `earnings_date` null unless confirmed by a backup source.

### 5.5 Allowed Automation Method

The agent uses:

- Playwright `page.goto(url)` — Finviz URL contains all filter parameters
- HTML table parsing from accessibility tree or raw HTML
- Screenshot + vision model extraction as fallback
- Redis cache (600 s TTL) to avoid hammering Finviz between strategy runs

The system must not use undocumented Finviz APIs.

### 5.6 Screener Status Reporting

After each scan the system records a `screener_status` value:

| Value | Meaning |
|---|---|
| `success` | Both Strategy A and Strategy B returned candidates |
| `partial` | Only one strategy returned candidates |
| `failed` | Both strategies returned no candidates (Finnhub/yfinance backup used) |

The `partial` status triggers a warning text in the Telegram message explaining which strategy was unavailable.

---

## 6. Data Sources

### 6.1 Primary Source Matrix

| Data Need | Primary Source | Backup / Supporting Source |
|---|---|---|
| Screener candidates (up to 10) | Finviz dual-strategy browser automation (Strategy A + B) | Finnhub / yfinance earnings calendar |
| Earnings date verification | Finviz (Strategy A) + backup API | Yahoo Finance / Finnhub / Alpha Vantage |
| Market cap | Finviz | Yahoo Finance / yfinance |
| Historical OHLCV | Yahoo Finance / yfinance | Alpha Vantage |
| Option chains | Alpaca Options Snapshots API | Yahoo Finance / yfinance |
| Option Greeks | Alpaca Options Snapshots API | calculated/estimated when unavailable |
| Option bid/ask/quote data | Alpaca indicative options feed | Yahoo Finance / yfinance |
| News and catalysts | Web search | company investor relations pages |
| Market context | SPY, QQQ, VIX proxy | Yahoo Finance |
| Sector context | sector ETFs | Yahoo Finance |
| LLM reasoning | OpenRouter | user-provided OpenRouter API key |

### 6.2 Alpaca Options Data Role

Alpaca is the preferred options source when the user has provided both:

- Alpaca API key
- Alpaca API secret

The options service should use Alpaca first, then fall back to yfinance if:

- credentials are missing
- authentication fails
- Alpaca returns no usable chain
- ticker symbol normalization requires a backup lookup

### 6.3 yfinance and Alpha Vantage Role

yfinance is the primary market-data source in the implemented architecture.

Alpha Vantage is optional and currently used as:

- a supporting overview source
- a supporting price-history source when yfinance history is unavailable
- a conflict-detection source for price and market-cap checks

Alpha Vantage is not the primary option-chain provider.

### 6.4 News Data Role

The news pipeline is:

```text
Search results
   |
Article fetcher
   |
OpenRouter lightweight summary
   |
Coverage policy and confidence cap
```

If coverage is thin, the system should lower news confidence and note when IR
fallback results were required.

### 6.5 Fallback and Cache Rule

Current fallback order:

```text
Try primary source
   |
Try secondary source
   |
Use Redis cache when the service supports it
   |
If critical fields still fail, downgrade confidence or return No Trade
```

Current Redis-backed caches:

- market snapshots
- news bundles

---

## 7. Model Routing and API Key Requirements

### 7.1 User-Provided OpenRouter API Key

Each user must provide an OpenRouter API key.

The current system:

- validates the key during onboarding and edits
- stores the key encrypted
- uses it for lightweight news summarization
- uses it for the heavy final decision route

Without a valid OpenRouter key, the final recommendation path should not
produce a trade recommendation.

### 7.2 Heavy Reasoning Model

Default heavy model:

```text
anthropic/claude-opus-4.7
```

This route is used for the final structured decision step only. It receives a
fully prepared `DecisionInput` payload rather than raw market prompts.

Responsibilities:

- choose the final ticker and contract from pre-scored candidates
- return `recommend`, `watchlist`, or `no_trade`
- provide reasoning, evidence, concerns, and watchlist tickers
- comply with a strict JSON schema

If the heavy route is unavailable, the system falls back to a heuristic
decision. If authentication fails, the system returns a blocked no-trade result.

### 7.3 Lightweight Model

Default lightweight model:

```text
google/gemini-3.1-flash-lite-preview
```

Responsibilities in the current architecture:

- summarize fetched news articles
- produce lightweight structured synthesis tasks

### 7.4 Model Separation Rule

The router enforces a hard separation:

- `summarize()` uses the lightweight route
- `decide()` uses the heavy route

The heavy `decide()` call cannot be pointed at the lightweight model.

### 7.5 Model Input Discipline

The heavy decision step should consume structured candidate bundles that include:

- candidate identity
- earnings date and verification state
- market snapshot summary
- news brief
- considered contracts
- chosen per-candidate best contract
- confidence score and blockers
- sizing and risk context

---

## 8. User Settings

### 8.1 Current User Settings

| Setting | Status in Current UX | Required |
|---|---|---:|
| Telegram chat ID | automatic | Yes |
| Account size | editable | Yes |
| Risk profile | editable | Yes |
| Broker | editable | Yes |
| Timezone label + IANA timezone | editable | Yes |
| Strategy permission | editable | Yes |
| Max contracts | editable | Yes |
| OpenRouter API key | editable | Yes |
| Alpaca API key + secret | editable | Optional |
| Alpha Vantage API key | editable | Optional |
| Cron jobs | editable | Yes |

Persisted but not currently exposed in the Telegram UI:

- `custom_risk_percent`
- `max_option_premium`

### 8.2 Timezone Options

| Label | Stored IANA Timezone |
|---|---|
| PT | America/Vancouver |
| MT | America/Edmonton |
| CT | America/Winnipeg |
| ET | America/Toronto |
| AT | America/Halifax |
| NT | America/St_Johns |

### 8.3 Default User Settings

| Setting | Default |
|---|---|
| Timezone | ET / America/Toronto |
| Default cron job | Monday 10:30 |
| Risk profile | Balanced |
| Strategy permission | long_and_short |
| Max contracts | 3 |
| Main result threshold | Recommendation at final score 68+ with no blockers |

---

## 9. Risk Profile and Position Sizing

### 9.1 Risk Profile Defaults

| Risk Profile | Long Option Risk Budget |
|---|---:|
| Conservative | 1% |
| Balanced | 2% |
| Aggressive | 4% |

### 9.2 Long Options Sizing

Current long-option sizing:

```text
Trade budget = account size x risk percent
Max loss per contract = ask x 100
Suggested contracts = floor(trade budget / max loss per contract)
Suggested contracts are capped by max_contracts
```

If the result is zero, the setup becomes watchlist-only.

### 9.3 Short Options Sizing

Current short-option handling:

- `short_put`: approximate notional exposure = strike x 100
- `short_call`: max loss text = `Undefined for naked short call`
- both short strategies set `broker_verification_required = true`
- both short strategies use broker/margin-dependent messaging

### 9.4 Contract Quantity for Short Options

Current short-notional caps:

| Risk Profile | Max Short Notional Exposure |
|---|---:|
| Conservative | 10% of account size |
| Balanced | 20% of account size |
| Aggressive | 35% of account size |

Quantity is:

```text
floor(max_short_notional_exposure / (strike x 100))
```

The result is still capped by `max_contracts`.

---

## 10. Telegram Bot UX

### 10.1 General UX Rule

The bot should be button-first. Users should not have to memorize slash
commands for normal use.

### 10.2 Main Menu Buttons

Current main menu:

```text
🚀 Run Scan Now
📊 Last Recommendation
🗓 Manage Schedule
⚙️ Settings
🔑 API Keys
📘 Logs
❓ Help
```

### 10.3 Recommendation Message Buttons

Current inline actions:

```text
🔍 Why this?
⚖️ Risk / Sizing
📈 Alternatives
📘 Save Note
✅ I bought it
❌ I skipped it
```

### 10.4 Schedule Management Buttons

Current schedule actions:

```text
Add
Edit
Delete
Pause all
Resume all
```

### 10.5 Settings and API Key Buttons

Current settings actions:

```text
💰 Account Size
🎚 Risk Profile
🌎 Timezone
🏦 Broker
📜 Strategy Permission
🔢 Max Contracts
🔑 OpenRouter API Key
🔑 Alpaca Key + Secret
🔑 Alpha Vantage API Key
```

### 10.6 Telegram Tone

Messages should be:

- friendly
- concise
- clear
- cautious around risk

The current templates use short status messages before the final recommendation
or no-trade result.

---

## 11. Onboarding Flow

### 11.1 First-Time Setup

Current onboarding flow:

1. account size
2. risk profile
3. timezone
4. broker
5. strategy permission
6. OpenRouter key validation
7. Alpaca key
8. Alpaca secret validation or skip
9. Alpha Vantage key validation or skip
10. setup summary
11. confirm
12. create user + default cron job
13. show main menu

### 11.2 Main Menu After Setup

After setup the user lands on the persistent main menu described in Section
10.2.

---

## 12. Schedule and Cron Management

### 12.1 Default Cron Job

Current default cron:

```text
Monday 10:30 AM America/Toronto
```

### 12.2 Multiple Cron Jobs

Users can create multiple cron rows. Each row stores:

- weekday
- local time
- timezone label
- timezone IANA
- active flag

### 12.3 Cron Job Actions

Current actions:

- add
- edit
- delete
- pause all
- resume all
- run manually from the main menu

### 12.4 Cron Job Storage and Delivery

Current architecture:

- cron rows are stored in PostgreSQL
- APScheduler uses a SQLAlchemy job store outside test mode
- scheduler startup syncs database rows into runtime jobs
- user timezone updates rewrite stored cron timezone fields

### 12.5 Cron Conflict Handling

If a user already has a run in progress, the workflow runner should not start a
second run.

User-facing message:

```text
⏳ A scan is already running. I'll show the result here when it finishes.
```

The default lock TTL is 900 seconds.

---

## 13. Recommendation Output Format

### 13.1 Main Recommendation Template

Current template includes:

- warning text when the screener fell back
- setup label (`Best setup` or `Next best setup`)
- ticker
- direction
- contract label
- strike
- expiry
- suggested entry
- suggested quantity or watchlist-only status
- estimated max loss
- account risk
- earnings date
- confidence score
- risk level
- reasoning summary
- important warning
- action text

### 13.2 No-Trade Template

Current no-trade output includes:

- optional screener warning text
- scan-complete header
- explicit `No trade recommended`
- concise reason
- top watchlist tickers

### 13.3 Short Option Output Note

Short-option recommendations must clearly identify:

- `Short Put` or `Short Call`
- broker/margin dependency
- undefined naked-call risk when relevant

---

## 14. Candidate Selection Logic

### 14.1 Candidate Universe

The candidate universe starts from two concurrent Finviz screens.

**Strategy A — Catalyst Confluence** (run twice, dedupe):
- earningsdate_thisweek variant → up to 5 results
- earningsdate_nextweek variant → merged with above, dedupe by ticker

**Strategy B — Coiled Setup** (run twice, dedupe):
- ta_pattern_channelup2 variant → up to 5 results
- ta_pattern_triangleascending variant → merged with above, dedupe by ticker

After both strategies complete, the results are merged and deduped by ticker (Strategy A wins ticker ties). The pipeline receives up to 10 candidates.

### 14.2 Candidate Validation

Current candidate validation architecture:

1. try Finviz top five visible rows
2. validate each ticker with yfinance and Finnhub detail lookups
3. reconcile conflicts through `CandidateReconciler`
4. supplement missing valid rows from backup candidate lists

Important behavior:

- backup-only rows require a valid next-week earnings date
- Finviz-visible rows may remain eligible with downgraded earnings-date
  confidence when the row is visible but backup confirmation is incomplete

### 14.3 Exclusions

Hard exclusion cases include:

- ticker cannot be reconciled
- no next-week earnings date can be supported
- no usable option chain survives scoring
- current price is unavailable

The system should prefer confidence downgrade over unnecessary candidate loss
when non-critical fields are missing.

---

## 15. Company Analysis Engine

### 15.1 Inputs Per Stock

Each candidate is analyzed from:

- `CandidateRecord`
- `MarketSnapshot`
- `NewsBundle`
- expanded option chain
- `UserContext`

### 15.2 Direction Classification

Current direction logic is deterministic, not LLM-driven.

Classification rules:

- `bullish` when bias >= `0.12`
- `bearish` when bias <= `-0.12`
- `neutral` otherwise
- `avoid` when price is missing or data confidence is below 40

### 15.3 Direction and Opportunity Scoring

The current architecture uses deterministic per-candidate scoring and reserves
the heavy LLM route for the final cross-candidate choice.

### 15.3.1 Stage 1: Candidate Direction Score

Direction score components:

- trend alignment
- relative strength
- volume confirmation
- news/catalyst quality
- earnings expectation context
- market/sector environment
- price structure
- data confidence

### 15.3.2 Stage 2: Contract Opportunity Score

Contract score components:

- breakeven feasibility
- liquidity
- expiry fit
- strike or moneyness fit
- IV setup
- premium/risk fit
- direction compatibility

Hard vetoes zero out the final contract score.

### 15.3.3 Final Opportunity Score

Current combination:

```text
final score = 45% direction score + 55% contract score
```

### 15.3.4 Recommendation Thresholds

Current action rules:

- `no_trade` if no viable contract exists
- `no_trade` if confidence blockers exist
- `no_trade` if confidence score < 40
- `watchlist` if confidence is 40-54 and score >= 60
- `watchlist` if score is 60-67 without a full recommendation
- `recommend` if score >= 68 and no blockers remain

### 15.3.5 Hard Vetoes

Current hard vetoes include:

- unverified earnings date
- missing current price
- empty option chain
- expiry outside the valid earnings window
- missing long ask or short bid
- unusable quote
- zero open interest and zero volume
- extreme spread
- stale or non-tradable contract
- user risk settings allow zero contracts
- strategy side disabled for the user

### 15.3.6 Soft Penalties

Current soft penalties include:

- mixed news
- weak sector alignment
- light same-day option volume
- moderate or wide spreads
- elevated IV for longs
- weak IV for shorts
- valid but less-ideal expiry
- earnings-history versus implied-move mismatch

---

## 16. Option Strategy Support

### 16.1 V1 Supported Strategies

Current supported strategies:

- `long_call`
- `long_put`
- `short_put`
- `short_call`

### 16.2 Strategy Selection Logic

Current mapping is deterministic and filtered by user permission.

The strategy selector also tilts toward short premium when IV is rich enough
and the direction score is not extremely strong.

### 16.3 Direction-to-Strategy Mapping

| Direction | Allowed Strategies |
|---|---|
| Bullish | `long_call`, `short_put` |
| Bearish | `long_put`, `short_call` |
| Neutral / Avoid | none |

---

## 17. Expiry Selection

### 17.1 Expiry Window

Current valid expiry window:

- not before earnings date
- not more than 30 calendar days after earnings

### 17.2 Earnings Timing Rule

Current timing rule:

- same-day expiry is only valid when earnings timing is `BMO`
- same-day long expiries are allowed but penalized even for `BMO`

### 17.3 Expiry Selection Factors

Expiry scoring considers:

- days after earnings
- strategy type
- risk profile
- whether the expiry is merely valid or also preferred

### 17.4 Expiry Preference by Strategy

Current preferences:

- long strategies: strongest in the 3-21 day window after earnings
- short strategies: strongest in the 0-14 day window after earnings

---

## 18. Strike Selection

### 18.1 Long Options Strike Guidance

Current strike candidate selection samples:

- near-ATM
- slight ITM
- slight OTM
- best breakeven candidate
- best liquidity candidate

### 18.2 Short Options Strike Guidance

Current short-option sampling emphasizes:

- slight OTM
- moderate OTM
- strongest safety buffer
- best liquidity

### 18.3 Strike Flexibility

The system does not score the full raw chain blindly. It first picks a focused
set of representative strike candidates per expiry, deduplicates them, and
then scores that smaller set.

---

## 19. Liquidity and Spread Parameters

### 19.1 Hard Liquidity Rejects

Current hard rejects:

- zero open interest and zero same-day volume
- unusable quote
- extreme spread with no cheap-contract exception
- stale or non-tradable contract

### 19.2 Balanced Liquidity Thresholds

Current liquidity score biases:

- open interest >= 100 is strong
- volume >= 25 is strong
- spread <= 15% is strong
- spread <= 25% is usable

### 19.3 Flexible Acceptance Rule

The architecture is intentionally not all-or-nothing. Cheap contracts may still
be considered when percentage spread looks wide but absolute spread remains
reasonable.

### 19.4 Spread Rules

Current spread handling:

- `> 15%` adds a moderate penalty
- `> 25%` adds a stronger penalty
- `> 35%` can trigger a hard veto

### 19.5 Avoid Killing the Agent

If the workflow cannot justify a full recommendation but a candidate is still
interesting, the final action should prefer `watchlist` over silently discarding
all signal.

### 19.6 Option Chain Retrieval Order

Current order:

1. Alpaca by normalized ticker variants when credentials exist
2. yfinance by normalized ticker variants
3. in-memory per-day chain cache inside the options service

---

## 20. IV, Expected Move, and Breakeven Logic

### 20.1 Required Calculations

Current calculations include:

- option premium
- midpoint
- breakeven price
- breakeven move percent
- spread percent
- premium collected for short options
- contract capacity from user sizing

### 20.2 Breakeven Formulas

Current breakeven math:

```text
Long Call breakeven  = strike + premium
Long Put breakeven   = strike - premium
Short Put buffer     = premium below strike
Short Call buffer    = premium above strike
```

### 20.3 Strategy-Specific IV Interpretation

Current IV preferences:

- longs prefer lower IV
- shorts prefer richer IV
- missing IV is allowed but reduces confidence

### 20.4 Expected Move Decision Rule

When contextual move data is available, the contract score compares required
breakeven move against expected or prior earnings move. When that data is
missing, the scoring engine falls back to simpler heuristics instead of
fabricating precision.

---

## 21. Recommendation Engine

### 21.1 Per-Stock Output

Each candidate analysis produces:

- direction result
- confidence result
- considered contracts
- chosen best contract if one survives
- final candidate score
- candidate action (`recommend`, `watchlist`, `no_trade`)

### 21.2 Final Selection

The final selection step is cross-candidate.

Current architecture:

- build a structured decision payload from all five candidates
- ask the heavy LLM route to choose one setup or no trade
- validate the response against actual candidate/contract IDs
- fall back to heuristic selection on transient LLM failure

### 21.3 No-Trade Rule

If the final action is `no_trade`:

- no recommendation row is created
- the workflow run status becomes `no_trade`
- candidate cards and contract logs are still persisted
- the user still receives watchlist names and reasoning

---

## 22. News and Web Research

### 22.1 Purpose

News is used to add catalyst context, not to override hard market-data or
options-data constraints.

### 22.2 Lightweight Model Role

The lightweight model summarizes recent fetched articles into:

- bullish evidence
- bearish evidence
- neutral/contextual evidence
- key uncertainty
- news confidence

### 22.3 Heavy Model Role

The heavy model does not perform article-by-article browsing in the current
architecture. It consumes the already-prepared news brief during the final
decision step.

### 22.4 News Summary Format

Current brief structure:

```text
Bullish evidence
Bearish evidence
Neutral/contextual evidence
Key uncertainty
News confidence
```

---

## 23. Logging System

### 23.1 Purpose

The logging system should make every run explainable after the fact.

### 23.2 Recommendation Card

Current recommendation-card fields include:

- card ID, user ID, run ID, timestamp
- trigger type
- selected ticker and company
- selected strategy and selected contract
- contract rationale
- suggested entry and quantity
- confidence score and data confidence
- risk profile and account size snapshot
- earnings date and timing
- key evidence and concerns
- rejected alternatives
- decision engine and engine notes
- heavy and light model IDs
- action and reasoning
- watchlist tickers
- warning text
- Telegram message and message ID

### 23.3 Per-Candidate Logs

Current candidate-card data includes:

- ticker
- company name
- market cap
- earnings date
- direction classification
- direction score
- best strategy
- final opportunity score
- selected or rejected reason
- data confidence
- selected-for-final flag

### 23.4 Option Contract Logs

Current option-contract log fields include:

- ticker
- option type
- position side
- strike
- expiry
- bid / ask / mid
- volume / open interest
- IV / delta
- breakeven
- spread percent
- liquidity score
- contract score
- hard-filter pass/fail
- rejection reason

### 23.5 Logging Format

Current storage layers:

- `workflow_runs.run_summary_json`
- `workflow_runs.candidate_cards_json`
- `workflow_runs.option_contracts_json`
- `workflow_runs.recommendation_card_json`
- `workflow_runs.telegram_message_text`

Outside test mode, the same artifacts are also archived under:

```text
var/runs/<run_id>/
```

### 23.6 V2 Feedback Loop Preparation

V1 already stores enough context for V2 feedback work:

- user action (`bought` / `skipped`)
- original recommendation context
- candidate and contract alternatives
- final reasoning

---

## 24. Database Schema

### 24.1 `users`

Current fields:

- `id`
- `telegram_chat_id`
- `account_size`
- `risk_profile`
- `custom_risk_percent`
- `broker`
- `timezone_label`
- `timezone_iana`
- `strategy_permission`
- `max_contracts`
- `max_option_premium`
- encrypted API key fields for OpenRouter, Alpaca key, Alpaca secret, and
  Alpha Vantage
- `is_active`
- `created_at`
- `updated_at`

### 24.2 `cron_jobs`

Current fields:

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| trigger_type | cron/manual |
| status | running/success/failed/no_trade |
| started_at | timestamp |
| finished_at | timestamp |
| screener_status | success/partial/failed |
| selected_candidate_count | integer |
| final_recommendation_id | UUID/null |
| error_message | text/null |

### 24.3 `workflow_runs`

| Field | Type |
|---|---|
| id | UUID |
| run_id | UUID |
| ticker | string |
| company_name | string |
| market_cap | decimal |
| earnings_date | date |
| earnings_timing | string/null |
| current_price | decimal |
| strategy_source | catalyst_confluence/coiled_setup |
| direction_classification | string |
| candidate_direction_score | integer |
| best_strategy | string/null |
| final_opportunity_score | integer |
| data_confidence_score | integer |
| selected_for_final | boolean |
| created_at | timestamp |

- `id`
- `user_id`
- `trigger_type`
- `status`
- `started_at`
- `finished_at`
- `screener_status`
- `selected_candidate_count`
- `final_recommendation_id`
- `error_message`
- `run_summary_json`
- `candidate_cards_json`
- `option_contracts_json`
- `recommendation_card_json`
- `telegram_message_text`

### 24.4 `candidates`

Current fields:

- `id`
- `run_id`
- `ticker`
- `company_name`
- `market_cap`
- `earnings_date`
- `earnings_timing`
- `current_price`
- `direction_classification`
- `candidate_direction_score`
- `best_strategy`
- `final_opportunity_score`
- `data_confidence_score`
- `selected_for_final`
- `created_at`

### 24.5 `option_contracts`

Current fields:

- `id`
- `candidate_id`
- `ticker`
- `option_type`
- `position_side`
- `strike`
- `expiry`
- `bid`
- `ask`
- `mid`
- `volume`
- `open_interest`
- `implied_volatility`
- `delta`
- `breakeven`
- `spread_percent`
- `liquidity_score`
- `contract_opportunity_score`
- `passed_hard_filters`
- `rejection_reason`
- `created_at`

### 24.6 `recommendations`

Current fields:

- `id`
- `user_id`
- `run_id`
- `parent_recommendation_id`
- `ticker`
- `company_name`
- `strategy`
- `option_type`
- `position_side`
- `strike`
- `expiry`
- `suggested_entry`
- `suggested_quantity`
- `estimated_max_loss`
- `account_risk_percent`
- `confidence_score`
- `risk_level`
- `reasoning_summary`
- `key_evidence_json`
- `key_concerns_json`
- `telegram_message_id`
- `created_at`

### 24.7 `feedback_events`

Current fields:

- `id`
- `recommendation_id`
- `user_id`
- `user_action`
- `entry_price`
- `exit_price`
- `pnl`
- `note`
- `created_at`

---

## 25. Backend Architecture

### 25.1 Current Stack

| Layer | Current Choice |
|---|---|
| Language | Python 3.12 |
| App lifecycle | FastAPI |
| Telegram bot | aiogram 3 |
| Scheduler | APScheduler |
| Database | PostgreSQL |
| Cache / locks | Redis |
| ORM | SQLAlchemy async + Alembic |
| Browser automation | Playwright |
| Screener | Finviz |
| Market data | yfinance + Alpha Vantage support |
| Options data | Alpaca primary when configured, yfinance fallback |
| LLM routing | OpenRouter |

### 25.2 Service Components

| Component | Module |
|---|---|
| Telegram Bot Service | User interaction |
| Schedule Service | Cron management |
| Finviz Browser Service | Dual-strategy screener (Strategy A + B) with Redis cache |
| Candidate Service | Candidate extraction, validation, and multi-strategy merge |
| Market Data Service | OHLCV, market cap, sector data |
| News Service | Web/news gathering |
| Options Service | Option chain retrieval from Alpaca first, yfinance fallback |
| Scoring Service | Direction and contract scoring |
| Risk/Sizing Service | Quantity and exposure calculation |
| LLM Router | Routes tasks to Opus or Gemini |
| Recommendation Service | Final trade/no-trade decision |
| Logging Service | Stores evidence cards |
| Feedback Stub | Stores simple user feedback for V2 |

---

## 26. Error Handling

### 26.1 Finviz Screener Failure

If Finviz cannot be accessed for one or both strategies:

1. Retry browser session with a clean browser context.
2. If Strategy A fails but Strategy B succeeds, continue with partial results (`screener_status = "partial"`).
3. If Strategy B fails but Strategy A succeeds, continue with partial results (`screener_status = "partial"`).
4. If both fail, try backup earnings calendar (Finnhub/yfinance). Set `screener_status = "failed"`.
5. Notify user via Telegram if screener was degraded.

If backup candidates are used, surface this warning:

```text
⚠️ Finviz Strategy A did not load, so I used structure-driven setups only for this scan.
```

### 26.2 Option Chain Failure

Current option-chain fallback behavior:

1. try Alpaca when credentials exist
2. fall back to yfinance
3. if both fail, the candidate can still be analyzed but should not produce an
   invented contract
4. final action should become `watchlist` or `no_trade`

### 26.3 Missing Data

Critical blockers include:

- missing ticker
- unverified earnings date
- missing current price
- missing expiry
- missing strike
- unusable quote
- invalid user account size
- invalid or missing OpenRouter key for final recommendation work

Non-critical missing fields should reduce confidence rather than automatically
crashing the run.

---

## 27. Data Confidence System

### 27.1 Purpose

Data confidence should measure whether the system has enough reliable input to
support a recommendation.

### 27.2 Current Confidence Weights

| Component | Weight |
|---|---:|
| Earnings-date confidence | 25% |
| Options-data confidence | 22% |
| Market-data confidence | 20% |
| Identity confidence | 13% |
| Cross-source agreement | 10% |
| Calculation integrity | 7% |
| News coverage | 3% |

### 27.3 Data Confidence Interpretation

| Score | Label | Action |
|---|---|---|
| 85 to 100 | strong | recommendation allowed |
| 70 to 84 | good | recommendation allowed |
| 55 to 69 | partial | recommendation allowed only if score is strong |
| 40 to 54 | weak | watchlist or no trade |
| below 40 | critical | no trade |

### 27.4 Critical Field Override

Even if the data confidence score is numerically above 40, the system must block the recommendation if any critical field is missing.

Critical blocking fields:

- ticker
- strategy_source (which Finviz strategy surfaced this candidate — required for V2 feedback attribution)
- verified earnings date (Strategy A candidates only; Strategy B candidates may have no earnings date)
- current price
- contract type
- position side
- strike
- expiry
- usable bid/ask or mid
- user account size
- risk profile
- valid OpenRouter API key

### 27.5 Missing Greeks Rule

Missing Greeks should not automatically kill the trade. The current engine can
fall back to:

- moneyness
- premium
- spread quality
- liquidity
- confidence penalties

### 27.6 Source Conflict Rule

Cross-source conflicts should:

- create confidence notes
- lower confidence adjustment
- become blockers only when they affect critical fields

### 27.7 Data Confidence in Telegram

The main recommendation message should stay readable. Confidence detail belongs
mainly in logs and supporting views unless a data issue materially affects the
trade decision.

---

## 28. Acceptance Criteria

### 28.1 Workflow Acceptance Criteria

The workflow passes if:

- the scheduled scan runs at the correct user timezone
- manual scan can be triggered from Telegram
- Finviz Strategy A screener opens and runs (both earningsdate variants)
- Finviz Strategy B screener opens and runs (both pattern variants)
- results from both strategies are merged and deduped
- screener_status is recorded (success / partial / failed)
- up to 10 candidates are passed to the scoring pipeline
- option chains are retrieved or failure is logged
- one recommendation or no-trade result is produced
- Telegram message is delivered (with partial/failed warning if applicable)
- recommendation card is stored with strategy_source per candidate

### 28.2 Recommendation Acceptance Criteria

A recommendation must include:

- ticker
- direction
- contract
- strike
- expiry
- suggested entry
- quantity or watchlist-only status
- risk warning
- confidence
- reasoning

### 28.3 Schedule Acceptance Criteria

The user must be able to:

- add, edit, delete, pause, and resume schedules
- see stored schedules in local time
- trigger a manual run without bypassing the run lock

### 28.4 Logging Acceptance Criteria

Every completed run must store:

- run summary
- candidate cards
- option contract logs
- recommendation card or no-trade context
- Telegram message text

---

## 29. MVP Scope

### 29.1 V1 Must Include

- Telegram bot onboarding
- user settings
- OpenRouter API key storage
- Alpaca API key and secret storage
- optional Alpha Vantage key storage
- Finviz browser automation (Strategy A + Strategy B)
- Strategy A: earnings catalyst filter, relative volume sort
- Strategy B: coiled pattern filter, half-year performance sort
- multi-strategy merge with up to 10 candidates and strategy_source tagging
- Redis cache for Finviz queries (600 s TTL)
- market data retrieval
- option chain retrieval
- web/news gathering
- Claude Opus 4.7 Thinking for heavy reasoning
- Gemini 3.1 Flash for lighter tasks
- long call support
- long put support
- short put support
- short call support
- scoring system
- position sizing
- cron job management
- manual run button
- recommendation/no-trade output
- structured run logging

### 29.2 V1 Should Not Include

- broker execution
- auto-trading
- public web dashboard
- multi-leg options strategies
- payment system
- automated strategy self-modification

---

## 30. V2 Scope

V2 can add:

- deeper feedback capture
- post-earnings result tracking
- richer recommendation drill-downs
- performance reporting
- multi-leg strategies
- stronger option-data providers
- historical evaluation tools

### 30.1 V2 Feedback Agent

The existing `feedback_events` table is enough to support a later feedback
agent that asks the user what happened after the trade and compares outcome
versus original thesis.

---

## 31. Suggested Development Phases

The detailed phase plan now lives in [`Plan1.md`](./Plan1.md). From the
perspective of the current architecture, the major milestones are:

Build:

- Telegram bot
- onboarding
- settings screens
- API key storage
- timezone selection
- risk profile selection
- strategy permission setting
- cron job UI

### Phase 2: Finviz Dual-Strategy Candidate Extraction

Build:

- Playwright browser automation
- Finviz Strategy A screener (earningsdate_thisweek + earningsdate_nextweek variants, dedupe)
- Finviz Strategy B screener (channelup2 + triangleascending variants, dedupe)
- concurrent execution via asyncio.gather, Semaphore(2) rate limiter
- Redis cache (FinvizScreenerCache, 600 s TTL, key: screener:{strategy_source}:{hash}:{date})
- multi-strategy merge and ticker-level deduplication (A wins ties)
- strategy_source tagging on every CandidateRecord
- screener_status reporting (success / partial / failed)
- fallback to Finnhub/yfinance earnings calendar if both strategies fail

### Phase 3: Market and Options Data

Build:

- market data service
- Alpaca option chain service
- yfinance fallback option chain service
- fallback data logic
- data confidence scoring
- candidate validation

### Phase 4: Scoring and Recommendation

Build:

- Direction Score
- Contract Opportunity Score
- Final Opportunity Score
- long/short strategy selection
- position sizing
- no-trade logic

### Phase 5: LLM Integration

Build:

- OpenRouter integration
- Claude Opus 4.7 Thinking route
- Gemini 3.1 Flash route
- structured prompts
- structured outputs
- final recommendation generation

### Phase 6: Logging

Build:

- recommendation cards
- candidate logs
- contract logs
- run summaries
- Telegram message archive

### Phase 7: Testing

Test:

- manual scan
- Monday scheduled scan
- timezone behavior
- multiple cron jobs
- bad OpenRouter API key
- bad Alpaca API key/secret
- TradingView failure
- missing option chain
- no-trade result
- long call recommendation
- long put recommendation
- short put recommendation
- short call recommendation

---

## 32. Final Product Behavior Example

### 32.1 Normal Weekly Run

Bot status message:

```text
📊 Weekly scan is ready.
```

Then the bot sends either:

- one best setup
- one watchlist-only setup
- or a no-trade result

### 32.2 Manual Run

User taps:

```text
🚀 Run Scan Now
```

Bot replies:

```text
🧠 Starting a fresh earnings-options scan now.
```

### 32.3 No Trade

Example:

```text
📊 Scan complete.

No trade looks strong enough this time. The best setups had either weak
direction, poor option pricing, or not enough data confidence.
```

---

## 33. Build Priorities

Current priorities:

1. Finviz dual-strategy extraction (Strategy A + B, merge, dedupe)
2. option-chain retrieval
3. expiry logic around earnings date
4. long vs short option selection
5. scoring system
6. data confidence scoring
7. Telegram UX
8. logging system

Lower priorities:

1. decorative UI polish
2. public dashboards
3. advanced analytics beyond the stored run artifacts

---

## 34. Definition of Done for V1

V1 is done when:

- a user can onboard from Telegram
- a user can set account size, timezone, risk profile, and API key
- a user can manage cron jobs from Telegram buttons
- the default Monday 10:30 AM Montreal schedule works
- the user can manually run the workflow
- the agent runs Finviz Strategy A (both earnings date variants) and Strategy B (both pattern variants)
- the agent merges up to 10 candidates with strategy_source tagging
- the agent retrieves option-chain data from Alpaca first, with yfinance fallback
- the agent uses Gemini 3.1 Flash for light research
- the agent uses Claude Opus 4.7 Thinking for final analysis
- the agent supports long calls, long puts, short puts, and short calls
- the agent sends one recommendation or no-trade message
- the recommendation includes contract details and reasoning
- the system stores a complete recommendation card and evidence log
