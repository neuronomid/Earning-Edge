# PRD: Earnings Options Recommendation Agent

**Version:** V1.1  
**Update:** Alpaca Options Snapshots API added as the primary option-chain source; Yahoo Finance / yfinance moved to fallback; Alpha Vantage remains optional supporting data.

## 1. Product Summary

The Earnings Options Recommendation Agent is a Telegram-based agent that scans upcoming earnings, selects the top five companies by market capitalization, analyzes their likely earnings-related price movement, evaluates available options contracts, and sends a friendly Telegram recommendation to the user.

The agent runs automatically based on user-defined cron jobs. The default cron job is:

**Every Monday at 10:30 AM Montreal, Quebec local time**

The user can also manually trigger the workflow anytime from Telegram.

The agent does not place trades. It only provides structured recommendations and reasoning so the user can manually review and execute the trade in their preferred broker.

---

## 2. Core Product Objective

The product should answer one practical question:

> “Among the largest companies reporting earnings next week, which option contract has the best opportunity based on trend, earnings setup, market context, option chain quality, pricing, and expected move?”

The output should be a simple Telegram message with:

- the chosen ticker
- the trade direction
- the option type
- strike
- expiry
- suggested entry/premium
- suggested quantity
- short reasoning
- confidence score
- key evidence
- why the agent chose that contract over alternatives

---

## 3. Core Workflow

### 3.1 Weekly Automated Workflow

Default run:

```text
Monday 10:30 AM Montreal, Quebec local time
```

Workflow:

```text
Cron Trigger
   ↓
Open TradingView Screener
   ↓
Filter: Upcoming earnings date = Next week
   ↓
Sort: Market capitalization descending
   ↓
Select top 5 companies
   ↓
Gather market data, chart data, option chain data, earnings context, and news
   ↓
Analyze each stock direction
   ↓
Analyze long and short option opportunities
   ↓
Select one best contract or return “No trade”
   ↓
Send recommendation through Telegram
   ↓
Store recommendation card and evidence logs
```

### 3.2 Manual Workflow

The user can start the workflow anytime from Telegram.

Manual trigger options:

- **Run Scan Now**
- **Run Earnings Scan**
- **Refresh Last Scan**
- **Analyze Specific Ticker**
- **Show Last Recommendation**

Manual runs should follow the same pipeline as the scheduled run unless the user specifically chooses a custom ticker.

---

## 4. Main Requirements

### 4.1 The Agent Must

1. Use TradingView Screener through browser automation.
2. Filter for stocks with earnings next week.
3. Sort the TradingView table by market capitalization descending.
4. Select the top five stocks.
5. Gather additional market, option, chart, earnings, and news data.
6. Analyze bullish and bearish scenarios.
7. Evaluate both long and short options.
8. Choose only one direction per stock: bullish, bearish, neutral, or avoid.
9. Never recommend both a call and a put for the same stock in the same run.
10. Select the best overall opportunity across the top five.
11. Send a clear Telegram recommendation.
12. Store a compact evidence-based log card for each recommendation.
13. Allow user-configurable account size, risk profile, timezone, API keys, and cron schedules.

### 4.2 The Agent Must Not

1. Execute trades.
2. Connect to broker accounts in V1.
3. Recommend both call and put for the same stock.
4. Invent missing data.
5. Ignore option liquidity.
6. Ignore earnings timing.
7. Ignore option expiry relative to earnings.
8. Depend on one data source only.
9. Require users to memorize Telegram slash commands.

---

## 5. TradingView Screener Integration

### 5.1 Purpose

TradingView Screener is used as the primary visual screener for selecting the top five companies reporting earnings next week.

The agent should open:

```text
https://www.tradingview.com/screener/
```

Then apply:

```text
Filter: Upcoming earnings date = Next week
Sort: Market capitalization = Descending
Select: Top 5 rows
```

### 5.2 Allowed Automation Method

The agent can use:

- Playwright CLI
- Playwright script
- browser-use style automation
- MCP browser automation server
- visible browser interaction
- accessibility tree extraction
- screenshot + vision model extraction if needed

### 5.3 TradingView Extraction Rule

The agent should only rely on data visible in the TradingView browser session.

Preferred extraction methods:

1. Browser accessibility snapshot
2. Visible table text extraction
3. Screenshot analysis
4. Manual fallback if browser automation fails

The system should not use hidden/private TradingView APIs.

### 5.4 Required Extracted Fields

For each of the top five rows, extract:

| Field | Required |
|---|---:|
| Ticker | Yes |
| Company name | Yes |
| Market cap | Yes |
| Upcoming earnings date | Yes |
| Current price | Preferred |
| Daily change % | Preferred |
| Volume | Preferred |
| Sector/industry | Preferred |

If TradingView does not expose all preferred fields, the agent should fill missing fields from backup data sources.

---

## 6. Data Sources

The system should use a free-data-first architecture.

### 6.1 Primary Data Sources

| Data Need | Primary Source | Backup Source |
|---|---|---|
| Top-five earnings candidates | TradingView Screener browser automation | Earnings calendar API |
| Earnings date verification | TradingView + backup API | Yahoo Finance / Finnhub / Alpha Vantage |
| Market cap | TradingView | Yahoo Finance / yfinance |
| Historical OHLCV | Yahoo Finance / yfinance | Alpha Vantage |
| Option chains | Alpaca Options Snapshots API | Yahoo Finance / yfinance |
| Option Greeks | Alpaca Options Snapshots API | calculated/estimated when unavailable |
| Option bid/ask/quote data | Alpaca indicative options feed | Yahoo Finance / yfinance |
| News and catalysts | Web search | company investor relations pages |
| Market context | SPY, QQQ, VIX proxy | Yahoo Finance |
| Sector context | sector ETFs | Yahoo Finance |
| LLM reasoning | OpenRouter | user-provided OpenRouter API key |

### 6.2 Alpaca Options Data Role

Alpaca should be the primary V1 source for option-chain data.

Use Alpaca Options Snapshots API for:

- full option chains
- calls and puts
- bid/ask quote data
- latest trade data if available
- Greeks if available
- implied volatility if available
- expiry filtering
- strike filtering

The default Alpaca setup should use the free indicative options feed when available. This is suitable for research, screening, and educational testing, but the user must still verify the final contract price inside their broker before manually entering any trade.

Required Alpaca credentials:

- Alpaca API key
- Alpaca API secret

The user should be able to add, edit, test, or remove Alpaca credentials from Telegram settings.

### 6.3 Yahoo Finance / yfinance Fallback Role

Yahoo Finance / yfinance should be the fallback option-chain source.

Use yfinance when:

- Alpaca credentials are missing
- Alpaca API request fails
- Alpaca does not return the needed contract
- a backup comparison is needed
- option Greeks are not critical for the selected scoring path

Because yfinance is unofficial and may have incomplete option fields, the system should reduce data confidence when it relies only on yfinance for final option-chain data.

### 6.4 Alpha Vantage Role

The user may provide a free Alpha Vantage API key.

Use Alpha Vantage when available for:

- company overview
- earnings calendar if available
- daily time series
- news sentiment if available
- additional cross-checking

Alpha Vantage should not be the primary option-chain provider in V1 because the free tier may not provide the options-chain depth and real-time option data needed by the agent.

### 6.5 Free Data Fallback Rule

If one source fails:

```text
Try source A
   ↓
If missing, try source B
   ↓
If still missing, use cached data if fresh
   ↓
If critical fields are unavailable, do not fabricate data
   ↓
Either downgrade confidence or return No Trade
```

Critical fields are defined in Section 27.3.

---

## 7. Model Routing and API Key Requirements

### 7.1 User-Provided OpenRouter API Key

Each user must be able to provide their own OpenRouter API key.

The app should store the key encrypted.

Required behavior:

- User enters OpenRouter API key in Telegram onboarding or settings.
- System validates the key with a lightweight test call.
- If the key fails, the user is prompted to update it.
- LLM workflows do not run without a valid key.
- The key can be edited or removed from Telegram settings.

### 7.2 Heavy Reasoning Model

Heavy reasoning must be handled by:

```text
Claude Opus 4.7 Thinking
```

This model is responsible for:

- market analysis
- trend interpretation
- option-chain assessment
- comparing long vs short options
- expected move reasoning
- earnings setup assessment
- contract selection
- final confidence calculation
- reasoning summary
- risk/reward assessment
- deciding whether to recommend a trade or avoid

Implementation note:

Use a configurable model alias, for example:

```text
MARKET_ANALYSIS_MODEL = claude-opus-4.7-thinking
```

The exact OpenRouter model ID should be stored in environment configuration so it can be updated without code changes.

### 7.3 Lightweight Model

Lighter tasks should be handled by:

```text
Gemini 3.1 Flash
```

Gemini 3.1 Flash is responsible for:

- browsing assistance
- news gathering
- summarizing articles
- extracting key points from web pages
- preparing short candidate summaries
- Telegram message drafting
- Telegram message interpretation
- button/menu response handling
- summarizing logs for display

Implementation note:

Use a configurable model alias, for example:

```text
LIGHTWEIGHT_MODEL = gemini-3.1-flash
```

### 7.4 Model Separation Rule

The lightweight model can collect and summarize information, but it should not make the final trade decision.

Final decision authority:

```text
Claude Opus 4.7 Thinking
```

### 7.5 Model Input Discipline

The heavy reasoning model must receive structured data, not vague prompts.

For each stock, pass:

- ticker
- company name
- earnings date
- earnings timing if known
- market cap
- current price
- recent returns
- trend indicators
- sector comparison
- market comparison
- news summary
- option chain candidates
- contract liquidity data
- expected move data
- previous earnings move data if available
- data confidence score
- rejected contract reasons

---

## 8. User Settings

### 8.1 Required User Settings

| Setting | Type | Example | Required |
|---|---|---:|---:|
| Telegram chat ID | string | `123456789` | Yes |
| Account size | number | `$5,000` | Yes |
| Risk profile | enum | Conservative / Balanced / Aggressive | Yes |
| Broker | enum/string | Wealthsimple / IBKR / Questrade / Other | Optional |
| Timezone | enum | Eastern (ET) | Yes |
| OpenRouter API key | encrypted string | `sk-or-...` | Yes |
| Alpaca API key | encrypted string | optional but strongly recommended | Preferred |
| Alpaca API secret | encrypted string | optional but strongly recommended | Preferred |
| Alpha Vantage API key | encrypted string | optional | No |
| Strategy permission | enum | Long only / Short only / Long and short | Yes |
| Max contracts | number | `3` | Yes |
| Max option premium | number | `$500` | Optional |
| Cron jobs | list | Monday 10:30 AM | Yes |

### 8.2 Timezone Options

The user must be able to select timezone from this list:

| Display Name | UTC Offset |
|---|---|
| Pacific (PT) | UTC-08:00 |
| Mountain (MT) | UTC-07:00 |
| Central (CT) | UTC-06:00 |
| Eastern (ET) | UTC-05:00 |
| Atlantic (AT) | UTC-04:00 |
| Newfoundland (NT) | UTC-03:30 |

Default:

```text
Eastern (ET), Montreal/Quebec local time
```

Implementation note:

The UI should show the above labels, but the backend should store an IANA timezone where possible so daylight saving time is handled correctly.

Recommended mapping:

| Display Name | Suggested IANA Timezone |
|---|---|
| Pacific (PT) | America/Vancouver |
| Mountain (MT) | America/Edmonton |
| Central (CT) | America/Winnipeg |
| Eastern (ET) | America/Toronto or America/Montreal |
| Atlantic (AT) | America/Halifax |
| Newfoundland (NT) | America/St_Johns |

### 8.3 Default User Settings

| Setting | Default |
|---|---|
| Default cron job | Monday 10:30 AM Eastern/Montreal time |
| Risk profile | Balanced |
| Strategy permission | Long and short |
| Max contracts | 3 |
| Max weekly recommendations | 1 main recommendation per scan |
| Minimum confidence for main recommendation | 68/100 |
| Action if score below threshold | Send No Trade + best watchlist setup |
| Telegram tone | Friendly, clear, lightly energetic |
| Emoji style | Light use, not excessive |

---

## 9. Risk Profile and Position Sizing

### 9.1 Risk Profile Defaults

| Risk Profile | Max Account Allocation Per Trade |
|---|---:|
| Conservative | 1% |
| Balanced | 2% |
| Aggressive | 4% |

The user should be able to edit these values later, but these are the defaults.

### 9.2 Long Options Sizing

For long calls and long puts:

```text
Max loss per contract = option ask price × 100
Trade budget = account size × risk percentage
Suggested contracts = floor(trade budget / max loss per contract)
```

Example:

```text
Account size = $5,000
Risk profile = Balanced = 2%
Trade budget = $100
Option ask = $0.85
Contract cost = $85
Suggested quantity = 1 contract
```

### 9.3 Short Options Sizing

V1 supports short calls and short puts, but sizing is more complex because broker margin requirements are not always available from free APIs.

For short options, the agent must calculate and display:

- premium collected
- strike price
- contract notional exposure
- breakeven
- distance from current price
- estimated margin requirement if possible
- whether max loss is defined or undefined
- whether the setup requires broker-side margin verification

For short puts:

```text
Approximate worst-case notional exposure = strike × 100 × contracts
```

For short calls:

```text
Theoretical max loss may be undefined if naked
```

The agent should still support short calls and short puts in V1, but it must clearly label the trade type and show broker verification requirements in the recommendation metadata.

### 9.4 Contract Quantity for Short Options

Because broker margin is unavailable in many free data sources, the agent should use conservative notional exposure limits.

Default short-option exposure rule:

| Risk Profile | Max Short Option Notional Exposure |
|---|---:|
| Conservative | 10% of account size |
| Balanced | 20% of account size |
| Aggressive | 35% of account size |

The agent should calculate:

```text
contracts = floor(max_short_notional_exposure / (strike × 100))
```

If the result is zero, the agent can still show the setup as “watch only” but should not suggest a contract quantity.

---

## 10. Telegram Bot UX

### 10.1 General UX Rule

The bot should not force users to memorize commands.

The bot should use:

- persistent reply keyboard
- inline keyboard buttons
- menu items
- guided forms
- quick action buttons
- confirmation prompts
- simple setting screens

Slash commands can exist as fallback, but buttons should be the main UX.

### 10.2 Main Menu Buttons

Suggested main menu:

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

After sending a recommendation, include inline buttons:

```text
🔍 Why this?
⚖️ Risk / Sizing
📈 Alternatives
📘 Save Note
✅ I bought it
❌ I skipped it
```

For V1, “I bought it” and “I skipped it” can be stored as simple log fields. The deeper feedback-loop system is V2.

### 10.4 Schedule Management Buttons

The schedule screen should support:

```text
➕ Add Cron Job
✏️ Edit Cron Job
🗑 Delete Cron Job
⏸ Pause Schedule
▶️ Resume Schedule
```

### 10.5 Settings Buttons

The settings screen should support:

```text
💰 Account Size
🎚 Risk Profile
🌎 Timezone
🏦 Broker
📜 Strategy Permission
🔢 Max Contracts
🔑 OpenRouter API Key
🔑 Alpaca API Key
🔑 Alpaca API Secret
🔑 Alpha Vantage API Key
```

### 10.6 Telegram Tone

Telegram messages should feel friendly, clear, and fresh.

Use light emojis, for example:

- 🚀
- 📊
- ⚠️
- ✅
- 🔍
- 🧠
- 📈
- 🗓

Do not overuse emojis. The message should still feel serious and useful.

Good tone:

```text
📊 Weekly scan is ready.

I found one setup that looks stronger than the rest. It is still an earnings trade, so the setup needs careful review before entry.
```

Avoid cold tone:

```text
Recommendation generated. Execute according to parameters.
```

Avoid hype tone:

```text
This is a guaranteed winner.
```

---

## 11. Onboarding Flow

### 11.1 First-Time Setup

1. User opens Telegram bot.
2. Bot welcomes user.
3. Bot asks for account size.
4. Bot asks for risk profile.
5. Bot asks for timezone.
6. Bot asks for broker.
7. Bot asks whether to allow:
   - long options only
   - short options only
   - long and short options
8. Bot asks for OpenRouter API key.
9. Bot asks for Alpaca API key and secret, with a clear option to skip and use yfinance fallback.
10. Bot optionally asks for Alpha Vantage API key.
11. Bot creates the default cron job:
    - Monday 10:30 AM Eastern/Montreal time
12. Bot shows setup summary.
13. User confirms settings.
14. Bot shows main menu.

### 11.2 Main Menu After Setup

After onboarding, the user should see:

```text
🚀 Run Scan Now
📊 Last Recommendation
🗓 Manage Schedule
⚙️ Settings
📘 Logs
```

---

## 12. Schedule and Cron Management

### 12.1 Default Cron Job

Create this by default:

```text
Monday 10:30 AM Eastern/Montreal local time
```

### 12.2 Multiple Cron Jobs

The user must be able to create multiple cron jobs.

Example:

```text
Monday 10:30 AM
Tuesday 9:00 AM
Friday 11:00 AM
```

If the user adds Tuesday at 9:00 AM, the bot should run on both:

```text
Monday 10:30 AM
Tuesday 9:00 AM
```

### 12.3 Cron Job Actions

The user must be able to:

- add a cron job
- edit an existing cron job
- delete a cron job
- pause all cron jobs
- resume all cron jobs
- run the workflow manually outside cron schedule

### 12.4 Cron Job Storage

Each cron job should store:

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| day_of_week | enum |
| time | HH:MM |
| timezone | enum/IANA |
| is_active | boolean |
| created_at | timestamp |
| updated_at | timestamp |

### 12.5 Cron Conflict Handling

If two cron jobs overlap or trigger within a short time window, the system should avoid duplicate runs.

Default rule:

```text
If the same user has a scan already running, do not start another scan.
```

If another run is requested manually while one is already running, Telegram should show:

```text
⏳ A scan is already running. I’ll show the result here when it finishes.
```

---

## 13. Recommendation Output Format

Telegram message should be short but complete.

### 13.1 Main recommendation template

**Weekly Earnings Options Signal**

**Best setup:** AMD  
**Direction:** Bullish  
**Contract:** AMD Call  
**Strike:** $X  
**Expiry:** YYYY-MM-DD  
**Suggested entry:** up to $X.XX premium  
**Suggested quantity:** X contract(s)  
**Estimated max loss:** $X  
**Account risk:** X%  
**Earnings date:** YYYY-MM-DD  
**Confidence:** 74/100  
**Risk level:** High

**Why this setup:**  
AMD is one of the largest companies reporting next week. The stock has positive short-term momentum, strong relative strength versus its sector, and recent news sentiment is supportive. The selected call is near-the-money, has acceptable liquidity, and the breakeven move is reasonable compared with recent earnings reactions.

**Important warning:**  
This trade holds through earnings. IV crush can reduce the option value after the report even if the stock moves in the expected direction.

**Action:**  
Manually review the contract in your broker before buying.

### 13.2 No-trade template

**Weekly Earnings Options Scan Complete**

I scanned the top five large-cap companies reporting earnings next week.

**Result:** No trade recommended.

**Reason:**  
The available options had poor risk/reward. The expected move was already expensive, bid-ask spreads were wide, and the directional edge was not strong enough to justify holding through earnings.

**Best watchlist names:**  
1. Ticker A  
2. Ticker B  
3. Ticker C

### 13.3 Short Option Output Note

For short options, the template should remain structurally similar, but the agent must clearly label the contract as:

```text
Short Call
Short Put
```

If maximum loss is undefined or broker-margin dependent, the “Estimated max loss” field should display:

```text
Broker/margin dependent
```

or:

```text
Undefined for naked short call
```

The recommendation card should still store all sizing, breakeven, notional exposure, and margin-estimate fields.

---

## 14. Candidate Selection Logic

### 14.1 Candidate Universe

The candidate universe starts from TradingView Screener.

Required filter:

```text
Upcoming earnings date = Next week
```

Required sort:

```text
Market capitalization = Descending
```

Required selection:

```text
Top 5 rows
```

### 14.2 Candidate Validation

After selecting the top five, validate each stock using backup data sources.

Validation checks:

| Check | Action if Missing |
|---|---|
| Ticker | reject candidate |
| Earnings date | verify from backup source |
| Market cap | fill from backup source |
| Current price | fill from backup source |
| Option chain availability | reject options analysis if unavailable |
| Historical candles | downgrade trend confidence |
| News availability | continue but downgrade news confidence |

### 14.3 Exclusions

Exclude candidates only for hard reasons:

- ticker cannot be verified
- earnings date cannot be verified
- no option chain is available
- current price is unavailable
- company has no usable market data
- selected expiry window has no options

Avoid overly aggressive exclusions. The agent should not reject a candidate just because one non-critical metric is missing.

---

## 15. Company Analysis Engine

### 15.1 Inputs Per Stock

Each top-five stock should be analyzed with the following inputs:

| Input | Purpose |
|---|---|
| Ticker | Contract matching |
| Company name | Telegram output |
| Earnings date | Expiry logic |
| Earnings timing | Before open / after close if available |
| Market cap | Ranking verification |
| Current price | Strike and moneyness |
| 1-day return | Short-term movement |
| 5-day return | Pre-earnings trend |
| 20-day return | Medium short-term trend |
| 50-day return | Broader trend |
| Volume vs average volume | Participation confirmation |
| Relative strength vs SPY/QQQ | Market comparison |
| Sector ETF trend | Sector confirmation |
| News summary | Catalyst context |
| Previous earnings move | Expected move comparison |
| Options implied move | Market expectation |
| Option chain | Contract selection |
| Data confidence score | Reliability adjustment |

### 15.2 Direction Classification

For each stock, the agent must classify the setup as one of:

| Classification | Meaning |
|---|---|
| Bullish | Consider long calls or short puts |
| Bearish | Consider long puts or short calls |
| Neutral | No directional edge |
| Avoid | Data or options setup is not usable |

The agent must not classify a stock as both bullish and bearish in the same final output.

### 15.3 Direction and Opportunity Scoring

This section is critical. The scoring system must avoid two failure modes:

1. Being too strict and almost never recommending anything.
2. Being too loose and recommending weak setups.

To solve this, V1 should use a two-stage scoring system:

```text
Stage 1: Candidate Direction Score
Stage 2: Contract Opportunity Score
```

The agent should not rely on one vague score.

---

### 15.3.1 Stage 1: Candidate Direction Score

Candidate Direction Score measures whether the stock has a clear directional setup before earnings.

Score range:

```text
0 to 100
```

Suggested weighting:

| Factor | Weight | Description |
|---|---:|---|
| Trend alignment | 20 | 5-day, 20-day, and 50-day direction |
| Relative strength | 15 | Stock vs SPY/QQQ and sector ETF |
| Volume confirmation | 10 | Recent volume compared with average |
| News/catalyst quality | 15 | Recent news supports direction |
| Earnings expectation context | 15 | Estimate revisions, previous earnings reaction, guidance tone if available |
| Market/sector environment | 10 | Broad market and sector are supportive |
| Price structure | 10 | Breakout, breakdown, support/resistance, pre-earnings compression |
| Data confidence | 5 | Reliability of data used |

Interpretation:

| Score | Meaning |
|---|---|
| 80 to 100 | Strong directional setup |
| 68 to 79 | Usable setup |
| 55 to 67 | Watchlist only unless contract score is excellent |
| Below 55 | Avoid directional recommendation |

Important rule:

A stock with a Direction Score of 60 can still produce a recommendation if the Contract Opportunity Score is very strong, especially for short-option IV strategies. But a stock below 55 should usually not produce a recommendation.

---

### 15.3.2 Stage 2: Contract Opportunity Score

Contract Opportunity Score measures whether the actual option contract is attractive enough.

Score range:

```text
0 to 100
```

Suggested weighting:

| Factor | Weight | Description |
|---|---:|---|
| Breakeven feasibility | 20 | Required move is reasonable compared with expected/historical move |
| Option liquidity | 15 | Volume, open interest, spread quality |
| Expiry fit | 15 | Expiry is well matched to earnings timing |
| Strike/moneyness fit | 15 | Strike makes sense for direction and strategy |
| IV setup | 15 | IV is favorable for long or short option structure |
| Premium/risk fit | 10 | Contract fits account size and risk profile |
| Direction compatibility | 10 | Contract type matches stock thesis |

Interpretation:

| Score | Meaning |
|---|---|
| 82 to 100 | Excellent contract |
| 70 to 81 | Good contract |
| 60 to 69 | Acceptable if direction score is strong |
| Below 60 | Avoid |

---

### 15.3.3 Final Opportunity Score

Final Opportunity Score combines the two stages:

```text
Final Score = (Candidate Direction Score × 0.45) + (Contract Opportunity Score × 0.55)
```

Reason:

The contract matters slightly more than the stock thesis because even a correct thesis can fail if the option is overpriced, illiquid, or poorly timed.

### 15.3.4 Recommendation Thresholds

Use tiered thresholds:

| Final Score | Action |
|---|---|
| 78+ | Strong recommendation |
| 68 to 77 | Recommendation allowed |
| 60 to 67 | Watchlist / only recommend if top setup and no major red flags |
| Below 60 | No trade |

Default recommendation threshold:

```text
68/100
```

The agent should not be killed by overly strict filters. If no setup reaches 68, the bot should still send the best watchlist names and explain why no trade was selected.

### 15.3.5 Hard Vetoes

Hard vetoes should be rare and only used when necessary.

Hard veto conditions:

- earnings date cannot be verified
- option chain unavailable
- expiry is before earnings
- bid/ask data missing for selected contract
- current price unavailable
- contract is not tradable or appears stale
- spread is extremely wide
- user risk settings allow zero contracts
- data confidence is critically low
- short option selected but user disabled short options
- long option selected but user disabled long options

### 15.3.6 Soft Penalties

Soft penalties should reduce score but not automatically reject the setup.

Soft penalty examples:

| Issue | Penalty |
|---|---:|
| News mixed | -5 to -10 |
| Sector trend weak | -3 to -8 |
| Option volume low but open interest acceptable | -3 to -7 |
| Spread wider than ideal but still usable | -5 to -12 |
| IV elevated for long options | -5 to -15 |
| IV too low for short options | -5 to -10 |
| Expiry slightly less ideal | -3 to -8 |
| Previous earnings moves inconsistent | -3 to -8 |

This approach allows the agent to still trigger when the setup is imperfect but reasonable.

---

## 16. Option Strategy Support

### 16.1 V1 Supported Strategies

V1 must support four single-leg option strategies:

| Strategy | Directional Thesis | Notes |
|---|---|---|
| Long Call | Bullish | Benefits from upside move |
| Long Put | Bearish | Benefits from downside move |
| Short Put | Bullish or neutral-bullish | Benefits from price staying above strike and IV collapse |
| Short Call | Bearish or neutral-bearish | Benefits from price staying below strike and IV collapse |

### 16.2 Strategy Selection Logic

The agent should decide between long and short options based on:

| Condition | More Suitable Strategy |
|---|---|
| Strong directional conviction + reasonable premium | Long call/put |
| Moderate directional conviction + high IV | Short put/call |
| Very high IV + unclear direction | Usually avoid single-leg directional recommendation |
| Poor liquidity | Avoid |
| Wide spreads | Avoid or watchlist |
| Expiry too close and move already priced in | Avoid or short-option candidate if allowed |

### 16.3 Direction-to-Strategy Mapping

| Stock Classification | Allowed Option Types |
|---|---|
| Bullish | Long call or short put |
| Bearish | Long put or short call |
| Neutral | No trade in V1 |
| Avoid | No trade |

The agent should select the best single contract among the allowed options.

---

## 17. Expiry Selection

### 17.1 Expiry Window

The expiry date can be:

```text
Same day after earnings up to 30 days after earnings
```

The LLM must decide the best expiry based on reasoning, inference, and calculations.

### 17.2 Earnings Timing Rule

If earnings are before market open:

```text
Same-day expiry is allowed if the option expires after the earnings event.
```

If earnings are after market close:

```text
Same-day expiry is not valid because the option would expire before the earnings reaction.
```

In that case, the earliest valid expiry is the next available expiry after the earnings event.

### 17.3 Expiry Selection Factors

The agent should consider:

- earnings date
- earnings timing
- expected move
- option liquidity by expiry
- IV level
- theta decay
- premium cost
- user risk profile
- strategy type
- historical earnings reaction window

### 17.4 Expiry Preference by Strategy

| Strategy | Preferred Expiry Range |
|---|---|
| Long call/put | 3 to 21 days after earnings |
| Short put/call | 0 to 14 days after earnings |
| Aggressive setup | 0 to 7 days after earnings |
| Conservative setup | 14 to 30 days after earnings |

These are preferences, not hard rules. The agent can choose any expiry from same day after earnings to 30 days after earnings if the reasoning supports it.

---

## 18. Strike Selection

### 18.1 Long Options Strike Guidance

For long calls and long puts, avoid being too restrictive.

Preferred range:

```text
Delta: 0.30 to 0.70
```

If Greeks are unavailable, approximate with moneyness:

| Contract Type | Preferred Moneyness |
|---|---|
| Long call | ATM to moderately OTM, or slightly ITM |
| Long put | ATM to moderately OTM, or slightly ITM |

Suggested default:

- prioritize ATM or slightly ITM when premium fits the user budget
- allow moderately OTM when the expected move justifies it
- avoid far OTM lottery contracts unless user chooses aggressive profile and the setup score is high

### 18.2 Short Options Strike Guidance

For short puts and short calls:

Preferred range:

```text
Absolute delta: 0.15 to 0.40
```

If Greeks are unavailable:

| Contract Type | Preferred Moneyness |
|---|---|
| Short put | OTM below current price |
| Short call | OTM above current price |

Default behavior:

- prefer OTM strikes with meaningful premium
- avoid strikes too close to current price unless confidence is high
- avoid strikes so far OTM that premium is tiny and not worth the setup

### 18.3 Strike Flexibility

Strike selection should not be too rigid.

The agent should compare multiple strikes and score them rather than only selecting one fixed delta.

For each expiry and strategy, evaluate:

- ATM
- slightly ITM
- slightly OTM
- moderate OTM
- best liquidity strike
- best breakeven strike
- best score strike

Then select the strongest contract based on the Contract Opportunity Score.

---

## 19. Liquidity and Spread Parameters

This section must be balanced. The thresholds should protect the recommendation quality without preventing the agent from ever triggering.

### 19.1 Hard Liquidity Rejects

Reject a contract only if one or more of these is true:

| Condition | Hard Reject |
|---|---:|
| Bid and ask are both missing | Yes |
| Ask is zero or invalid for long options | Yes |
| Bid is zero or invalid for short options | Yes |
| Open interest = 0 and volume = 0 | Yes |
| Bid-ask spread is extreme | Yes |
| Contract expiry is invalid | Yes |
| Contract strike is clearly wrong or corrupted | Yes |

### 19.2 Balanced Liquidity Thresholds

Preferred, but not mandatory:

| Metric | Preferred |
|---|---:|
| Open interest | 100+ |
| Same-day volume | 25+ |
| Bid-ask spread | ≤ 15% of mid price |
| Contract premium | Fits user risk profile |
| Expiry liquidity | Multiple nearby strikes available |

### 19.3 Flexible Acceptance Rule

A contract can still be considered if:

```text
Open interest is low but same-day volume is strong
```

or:

```text
Same-day volume is low but open interest is strong
```

Minimum acceptable rule:

```text
Open interest ≥ 50 OR same-day volume ≥ 20
```

If both are below this minimum, the contract should normally be rejected unless it is a highly liquid mega-cap ticker and all nearby strikes show consistent pricing.

### 19.4 Spread Rules

Spread percent:

```text
Spread % = (Ask - Bid) / Mid
```

Preferred:

```text
≤ 15%
```

Acceptable:

```text
15% to 25%
```

High penalty:

```text
25% to 35%
```

Hard reject:

```text
> 35%
```

For very cheap contracts under $0.50, spread percentage can look distorted. In that case, also check absolute spread.

Suggested absolute spread guidance:

| Premium Range | Preferred Max Absolute Spread |
|---|---:|
| Under $0.50 | $0.05 to $0.10 |
| $0.50 to $2.00 | $0.10 to $0.25 |
| Above $2.00 | $0.25 to $0.50 |

### 19.5 Avoid Killing the Agent

The system should not use overly strict filters like:

```text
Volume must be 500+
Open interest must be 1000+
Spread must be under 5%
```

Those rules may reject too many valid setups.

Instead:

- use hard rejects only for broken or unusable data
- use scoring penalties for imperfect contracts
- allow the best setup to surface if it is reasonable
- show “watchlist only” if the score is close but not strong enough

---
### 19.6 Option Chain Retrieval Order

For every selected ticker, the Options Service should retrieve option-chain data in this order:

```text
1. Alpaca Options Snapshots API
2. Yahoo Finance / yfinance fallback
3. Cached recent option-chain snapshot if still fresh
4. Mark option-chain data unavailable
```

Freshness rule:

| Source | Maximum Age for Scheduled Scan |
|---|---:|
| Alpaca indicative feed | current session or latest available snapshot |
| yfinance | current session if available |
| cached options snapshot | same trading day only |

If both Alpaca and yfinance are available, the system should prefer Alpaca for:

- bid/ask quotes
- Greeks
- implied volatility
- contract-level scoring

The system can still use yfinance as a cross-check for:

- expiry availability
- call/put table existence
- volume/open interest sanity check

If Alpaca and yfinance disagree significantly, the system should reduce data confidence and log the conflict.

---

## 20. IV, Expected Move, and Breakeven Logic

### 20.1 Required Calculations

For every candidate option, calculate:

- breakeven price
- breakeven move %
- expected move if available
- previous earnings move %
- option premium as % of stock price
- IV level if available
- IV rank/percentile if available
- directional move required for profit
- post-earnings sensitivity estimate if possible

### 20.2 Breakeven Formulas

Long call:

```text
Breakeven = strike + premium paid
```

Long put:

```text
Breakeven = strike - premium paid
```

Short put:

```text
Breakeven = strike - premium received
```

Short call:

```text
Breakeven = strike + premium received
```

### 20.3 Strategy-Specific IV Interpretation

| Strategy | IV Preference |
|---|---|
| Long call | Lower or reasonable IV preferred |
| Long put | Lower or reasonable IV preferred |
| Short put | Higher IV can be beneficial |
| Short call | Higher IV can be beneficial |

Important:

High IV is not automatically bad.  
It is bad for long options if the expected move is not enough.  
It may be attractive for short options if the directional and exposure setup is acceptable.

### 20.4 Expected Move Decision Rule

The agent should compare:

```text
required move for profit
vs
market implied move
vs
historical earnings move
vs
current trend strength
```

A long option should be favored when:

```text
expected/historical move > breakeven move by a reasonable margin
```

A short option should be favored when:

```text
premium collected is attractive and the selected strike is outside the most likely post-earnings range
```

---

## 21. Recommendation Engine

### 21.1 Per-Stock Output

For each of the top five stocks, the system should produce:

| Field | Description |
|---|---|
| Ticker | Stock symbol |
| Direction classification | Bullish / Bearish / Neutral / Avoid |
| Candidate Direction Score | 0 to 100 |
| Best strategy | Long call / long put / short put / short call / avoid |
| Best contract | strike + expiry |
| Contract Opportunity Score | 0 to 100 |
| Final Opportunity Score | 0 to 100 |
| Main evidence | 3 to 5 bullets |
| Rejection reasons | if avoided |
| Data confidence | 0 to 100 |

### 21.2 Final Selection

The agent should select:

```text
The best single opportunity across the top five companies
```

The final result can be:

- one long call
- one long put
- one short put
- one short call
- no trade

### 21.3 No-Trade Rule

No trade should be selected if:

- all Final Opportunity Scores are below 60
- critical data is missing
- all options fail basic liquidity checks
- earnings date cannot be verified
- no contract fits user settings
- data confidence is critically low

If the best score is between 60 and 67:

- do not send it as a strong recommendation
- send it as a watchlist setup
- explain what would need to improve

If the best score is 68 or higher:

- recommendation is allowed

If the best score is 78 or higher:

- strong recommendation label is allowed

---

## 22. News and Web Research

### 22.1 Purpose

News research is used to understand recent catalysts, sentiment, and context.

The news layer should answer:

- Is there recent company-specific news?
- Is there sector-specific momentum?
- Are analysts revising expectations?
- Is there a product launch, regulatory issue, lawsuit, merger, guidance update, or macro event?
- Is the news supportive or contradictory to the stock trend?

### 22.2 Gemini 3.1 Flash Role

Gemini 3.1 Flash should collect and summarize:

- recent headlines
- earnings preview articles
- company announcements
- sector news
- analyst expectation summaries
- market-wide context

### 22.3 Claude Opus 4.7 Thinking Role

Claude Opus 4.7 Thinking should decide how much the news matters for the final trade.

It should identify:

- strong catalyst
- weak catalyst
- contradictory catalyst
- irrelevant noise
- uncertainty

### 22.4 News Summary Format

For each ticker:

```text
News Summary:
- Bullish evidence:
- Bearish evidence:
- Neutral/contextual evidence:
- Key uncertainty:
- News confidence:
```

---

## 23. Logging System

### 23.1 Purpose

V1 must build a strong logging system even though the feedback loop is V2.

The logs should store compact “recommendation cards” explaining:

- what option was suggested
- what evidence supported the recommendation
- what alternatives were rejected
- what data was used
- what model made the final decision
- what the final confidence score was

These logs are the foundation for future improvement.

### 23.2 Recommendation Card

Each recommendation card should include:

| Field | Description |
|---|---|
| card_id | Unique card ID |
| user_id | User ID |
| run_id | Weekly/manual run ID |
| timestamp | Time of recommendation |
| trigger_type | Cron/manual |
| selected_ticker | Final ticker |
| selected_company | Company name |
| selected_strategy | Long call / long put / short put / short call / no trade |
| selected_contract | Strike, expiry, type |
| suggested_quantity | Number of contracts |
| confidence_score | Final score |
| risk_profile | Conservative/Balanced/Aggressive |
| account_size_snapshot | User account size at recommendation time |
| earnings_date | Earnings date |
| earnings_timing | Before open / after close / unknown |
| key_evidence | Short bullet list |
| key_concerns | Short bullet list |
| rejected_alternatives | Top rejected alternatives and why |
| data_confidence | 0 to 100 |
| model_used_heavy | Claude Opus 4.7 Thinking |
| model_used_light | Gemini 3.1 Flash |
| telegram_message | Final message text |
| created_at | timestamp |

### 23.3 Per-Candidate Logs

For each of the top five candidates, store:

| Field | Description |
|---|---|
| ticker | Stock symbol |
| company_name | Company |
| market_cap | Market cap |
| earnings_date | Earnings date |
| direction_classification | Bullish/Bearish/Neutral/Avoid |
| candidate_direction_score | 0 to 100 |
| best_contract_score | 0 to 100 |
| final_opportunity_score | 0 to 100 |
| best_strategy | chosen strategy |
| best_contract | strike + expiry |
| reason_selected_or_rejected | concise explanation |
| data_sources_used | list |
| missing_data_fields | list |

### 23.4 Option Contract Logs

For each seriously considered contract, store:

| Field | Description |
|---|---|
| ticker | Stock symbol |
| option_type | call/put |
| position_side | long/short |
| strike | strike price |
| expiry | expiry date |
| bid | bid price |
| ask | ask price |
| mid | mid price |
| volume | volume |
| open_interest | open interest |
| implied_volatility | IV if available |
| delta | delta if available |
| breakeven | breakeven price |
| spread_percent | spread quality |
| liquidity_score | 0 to 100 |
| contract_score | 0 to 100 |
| passed_hard_filters | true/false |
| rejection_reason | if rejected |

### 23.5 Logging Format

Use structured JSON.

Each run should create:

```text
run_summary.json
candidate_cards.json
option_contracts.json
recommendation_card.json
telegram_message.txt
```

In production, store these in PostgreSQL and optionally archive JSON snapshots to object storage.

### 23.6 V2 Feedback Loop Preparation

V1 should store enough data so that V2 can introduce a Feedback Agent.

V2 Feedback Agent will:

1. Ask user what happened after the recommendation:
   - profit
   - loss
   - still holding
   - did not buy
2. Read the original recommendation card.
3. Compare the original thesis to the actual outcome.
4. Identify whether the issue came from:
   - wrong direction
   - bad expiry
   - bad strike
   - poor IV judgment
   - liquidity issue
   - bad news interpretation
   - earnings timing error
   - overconfidence
   - missing data
5. Suggest improvements to scoring and filters.
6. Store lessons for future runs.

V1 only needs to log the data. The improvement loop is V2.

---

## 24. Database Schema

### 24.1 users

| Field | Type |
|---|---|
| id | UUID |
| telegram_chat_id | string |
| account_size | decimal |
| risk_profile | string |
| custom_risk_percent | decimal/null |
| broker | string |
| timezone_label | string |
| timezone_iana | string |
| strategy_permission | string |
| max_contracts | integer |
| max_option_premium | decimal/null |
| openrouter_api_key_encrypted | text |
| alpaca_api_key_encrypted | text/null |
| alpaca_api_secret_encrypted | text/null |
| alpha_vantage_api_key_encrypted | text/null |
| is_active | boolean |
| created_at | timestamp |
| updated_at | timestamp |

### 24.2 cron_jobs

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| day_of_week | string |
| local_time | string |
| timezone_label | string |
| timezone_iana | string |
| is_active | boolean |
| created_at | timestamp |
| updated_at | timestamp |

### 24.3 workflow_runs

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| trigger_type | cron/manual |
| status | running/success/failed/no_trade |
| started_at | timestamp |
| finished_at | timestamp |
| tradingview_status | success/failed |
| selected_candidate_count | integer |
| final_recommendation_id | UUID/null |
| error_message | text/null |

### 24.4 candidates

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
| direction_classification | string |
| candidate_direction_score | integer |
| best_strategy | string/null |
| final_opportunity_score | integer |
| data_confidence_score | integer |
| selected_for_final | boolean |
| created_at | timestamp |

### 24.5 option_contracts

| Field | Type |
|---|---|
| id | UUID |
| candidate_id | UUID |
| ticker | string |
| option_type | call/put |
| position_side | long/short |
| strike | decimal |
| expiry | date |
| bid | decimal |
| ask | decimal |
| mid | decimal |
| volume | integer/null |
| open_interest | integer/null |
| implied_volatility | decimal/null |
| delta | decimal/null |
| breakeven | decimal |
| spread_percent | decimal |
| liquidity_score | integer |
| contract_opportunity_score | integer |
| passed_hard_filters | boolean |
| rejection_reason | text/null |
| created_at | timestamp |

### 24.6 recommendations

| Field | Type |
|---|---|
| id | UUID |
| user_id | UUID |
| run_id | UUID |
| ticker | string |
| company_name | string |
| strategy | string |
| option_type | call/put |
| position_side | long/short |
| strike | decimal |
| expiry | date |
| suggested_entry | decimal/null |
| suggested_quantity | integer |
| estimated_max_loss | text |
| account_risk_percent | decimal |
| confidence_score | integer |
| risk_level | string |
| reasoning_summary | text |
| key_evidence_json | jsonb |
| key_concerns_json | jsonb |
| telegram_message_id | string/null |
| created_at | timestamp |

### 24.7 feedback_events

This table is mostly for V2, but V1 can already create simple feedback records.

| Field | Type |
|---|---|
| id | UUID |
| recommendation_id | UUID |
| user_id | UUID |
| user_action | bought/skipped/still_holding/closed |
| entry_price | decimal/null |
| exit_price | decimal/null |
| pnl | decimal/null |
| note | text/null |
| created_at | timestamp |

---

## 25. Backend Architecture

### 25.1 Suggested Stack

| Layer | Recommendation |
|---|---|
| Language | Python |
| Backend API | FastAPI |
| Browser automation | Playwright |
| Scheduler | APScheduler or Celery Beat |
| Database | PostgreSQL |
| Cache | Redis |
| Telegram bot | python-telegram-bot or aiogram |
| Data analysis | pandas, numpy |
| Market data | Alpaca for options, yfinance for fallback/market data, Alpha Vantage optional |
| LLM routing | OpenRouter |
| Deployment | VPS |
| Logging | JSON structured logs + database records |

### 25.2 Service Components

| Component | Responsibility |
|---|---|
| Telegram Bot Service | User interaction |
| Schedule Service | Cron management |
| TradingView Browser Service | Screener interaction |
| Candidate Service | Top-five extraction and validation |
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

### 26.1 TradingView Failure

If TradingView cannot be accessed:

1. Retry browser session.
2. Try a clean browser context.
3. Try backup earnings calendar.
4. Notify user if TradingView failed.
5. Continue only if backup candidates are usable.

Telegram message example:

```text
⚠️ TradingView did not load correctly, so I used backup earnings data for this scan.
```

### 26.2 Option Chain Failure

If Alpaca option-chain data is unavailable for a candidate:

1. retry Alpaca once
2. try yfinance fallback
3. try same-day cached data if available
4. mark the candidate as unusable only if no usable option-chain data remains

If option chain is unavailable after all fallbacks:

- mark the candidate as unusable for final recommendation
- continue with other candidates
- log the failure
- do not invent contracts

### 26.3 Missing Data

If non-critical data is missing:

- continue
- apply data confidence penalty
- mention missing data in logs

If critical data is missing:

- reject the candidate or contract

Critical data:

| Field | Critical? |
|---|---:|
| Ticker | Yes |
| Earnings date | Yes |
| Current stock price | Yes |
| Option expiry | Yes |
| Option strike | Yes |
| Bid/ask or usable mid price | Yes |
| Position side | Yes |
| Option type | Yes |
| User account size | Yes |
| User risk profile | Yes |
| OpenRouter API key | Yes |
| News summary | No |
| Greeks | No |
| IV | Preferred but not always critical |
| Volume/open interest | Preferred, but one usable liquidity signal is required |

---

## 27. Data Confidence System

### 27.1 Purpose

Data confidence should help the agent make better decisions without killing too many opportunities.

The system should not say:

```text
Missing one non-critical field = no trade
```

Instead, it should say:

```text
Which data is missing?
How important is it?
Can another source confirm it?
Should this reduce confidence or block the trade?
```

### 27.2 Data Confidence Score

Score range:

```text
0 to 100
```

Suggested components:

| Component | Weight | Description |
|---|---:|---|
| Candidate identity confidence | 15 | Ticker/company match across sources |
| Earnings date confidence | 20 | Earnings date confirmed or conflicting |
| Market data freshness | 15 | Current price and candles are fresh |
| Options data completeness | 20 | Bid/ask, expiry, strike, volume/OI, IV if available |
| Cross-source agreement | 10 | TradingView vs backup sources agree |
| News/context availability | 10 | Recent relevant news available |
| Calculation integrity | 10 | Breakeven, spread, sizing, scores calculated successfully |

### 27.3 Data Confidence Interpretation

| Score | Meaning | Action |
|---|---|---|
| 85 to 100 | Strong data | Recommendation allowed |
| 70 to 84 | Good data | Recommendation allowed |
| 55 to 69 | Partial data | Recommendation allowed only if setup is strong |
| 40 to 54 | Weak data | Watchlist only unless user manually overrides |
| Below 40 | Critical weakness | No recommendation |

### 27.4 Critical Field Override

Even if the data confidence score is numerically above 40, the system must block the recommendation if any critical field is missing.

Critical blocking fields:

- ticker
- verified earnings date
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

Missing Greeks should not automatically block a recommendation.

If delta, IV, or theta are unavailable:

1. approximate moneyness using stock price and strike
2. use premium as percentage of stock price
3. use expected move from available option prices if possible
4. reduce confidence
5. log the limitation

### 27.6 Source Conflict Rule

If sources disagree:

| Conflict | Action |
|---|---|
| Slight price difference | Use most recent source |
| Different earnings date | Verify with additional source |
| Different market cap | Use TradingView for ranking, backup source for context |
| Different option chain values | Use most recent option-chain source |
| Severe conflict | Downgrade confidence or no trade |

### 27.7 Data Confidence in Telegram

Do not overload the main message with data confidence details unless there is an issue.

Good format:

```text
Data confidence: Good
```

If confidence is weak:

```text
⚠️ Data confidence is partial because Greeks were unavailable and earnings timing could not be confirmed.
```

---

## 28. Acceptance Criteria

### 28.1 Workflow Acceptance Criteria

The workflow passes if:

- the scheduled scan runs at the correct user timezone
- manual scan can be triggered from Telegram
- TradingView screener opens successfully
- the earnings filter is applied
- the table is sorted by market cap descending
- top five companies are extracted
- option chains are retrieved or failure is logged
- one recommendation or no-trade result is produced
- Telegram message is delivered
- recommendation card is stored

### 28.2 Recommendation Acceptance Criteria

Each recommendation must include:

- ticker
- company name
- earnings date
- direction
- strategy type
- long or short position side
- option type
- strike
- expiry
- suggested entry
- suggested quantity
- estimated max loss or margin-dependent label
- confidence score
- short reasoning
- key evidence
- Telegram buttons for details and logs

### 28.3 Schedule Acceptance Criteria

The user must be able to:

- view all cron jobs
- add a new cron job
- edit an existing cron job
- delete a cron job
- pause cron jobs
- resume cron jobs
- run scan manually outside cron schedule

### 28.4 Logging Acceptance Criteria

For every run, the system must store:

- run summary
- top-five candidates
- candidate scores
- considered option contracts
- final recommendation
- no-trade reason if no trade
- model used
- data confidence score
- Telegram message text

---

## 29. MVP Scope

### 29.1 V1 Must Include

- Telegram bot onboarding
- user settings
- OpenRouter API key storage
- Alpaca API key and secret storage
- optional Alpha Vantage key storage
- TradingView browser automation
- earnings next-week filter
- market-cap descending sort
- top-five candidate selection
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
- recommendation message
- no-trade message
- recommendation logs

### 29.2 V1 Should Not Include

- broker connection
- automatic trading
- payment system
- public user management
- web dashboard
- complex multi-leg strategies
- automatic feedback optimization
- full backtesting engine

---

## 30. V2 Scope

V2 should add:

- feedback agent
- result-checking workflow
- user outcome collection
- trade result analysis
- performance dashboard
- scoring improvement suggestions
- automated detection of repeated mistakes
- weekly performance summary
- multi-leg options strategies
- better options data provider
- historical backtesting
- strategy comparison
- ticker-specific memory

### 30.1 V2 Feedback Agent

The Feedback Agent should ask users after the earnings event:

```text
How did the previous recommendation go?
```

Button options:

```text
✅ Profit
❌ Loss
⏳ Still holding
🚫 Did not buy
📝 Add note
```

Then the Feedback Agent reads the original log card and identifies possible improvement areas.

Possible bug categories:

- direction was wrong
- expiry was too short
- expiry was too long
- strike was too aggressive
- premium was too expensive
- IV crush was underestimated
- liquidity was poor
- news interpretation was weak
- earnings timing was wrong
- confidence score was too high
- data confidence was too low
- user settings caused poor sizing

The Feedback Agent should not directly change production scoring automatically in V2. It should propose changes for review.

---

## 31. Suggested Development Phases

### Phase 1: Telegram and Settings

Build:

- Telegram bot
- onboarding
- settings screens
- API key storage
- timezone selection
- risk profile selection
- strategy permission setting
- cron job UI

### Phase 2: TradingView Candidate Extraction

Build:

- Playwright browser automation
- TradingView screener opening
- earnings next-week filter
- market-cap descending sort
- top-five extraction
- fallback extraction from screenshot if needed

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

```text
Monday 10:30 AM Montreal time
```

Bot:

```text
📊 Weekly scan is ready.

I checked the top 5 large-cap companies reporting earnings next week and found one setup that looks stronger than the rest.
```

Then sends the recommendation card.

### 32.2 Manual Run

User taps:

```text
🚀 Run Scan Now
```

Bot:

```text
🧠 Starting a fresh earnings-options scan now.
```

After the workflow finishes:

```text
✅ Scan complete. Here is the strongest setup I found.
```

### 32.3 No Trade

Bot:

```text
📊 Scan complete.

No trade looks strong enough this time. The best setups had either weak direction, poor option pricing, or not enough data confidence.
```

Then shows top watchlist names.

---

## 33. Build Priorities

The most important parts to build correctly are:

1. TradingView extraction
2. option-chain retrieval
3. expiry logic around earnings date
4. long vs short option selection
5. scoring system
6. data confidence scoring
7. Telegram UX
8. logging system

The least important parts for V1 are:

1. beautiful dashboards
2. complex analytics
3. backtesting
4. multi-leg options
5. broker integration

---

## 34. Definition of Done for V1

V1 is complete when:

- a user can onboard from Telegram
- a user can set account size, timezone, risk profile, and API key
- a user can manage cron jobs from Telegram buttons
- the default Monday 10:30 AM Montreal schedule works
- the user can manually run the workflow
- the agent opens TradingView Screener
- the agent selects top five next-week earnings stocks by market cap
- the agent retrieves option-chain data from Alpaca first, with yfinance fallback
- the agent uses Gemini 3.1 Flash for light research
- the agent uses Claude Opus 4.7 Thinking for final analysis
- the agent supports long calls, long puts, short puts, and short calls
- the agent sends one recommendation or no-trade message
- the recommendation includes contract details and reasoning
- the system stores a complete recommendation card and evidence log
