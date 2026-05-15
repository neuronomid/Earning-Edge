# PM 195C Failure Audit And Fix Guide

Date updated: 2026-05-15

This document supersedes the earlier Claude report. Keep the useful parts of
that report, but prioritize the findings and fixes below. The purpose of this
file is not only to explain why the PM recommendation was bad. It is a guide for
the next implementation pass so a future Codex session can read this file and
know exactly what to fix, in what order, and why.

## Executive Verdict

The PM stock idea was not crazy. PM had real momentum, strong Q1 2026
fundamentals, and sector-relative support.

The option recommendation was still not good enough to send as the best live
trade:

- It recommended a near-expiration OTM call with no named near-term catalyst.
- It told the user to exit on Sunday, 2026-05-17, when the U.S. market is closed.
- It presented a structural score as "Confidence: 83/100", which users can
  naturally misread as win probability.
- It let the LLM call a 2026-05-22 option "May 2026" with "~6 months of runway"
  even though the run happened on 2026-05-15 UTC.
- It scored the target against an expiry-horizon expected move, while the exit
  plan used a much shorter holding window.
- It marked news as adequate in the LLM evidence even when the LLM itself said
  "News service unavailable".

If I were the investor, I would not buy this contract. I would treat the PM
equity trend as watchable, not as a clean 7-DTE long-call entry.

## Exact Run Under Review

Primary run matching the user's example:

- Run id: `9b7d22b3-61be-4d63-b090-5c7a72737e9a`
- Run started: `2026-05-15T00:07:05.547314+00:00`
- Run finished: `2026-05-15T00:07:46.312858+00:00`
- Selected ticker: `PM`
- Selected strategy source: `sector_relative_strength`
- Decision engine: `llm`
- Heavy model: `anthropic/claude-opus-4.7`
- Decision action: `recommend`
- Confidence score: `83`
- Risk level: `High`

Selected contract:

```text
PM long call
Strike: 195
Expiry: 2026-05-22
Bid: 1.73
Ask: 1.98
Mid: 1.855
Suggested entry: 1.98
Delta: 0.359
Gamma: 0.0481
Theta: -0.1881
Vega: 0.1062
IV: 0.2735
Volume: 144
Spread: 13.48%
Breakeven: 196.98
Target stock: 197.21
Target option: 4.09
Stop: 0.99
Exit by: 2026-05-17
Expected holding days: 2
Contract score: 89
Final opportunity score: 83
```

Stored PM candidate facts:

```text
Current price: 191.86000061035156
Expected move percent: 0.027889
Direction score: 75
Direction classification: bullish
Data confidence: 94
Event signal: XLP sector +4.4% (4w), stock screen percentile 60%
Market cap: 299030000000
Earnings date: null
Strategy source: sector_relative_strength
```

The LLM reasoning in that run included this materially wrong statement:

```text
The May 2026 195 call gives ~6 months of runway...
```

That is false. At run time, the 2026-05-22 contract had about one week to
expiry, not six months. This is a decisive audit finding.

Related PM runs:

- `e6fce527-656a-4cbb-829a-7976a9e0a9d4`: PM selected with score 76,
  target option 2.46, target stock 194.21, exit 2026-05-17.
- `bb66374f-e08d-4d30-bb07-224f885cdfa0`: same lower target variant.
- `052a51ba-7bd7-4004-a298-de640edf2357`: PM selected with score 83,
  target option 4.09.
- `54574da7-2e80-4362-85bf-36bc365f084d`: LLM blocked due OpenRouter key;
  PM was still the top structural candidate at score 83, but no trade was sent.

These variants matter because the same PM setup changed materially depending on
run timestamp and expected-move calculation.

## PM Market Research Summary

External facts used to validate the setup:

- PM closed at `191.86` on 2026-05-14, up `2.10%`, with a day range of
  `187.63 - 192.92` and a 52-week range of `142.11 - 192.92`.
- PM was at or near an all-time high around the recommendation.
- PM's latest earnings date was 2026-04-22. This was already in the past.
- Q1 2026 adjusted diluted EPS was `1.96`, ahead of the listed `1.83` forecast
  in public summaries.
- PM's official Q1 release showed strong group results, but also U.S. weakness:
  U.S. net revenue down `30.8%` and U.S. SFP shipment volume down `21.2%`.
- StockAnalysis listed average analyst target at `189.78`, slightly below the
  2026-05-14 close.
- NYSE core trading hours are 9:30 a.m. to 4:00 p.m. ET, and 2026-05-17 was a
  Sunday.

Sources:

- PM quote and metrics: https://stockanalysis.com/stocks/pm/
- PMI Q1 2026 release: https://www.pmi.com/investor-relations/press-releases-and-events/press-releases-overview/press-release-details?newsId=29931
- NYSE hours and holidays: https://www.nyse.com/trade/hours-calendars
- Investing.com all-time-high note: https://www.investing.com/news/company-news/philip-morris-stock-hits-alltime-high-of-19157-usd-93CH-4689132

Professional read:

PM was a reasonable sector-relative-strength watchlist candidate. The problem
was not "PM is bad." The problem was that the system transformed a defensive
large-cap momentum setup into a short-dated OTM long-call recommendation without
checking whether the holding-window math, catalyst window, target, and calendar
made sense.

## Trade Math For The Exact PM Run

Using the exact stored values:

```text
Spot: 191.86
Strike: 195
Entry ask: 1.98
Breakeven: 196.98
Target stock: 197.21
IV: 27.35%
Expiry: 2026-05-22
Exit by: 2026-05-17 Sunday
```

Required move:

- To strike: `195 / 191.86 - 1 = 1.64%`
- To breakeven: `196.98 / 191.86 - 1 = 2.67%`
- To stock target: `197.21 / 191.86 - 1 = 2.79%`

Approximate one-trading-day sigma:

```text
191.86 * 0.2735 * sqrt(1 / 252) = about 3.31 dollars
```

Required target move in one trading day:

```text
(197.21 - 191.86) / 3.31 = about 1.6 sigma
```

Rough driftless probability of touching the target by the only realistic
pre-exit trading day is around `11%`. That is not a high-quality "best setup"
recommendation.

Important correction to the earlier Claude report:

- Claude's version used spot around 190 and described the required move as
  roughly 3.8%. The exact stored run used spot 191.86 and a required target move
  around 2.79%.
- Claude described the target as mainly delta fallback. The exact artifact says
  `target_method = full_greeks`. The high target came from a local Greek Taylor
  projection where gamma contributed heavily.

The conclusion is unchanged: this was not a good live recommendation. The
correct reason is more precise: the target might be within the weekly expiry
expected move, but it was not realistic for the actual Sunday exit window and no
fresh catalyst.

## Answers To The User's Three Questions

### 1. Would I take the PM 195C?

No. I would not take this exact contract. I would not listen to the bot's final
recommendation as sent.

PM had trend strength, but the trade was a 7-DTE OTM call with no named catalyst
and a Sunday exit date. That is not the kind of option the system should send as
the best, user-actionable setup.

### 2. Why did the LLM miss Sunday and other simple facts?

Because the LLM was not given the right facts and the validator did not enforce
them.

The decision payload omits:

- reference date/time
- NYSE calendar facts
- DTE
- trading sessions to expiry
- proposed exit date
- whether proposed exit date is tradable
- target stock price
- target option price
- stop loss
- required sigma to target
- probability of touch
- news article count and news failure status

The LLM selected a ticker and a visible contract. The deterministic system then
persisted the target, stop, and Sunday exit plan. The LLM never had to validate
that final plan.

Worse, in the exact PM run, the LLM hallucinated the time horizon and described
the May 22, 2026 contract as having "~6 months of runway." This was possible
because the prompt did not anchor the model to the current date or require it to
compute DTE.

### 3. Does the LLM rerank the top four?

Yes. The deterministic layer ranks candidates and sends only the top finalists
to the LLM. The LLM may choose any visible finalist and any visible viable
contract for that finalist. Validation checks that the chosen ticker and
contract exist, then recomputes/clamps scores.

Relevant flow:

- `app/pipeline/orchestrator.py:_select_decision_finalists`
- `app/pipeline/steps/decide.py:build_decision_input`
- `app/pipeline/steps/decide.py:validate_llm_decision`

In the PM run, the LLM did not meaningfully rerank. PM was already the top
structural candidate, and the LLM rubber-stamped it.

## Root Causes, Prioritized

### P0-1: UTC Date Is Used As The Trading Valuation Date

Location:

- `app/pipeline/orchestrator.py:_analyze_candidate`

Current behavior:

```python
valuation_date = effective_reference_dt.date()
```

This uses UTC date. The PM run finished at `2026-05-15T00:07:46Z`, which was
still the evening of 2026-05-14 in North America and after the 2026-05-14 market
close. The options and stock data were effectively 2026-05-14 data, but the
pipeline treated the valuation date as 2026-05-15.

Why this matters:

- Expiry filtering changes when UTC crosses midnight.
- The front-expiry expected-move calculation can jump to a different expiry.
- Exit-horizon math changes.
- DTE math becomes inconsistent with actual market session data.

Evidence:

- Earlier PM recommendation variants used `expected_move_percent = 0.012250`
  and target option `2.46`.
- Later variants after UTC date rolled used `expected_move_percent = 0.027889`
  and target option `4.09`.

Fix:

- Use NYSE/Eastern session date, not UTC date, for trading calculations.
- Add helper(s) to `app/services/market_hours.py`:
  - `trading_reference_date(reference_dt: datetime) -> date`
  - `is_trading_session(day: date) -> bool`
  - `previous_trading_session(day: date) -> date`
  - `next_trading_session(day: date) -> date`
  - `trading_sessions_between(start: date, end: date) -> tuple[date, ...]`
- Use these helpers in orchestrator, exit target, expected move, position
  monitoring, and tests.
- If a manual scan runs after NYSE close, use the current ET date if the quotes
  are from that session. If quote timestamps prove stale, either block the trade
  or label it after-hours/watchlist only.

Acceptance tests:

- A reference datetime of `2026-05-15T00:07:46Z` must resolve to NYSE trading
  date `2026-05-14`, not `2026-05-15`.
- The PM fixture should not change target from `2.46` to `4.09` only because UTC
  rolled over while the market session did not.

### P0-2: Exit Dates Ignore Market Sessions

Location:

- `app/services/exit_target.py:_planned_holding_days`
- `app/services/exit_target.py:ExitTargetService.build`

Current behavior:

```python
latest_safe_exit = expiry - timedelta(days=5)
exit_by_date = valuation_date + timedelta(days=planned_holding_days)
```

This is calendar arithmetic. It produced `2026-05-17`, a Sunday.

Fix:

- Replace calendar-day exit date construction with NYSE session logic.
- Store both:
  - `expected_holding_calendar_days`
  - `expected_holding_trading_days`
- For long options, `exit_by_date` must always be a tradable session.
- If the computed safe exit rolls to a non-trading day, roll to the previous
  trading session only if that still leaves a meaningful holding window.
- If the previous trading session is the valuation date and the market is closed
  or nearly closed, reject the contract or force watchlist.

Acceptance tests:

- Valuation date Friday 2026-05-15, expiry Friday 2026-05-22 must never produce
  Sunday 2026-05-17 as `exit_by_date`.
- If safe exit rolls back to same day with no actionable trading session left,
  the contract must be rejected.

### P0-3: Expected Move Is Scored Against Expiry, Not Exit Horizon

Location:

- `app/pipeline/orchestrator.py:_expected_move_percent`
- `app/scoring/contract.py:_score_breakeven`
- `app/services/exit_target.py:_expected_move_fraction`

Current behavior:

- Expected move is calculated from the front-expiry straddle.
- Breakeven feasibility compares required move to that expiry move.
- Exit target uses that move, then sets a shorter exit window.

For PM, the system judged the target using an approximate weekly move, then told
the user to exit by Sunday. That is internally inconsistent.

Fix:

Create separate fields:

- `expected_move_to_expiry_percent`
- `expected_move_to_exit_percent`
- `expected_move_source_expiry`
- `trading_days_to_exit`
- `trading_days_to_expiry`

Use `expected_move_to_exit_percent` for:

- target feasibility
- breakeven feasibility
- required sigma
- probability of touch
- hard vetoes
- LLM payload

Keep expiry move for context only.

Acceptance tests:

- PM fixture must calculate the target feasibility over the exit horizon, not
  the expiry horizon.
- A weekly expected move cannot justify a target that must be hit in one
  trading session unless a named catalyst exists.

### P0-4: No Probability/Required-Sigma Gate Exists

Location:

- `app/scoring/vetoes.py`
- `app/scoring/contract.py`

Current hard vetoes cover missing data, bad expiry, quote problems, dead
contracts, extreme spreads, stale contracts, sizing, and strategy permission.

They do not cover:

- target probability of touch
- probability of profit
- required sigma to strike
- required sigma to breakeven
- required sigma to target
- target/horizon mismatch
- no-catalyst weekly lottery risk

Fix:

Add deterministic option reality metrics before final scoring:

```text
required_sigma_to_strike
required_sigma_to_breakeven
required_sigma_to_target
approx_probability_touch_target
approx_probability_expire_itm
spread_cost_percent
theta_cost_to_exit
has_named_catalyst_before_exit
```

Implementation location options:

- New module: `app/scoring/probability.py`
- New dataclass: `OptionRealityCheck`
- Attach to `ContractScoreResult` or expose through a parallel field.

Minimum P0 vetoes:

- `invalid_exit_session`
- `low_pot_no_catalyst`
- `target_unreachable_by_exit`
- `weekly_otm_no_catalyst`
- `breakeven_outside_exit_move`

Suggested thresholds for first implementation:

```text
For long OTM calls/puts without a named catalyst:
- DTE below 10 calendar days: hard veto
- trading days to exit below 3: hard veto unless catalyst before exit
- required_sigma_to_target > 1.00 over exit horizon: hard veto
- approximate target POT < 35%: hard veto
- breakeven outside 1.00 exit-horizon sigma: hard veto or severe penalty

For non-catalyst sector/coiled trades:
- prefer DTE 14-45 calendar days
- target must be inside 0.75-1.00 exit-horizon sigma
- no strong/recommend band if news is unavailable
```

The exact thresholds should be tuned after paper-trade/backtest results, but
the first version must fail closed. No probability gate is worse than a
conservative threshold.

Acceptance test:

- The PM 195C fixture must become `watchlist` or `no_trade`; it must not be a
  live `recommend`.

### P0-5: Non-Catalyst Strategies Can Select Weekly Long Options

Location:

- `app/scoring/strategy_policy.py`
- `app/scoring/expiry.py`
- `app/scoring/strategy_select.py`

Current policy:

```python
NO_EARNINGS_REQUIRED_STRATEGIES = {
    "coiled_setup",
    "sector_relative_strength",
    "activist_13d_followthrough",
}
```

That part is correct. These strategies should not require earnings.

The problem is what happens next: once a no-earnings candidate reaches scoring,
it can still receive a high score for a 7-DTE long call. In `score_expiry_fit`,
long options with no earnings receive full strategy preference for `7 <= days <=
30`.

Fix:

Create strategy-specific trade policies.

Suggested structure:

```python
@dataclass(frozen=True)
class StrategyTradePolicy:
    min_dte_calendar: int
    max_dte_calendar: int
    min_trading_days_to_exit: int
    max_required_sigma_to_target: Decimal
    min_target_touch_probability: Decimal
    allow_weeklies_without_named_catalyst: bool
    max_spread_percent: Decimal
    preferred_contract_sides: tuple[Strategy, ...]
```

Initial policy suggestions:

```text
catalyst_confluence:
  DTE: event-timed, normally 3-21 after earnings rules
  Weeklies: allowed only when earnings/date catalyst is in window

pead_continuation:
  DTE: 14-35
  Target horizon: 5-15 trading days
  Must have confirmed earnings-surprise/reaction event

coiled_setup:
  DTE: 14-45
  Weeklies: no, unless new breakout catalyst exists
  Need volume acceleration or volatility contraction evidence

sector_relative_strength:
  DTE: 14-45
  Weeklies: no
  Target horizon: 5-15 trading days
  Prefer ATM/slightly ITM calls, not cheap far OTM calls

activist_13d_followthrough:
  DTE: 14-45
  Weeklies: no
  Must have fresh filing/event signal
```

Acceptance tests:

- A sector-relative-strength PM candidate with 7-DTE OTM long call is rejected.
- A sector-relative-strength candidate with 21-DTE ATM/slightly ITM long call
  can still pass if probability and liquidity are acceptable.

### P0-6: The LLM Does Not See The Final Trade Plan

Location:

- `app/llm/schemas.py`
- `app/pipeline/steps/decide.py:_candidate_bundle`
- `app/pipeline/steps/decide.py:_option_chain_candidate`
- `app/llm/prompts/decide_recommendation.md`

Current `OptionChainCandidate` sent to the LLM includes:

- option type
- position side
- strike
- expiry
- bid/ask/mid
- spread percent
- IV
- delta
- volume
- open interest
- liquidity score
- breakeven

It does not include:

- current/reference date
- DTE
- trading sessions to expiry
- proposed exit date
- whether exit date is a trading session
- target stock
- target option
- stop
- expected holding days
- target method
- required sigma
- probability of touch
- theta cost to exit

Fix:

Extend schemas:

```python
class DecisionInput:
    reference_datetime_et: datetime
    reference_trading_date: date
    next_market_session: date | None
    market_calendar_notes: list[str]
    ...

class OptionChainCandidate:
    ...
    dte_calendar: int
    dte_trading_sessions: int
    proposed_exit_by: date | None
    proposed_exit_is_trading_session: bool | None
    expected_holding_calendar_days: int | None
    expected_holding_trading_days: int | None
    proposed_target_stock: Decimal | None
    proposed_target_option: Decimal | None
    proposed_stop_option: Decimal | None
    target_method: str | None
    required_sigma_to_target: Decimal | None
    required_sigma_to_breakeven: Decimal | None
    approx_probability_touch_target: Decimal | None
    has_named_catalyst_before_exit: bool
    reality_check_flags: list[str]
```

Prompt requirements:

- The LLM must state DTE correctly in its rationale.
- The LLM must refuse or downgrade if the exit date is not a trading session.
- The LLM must refuse or downgrade if `reality_check_flags` contains a P0 flag.
- The LLM must cite required sigma and target probability for any recommend.
- The LLM must not call a contract "long-dated" unless DTE is above a defined
  threshold, e.g. 45 calendar days.

Acceptance tests:

- Decision input JSON for PM includes `reference_trading_date`,
  `proposed_exit_by`, `proposed_exit_is_trading_session`, DTE, target, stop,
  required sigma, and probability fields.
- A mocked LLM that says "6 months of runway" for a 7-DTE option should be
  rejected by validation or the test should prove deterministic checks prevent
  the recommendation before LLM.

### P0-7: News Fallbacks Default To "Adequate"

Location:

- `app/services/news/types.py`
- `app/pipeline/orchestrator.py:_deferred_news_bundle`
- `app/pipeline/orchestrator.py:_fallback_news_bundle`
- `app/services/news/summarizer.py:_failure_brief`

Problem:

`NewsBundle.news_coverage` defaults to `"adequate"`. Fallback/deferred bundles
do not override it. Therefore the LLM can see evidence like:

```text
Data confidence 94, news coverage adequate, not stale
```

while also saying:

```text
News service unavailable
```

That contradiction appeared in the PM recommendation.

Fix:

- Change fallback and deferred news bundles to set `news_coverage="none"`.
- Set `stale_news=True` or a dedicated `news_status="unavailable"` when news
  failed due API/model/search problems.
- If `NewsBrief.key_uncertainty == "news service unavailable"`, force coverage
  to `none` and cap recommendation for non-catalyst strategies.
- Include article count, source count, and failure reason in LLM payload.

Acceptance tests:

- `_fallback_news_bundle` returns `news_coverage == "none"`.
- `_deferred_news_bundle` returns `news_coverage == "none"` or a distinct
  `"deferred"` status, not `"adequate"`.
- PM-like non-catalyst candidate with unavailable news cannot be `strong` or
  `recommend` unless deterministic event data is sufficient and probability
  checks pass.

### P0-8: LLM Output Has No Factual-Consistency Validator

Location:

- `app/pipeline/steps/decide.py:validate_llm_decision`

Current validation checks:

- action/band consistency
- chosen ticker exists
- chosen contract exists in visible chain
- LLM cannot inflate numeric score

It does not validate:

- DTE claims in rationale
- "long-dated" vs actual DTE
- "news coverage adequate" vs news failure
- "breakeven inside expected move" against correct horizon
- exit date being tradable
- target/stop realism

Fix:

Prefer deterministic blocking before LLM. But still add final validation:

- If selected contract has any P0 reality flag, force `no_trade`.
- If selected contract has `proposed_exit_is_trading_session=False`, force
  `no_trade`.
- If LLM rationale contains obvious contradictory horizon language, retry once
  with a corrective prompt. If still contradictory, force `no_trade`.
- Better: require the LLM response to include structured fields:
  - `dte_calendar_observed`
  - `exit_date_observed`
  - `target_probability_observed`
  - `primary_rejection_risks`
  Then validate them exactly.

Acceptance tests:

- A mocked LLM response that selects PM and claims "~6 months of runway" must
  not survive validation for a 7-DTE option.

## Secondary Root Causes

### P1-1: "Confidence" Is Not Win Probability

Location:

- `app/scoring/final.py:combine_scores`
- `app/pipeline/orchestrator.py:persist_recommendation`
- `app/telegram/templates/main_recommendation.py`

Current "Confidence" is structural opportunity score:

```python
0.45 * direction_score + 0.55 * contract_score
```

It is not:

- probability of profit
- probability of target
- expected value
- LLM confidence

Fix:

- Rename Telegram field from `Confidence` to `Setup score`.
- Add separate fields:
  - `Estimated target touch chance`
  - `Estimated breakeven chance`
  - `DTE`
  - `Trading sessions to planned exit`
  - `Strategy source`
  - `Catalyst`

Do not show a high 0-100 number next to "High risk" without explaining what it
means.

### P1-2: Risk Level Is Too Crude

Location:

- `app/pipeline/orchestrator.py:_risk_level`

Current behavior:

```python
if short: High
if final_score >= 78: High
else: Moderate
```

This makes PM `High` only because the score was high. Risk should come from
contract risk, not opportunity score.

Fix:

Risk level should consider:

- DTE
- moneyness
- probability of touch
- IV percentile or IV level
- spread
- liquidity
- no-catalyst status
- account sizing
- gap/overnight risk

Suggested labels:

- `Low`, `Moderate`, `High`, `Speculative`

For the PM 195C fixture, risk should be `Speculative` or `High`, and the action
should be `no_trade` or `watchlist`.

### P1-3: Cheap Contracts Can Win Because Better Contracts Exceed Risk Budget

Location:

- `app/scoring/contract.py:_score_premium_fit`
- `app/scoring/vetoes.py:evaluate_hard_vetoes`
- `app/scoring/strike.py:select_strike_candidates`

The PM chain had better, more sensible contracts, but many were rejected because
the account risk budget allowed zero contracts. The system then elevated the
cheaper near-expiry OTM contract.

That is dangerous. If the only affordable contract is structurally poor, the
right output is no trade.

Fix:

- Add a quality floor independent of affordability.
- If all quality contracts exceed risk budget and the remaining affordable
  contracts are low-probability, return `no_trade`.
- Do not let "1 contract fits risk" override target probability.

Acceptance test:

- If a PM-like chain has sensible contracts rejected by risk budget and only a
  7-DTE OTM low-POT call affordable, final action is `no_trade`.

### P1-4: Local Greek Projection Can Overstate Target Option Price

Location:

- `app/services/exit_target.py`

The PM target used full Greeks:

```text
current_mid + delta * move + 0.5 * gamma * move^2 + theta * days + vega * IV_change
```

For PM:

```text
1.855 + 0.359 * 5.35 + 0.5 * 0.0481 * 5.35^2 - 0.1881 * 2 = about 4.09
```

This is a local Taylor approximation. For a large move relative to DTE and an
OTM option moving toward/through the strike, gamma can overstate the realistic
target if used mechanically.

Fix:

- Prefer Black-Scholes/Bjerksund-style repricing when IV, DTE, strike, and spot
  are available.
- Use Greek projection only as fallback.
- Cap target option price against repriced theoretical value plus a conservative
  liquidity/slippage haircut.
- Charge theta over trading sessions to exit, not arbitrary calendar days.
- Make target price primary based on realistic exit-horizon repricing, not
  optimistic local gamma.

Acceptance test:

- PM target projection should be sanity-checked by an option repricer. If the
  target price requires a low-probability target move, reject the contract
  regardless of projected target gain.

### P1-5: "Weekly Earnings Options Signal" Is Wrong For Non-Earnings Strategies

Location:

- `app/telegram/templates/main_recommendation.py`

The PM message title said:

```text
Weekly Earnings Options Signal
```

But PM had:

```text
Earnings date: No earnings catalyst
Strategy source: sector_relative_strength
```

Fix:

- Template title should depend on strategy source.
- Examples:
  - `Earnings Options Signal`
  - `Post-Earnings Drift Options Signal`
  - `Sector Relative Strength Options Signal`
  - `Coiled Setup Options Signal`
  - `Activist 13D Options Signal`
- If no earnings catalyst, do not brand the card as an earnings signal.

### P1-6: Finalist News Refresh Failure Should Cap Or Block

Location:

- `app/pipeline/orchestrator.py:evaluate_batch`
- `app/pipeline/orchestrator.py:_analyze_candidate`
- `app/services/news/summarizer.py`

If finalist news fails, the system should not silently keep a high-confidence
structural trade for non-catalyst setups.

Fix:

- If live finalist news fails:
  - record `news_status="failed"`
  - cap non-catalyst trades at `watchlist`
  - require explicit deterministic event evidence to recommend anyway
- Do not let `DataConfidence` stay 94 when news is unavailable and the LLM
  claims news is a key concern.

## Implementation Plan

Follow this order. Do not start by changing the prompt. Prompt changes are not
enough. The deterministic scoring and validation layer must fail closed before
the LLM is allowed to approve a trade.

### Phase 0: Add Regression Fixtures First

Create a PM fixture from run `9b7d22b3-61be-4d63-b090-5c7a72737e9a`.

Minimum fixture fields:

- reference datetime: `2026-05-15T00:07:46Z`
- expected NYSE trading date: `2026-05-14`
- ticker: `PM`
- spot: `191.86`
- strategy source: `sector_relative_strength`
- earnings date: `None`
- event signal: XLP +4.4%, percentile 60%
- option:
  - 195C
  - expiry 2026-05-22
  - bid 1.73
  - ask 1.98
  - mid 1.855
  - IV 0.2735
  - delta 0.359
  - gamma 0.0481
  - theta -0.1881
  - vega 0.1062
  - volume 144
  - spread 13.48%

Tests to add before implementation:

- `test_trading_reference_date_uses_nyse_date_not_utc`
- `test_exit_target_never_returns_weekend_exit`
- `test_pm_weekly_no_catalyst_contract_is_not_recommendable`
- `test_expected_move_to_exit_is_used_for_target_feasibility`
- `test_fallback_news_bundle_is_not_adequate`
- `test_decision_payload_contains_exit_plan_and_reality_metrics`
- `test_llm_cannot_claim_months_of_runway_for_7_dte_contract`

### Phase 1: Market Calendar And Valuation Date

Files:

- `app/services/market_hours.py`
- `app/pipeline/orchestrator.py`
- `tests/test_market_hours.py`
- `tests/test_pipeline_orchestrator.py`

Steps:

1. Extend `market_hours.py` with session-date helper functions.
2. Replace UTC `.date()` valuation with NYSE-aware trading reference date.
3. Ensure after-hours manual scans do not use tomorrow's UTC date for today's
   market data.
4. Store/log reference datetime ET and reference trading date.

### Phase 2: Exit Date Correctness

Files:

- `app/services/exit_target.py`
- `tests/test_exit_target_service.py`

Steps:

1. Replace `_planned_holding_days` calendar-only logic with session-aware logic.
2. Return/store trading-session count.
3. Reject contracts whose safe exit date is not actionable.
4. Add Sunday/holiday/early-close tests.

### Phase 3: Expected-Move And Probability Reality Checks

Files:

- `app/pipeline/orchestrator.py`
- `app/scoring/probability.py` (new)
- `app/scoring/types.py`
- `app/scoring/contract.py`
- `app/scoring/vetoes.py`
- `tests/test_scoring_engine.py`

Steps:

1. Split expiry expected move from exit-horizon expected move.
2. Add required-sigma and probability metrics.
3. Add hard vetoes for low-probability no-catalyst contracts.
4. Add soft penalties for borderline but not fatal setups.
5. Make PM fixture fail closed.

### Phase 4: Strategy-Specific Contract Policy

Files:

- `app/scoring/strategy_policy.py`
- `app/scoring/expiry.py`
- `app/scoring/strike.py`
- `app/scoring/strategy_select.py`
- `tests/test_scoring_fairness.py`
- `tests/test_scoring_engine.py`

Steps:

1. Add `StrategyTradePolicy`.
2. Apply min/max DTE and no-weekly rules per strategy.
3. Make no-catalyst strategies prefer enough DTE for the thesis to work.
4. Ensure cheap OTM weeklies cannot outrank better but unaffordable contracts.

### Phase 5: Target/Stop Repricing

Files:

- `app/services/exit_target.py`
- `app/scoring/probability.py`
- `docs/gp-target-option.md`
- `docs/final-traget-option.md`
- `tests/test_exit_target_service.py`

Steps:

1. Add a conservative option repricer.
2. Use repricing before local Greek projection when inputs exist.
3. Charge theta over the full planned trading-session holding window.
4. Add slippage/spread haircut to target.
5. Reject targets that cannot pass the probability gate.

### Phase 6: LLM Payload, Prompt, And Validator

Files:

- `app/llm/schemas.py`
- `app/pipeline/steps/decide.py`
- `app/llm/prompts/decide_recommendation.md`
- `tests/test_decision_step.py`

Steps:

1. Add reference date/time and market calendar block to `DecisionInput`.
2. Add proposed exit plan and reality metrics to each visible contract.
3. Update the prompt to require:
   - DTE calculation
   - exit-date validation
   - required-sigma citation
   - probability citation
   - catalyst-window check
   - no recommendation if deterministic reality flags fail
4. Update `validate_llm_decision` to force no-trade if the selected contract has
   P0 reality flags.
5. Add factual-consistency validation for DTE and horizon language.

Prompt note:

The prompt should not say "be smarter" in vague terms. It should force a small
checklist:

```text
Before recommending, verify:
1. Current/reference trading date.
2. DTE and trading sessions to exit.
3. Exit date is a U.S. trading session.
4. Named catalyst exists before exit, or this is explicitly a non-catalyst setup.
5. Required sigma to target and breakeven.
6. Estimated probability of touching target before exit.
7. News status and article count.
8. Contract spread and liquidity.

If any P0 reality flag is present, choose no_trade.
If two or more P1 flags are present, choose watchlist or no_trade.
Do not describe a contract as long-dated unless DTE >= 45.
```

### Phase 7: Telegram UX

Files:

- `app/telegram/templates/main_recommendation.py`
- `app/services/logging_service.py`
- `app/services/results_export_service.py`
- tests for Telegram templates and logging

Steps:

1. Rename `Confidence` to `Setup score`.
2. Add:
   - DTE
   - trading sessions to exit
   - day of week for exit date
   - estimated target touch chance
   - strategy source
   - catalyst status
3. Strategy-specific card title.
4. If exit date is not actionable, never render a buy action.

### Phase 8: Backtest/Paper-Trade Calibration

This system will not become profitable just because the LLM prompt is stronger.
It needs feedback.

Steps:

1. Store every recommendation and rejected finalist with:
   - scores
   - strategy source
   - DTE
   - target probability
   - spread
   - IV
   - target/stop/exit
2. After expiry/exit window, compute:
   - target hit
   - stop hit
   - max favorable excursion
   - max adverse excursion
   - mark-to-market P/L
   - slippage-adjusted P/L
3. Calibrate thresholds by strategy.
4. Treat no-trade as a valid positive system outcome when the best setup is bad.

## File-Level Notes For Future Codex

Read these files first before coding:

```text
app/pipeline/orchestrator.py
app/pipeline/steps/decide.py
app/llm/schemas.py
app/llm/prompts/decide_recommendation.md
app/services/exit_target.py
app/services/market_hours.py
app/scoring/vetoes.py
app/scoring/contract.py
app/scoring/expiry.py
app/scoring/strategy_policy.py
app/scoring/strike.py
app/scoring/final.py
app/scoring/confidence.py
app/telegram/templates/main_recommendation.py
app/services/logging_service.py
```

Do not begin by only editing `decide_recommendation.md`. The PM failure was not
mainly a wording problem. It was a data-contract and deterministic-validation
problem.

The safest implementation order is:

1. Tests and PM fixture.
2. NYSE trading-date and exit-date correctness.
3. Expected-move-to-exit and probability gates.
4. Strategy-specific DTE/no-weekly policies.
5. LLM schema/prompt updates.
6. Telegram wording and logging.

## How The PM Fixture Should Behave After Fixes

For the exact PM 195C fixture:

Expected result:

```text
Action: no_trade or watchlist
Reason:
  - no named catalyst before exit
  - 7-DTE OTM long call
  - target requires too much move for available trading sessions
  - original exit date was non-trading Sunday
  - news status unavailable/contradictory
  - target probability below threshold
```

It must not produce:

```text
Action: recommend
Confidence: 83/100
Exit by: 2026-05-17
Reasoning: "6 months of runway"
```

## What To Keep From Claude's Report

Keep these Claude findings:

- PM was not a good live buy recommendation.
- Sunday exit date is a real bug.
- The LLM does not see the final exit plan.
- The decision prompt is too permissive and action-biased.
- "Confidence" is misleading.
- The LLM can choose among the top four finalists and is not bound to rank #1.
- Non-catalyst strategies are too permissive with weekly long calls.
- Need probability-of-touch/profitability gates.

Adjust these Claude findings:

- The exact PM run used spot `191.86`, not about `190`.
- The exact target move was about `2.79%`, not about `3.8%`.
- The target method in the exact artifact was `full_greeks`, not pure delta
  fallback.
- The biggest additional root cause is UTC date drift changing valuation and
  expected-move behavior.
- Another major root cause is news fallback defaulting to `"adequate"`.
- The LLM's "~6 months of runway" mistake is more severe than just missing a
  Sunday exit.

## Definition Of Done

This issue is not fixed until all of these are true:

- No recommendation can show a weekend or holiday exit date.
- Valuation date uses NYSE/Eastern trading-session logic, not raw UTC date.
- Expected move used for feasibility matches the proposed holding window.
- Long OTM weekly options without a named catalyst fail closed.
- Each strategy has its own DTE and contract policy.
- PM 195C fixture is not recommendable.
- News unavailable cannot appear as "coverage adequate".
- LLM input includes reference date, DTE, target, stop, exit date, probability,
  and reality flags.
- LLM validation can reject obvious factual contradictions.
- Telegram no longer labels structural score as win confidence.
- Telegram title matches the strategy source instead of always saying earnings.

If only the prompt changes, this file should still be considered unresolved.

## Post-PRMB Follow-Up (2026-05-15)

PRMB sector-RS run `919ed48f-cfa7-4eff-b149-f05663ffb656` produced a
watchlist-only output instead of a live recommendation, confirming the P0
fixes landed. Four follow-up issues surfaced during the post-mortem and have
since been resolved on the `codex/dumb` branch.

### Resolved

1. **News pipeline silently failing.** Finnhub + SEC EDGAR were healthy
   (84 articles for PRMB), but `NewsSummarizer.summarize()` was burning the
   completion budget on Gemini 3.1 Pro Preview reasoning tokens, leaving the
   final JSON truncated mid-string and the brief downgraded to
   `key_uncertainty="news service unavailable"`. Fix:
   - `LLMRouter.summarize()` now sends `reasoning={"effort": "low",
     "exclude": True}` and accepts a `response_format` kwarg.
   - `NewsSummarizer` requests `response_format={"type": "json_object"}`,
     runs a primary attempt + retry with a brevity hint, and logs the raw
     response tail + length on failure for easier debugging next time.
   - Added a tolerant JSON repair pass (`_repair_loose_json`) that fixes
     trailing commas and unescaped inner double quotes before falling back to
     `_failure_brief()`.
2. **Negative-EV long-premium contracts (R:R floor).**
   `StrategyTradePolicy.min_long_premium_risk_reward` enforces a 0.80 floor
   on non-catalyst strategies (0.50 for `catalyst_confluence`). Vetoes emit
   `weak_long_risk_reward` whenever target_gain / stop_distance falls below
   the policy floor on a long, non-catalyst contract.
3. **Tradable-but-not-actually-tradable contracts (liquidity floor).**
   `min_volume_non_catalyst_long` / `min_open_interest_non_catalyst_long`
   default to 5 / 10 for non-catalyst strategies and 1 / 1 for catalyst
   confluence. Vetoes emit `thin_liquidity_no_catalyst` when both fall below
   the policy floor on a long, non-catalyst contract.
4. **Catalyst-pending tickers disappearing from the watchlist (Op-3).**
   `CandidateBundle` now carries `tradeable_contracts_available` and
   `catalyst_pending_no_tradeable_contract`. The decide-step prompt asks the
   LLM to surface those tickers on the watchlist, and
   `_augment_with_catalyst_pending` fills empty slots deterministically when
   the LLM forgets.
5. **News-blackout downgrade reason (P2-1).** When the LLM downgrades a
   setup to `watchlist` while `news_status="unavailable"`,
   `validate_llm_decision` injects a canonical
   `"Downgraded to watchlist because news_status=unavailable…"` concern if
   the model did not already cite one.
6. **Tailored corrective prompts (P2-3).** `_targeted_retry_hint`
   detects runway-claim, unknown-contract, and band/action mismatches and
   appends a focused hint to the retry prompt so the heavy model fixes the
   exact mistake instead of guessing.

### Acceptance tests added

- `test_weak_long_risk_reward_vetoes_prmb_like_no_catalyst_contract`
- `test_weak_long_risk_reward_does_not_fire_for_short_premium`
- `test_thin_liquidity_no_catalyst_vetoes_volume_1_long_option`
- `test_thin_liquidity_floor_skipped_when_catalyst_is_pending`
- `test_watchlist_with_news_unavailable_gets_blackout_concern_injected`
- `test_watchlist_with_news_unavailable_preserves_existing_blackout_concern`
- `test_catalyst_pending_no_contract_ticker_lands_on_watchlist`
- `test_bundle_marks_catalyst_pending_no_tradeable_contract`
- `test_corrective_prompt_includes_targeted_hint_for_runway_violation`
- `test_corrective_prompt_includes_targeted_hint_for_unknown_contract`

### Still open

- The optional R:R floor for `catalyst_confluence` (0.50) was chosen as a
  defensive default and has not been backtested. Tune after paper-trade
  feedback.
- LLM still has discretion to choose `watchlist` over `no_trade` when the
  reality flags are borderline. The new structural concern injection is the
  audit trail, not a hard rule — review whether to harden further once we
  collect more decision examples.
