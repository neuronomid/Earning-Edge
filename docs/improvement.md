# Earning Edge — Improvement Plan

**Source:** Scholastic-consensus review by 6 Opus 4.7 agents, synthesised by the
review chair (Opus 4.7, thinking hard). Each agent investigated one slice of
the system, read the actual code, and proposed best-practice fixes with
citations. The chair reconciled findings: items agreed on by ≥3 agents are
"strong consensus"; single-agent findings are surfaced only when severity is
high enough to merit it.

**Guiding principle from the user:** keep what works very well, repair only
what is shady or under-specified, do not damage the current system in pursuit
of unproven improvements.

**Status:** This is a recommendations document. No code has been changed.

---

## TL;DR — chair's synthesis

The system has a strong **engineering** foundation (Decimal hygiene, frozen
dataclasses, pure-function scoring, clean fallback ladders, alert-only stops,
honest watch-only degradation) and a weaker **product** foundation (the two
strategies do not measure what their names claim; the earnings-options thesis
ignores IV-rank, straddle-implied expected move, and gap risk; short-premium
strategies are half-implemented).

The single biggest leverage is **fixing the candidate funnel first** (Strategy
A & B), because every downstream score, target, and stop is computed on
whatever survives that funnel. The second-biggest leverage is making **IV /
expected-move** a first-class signal end-to-end (it is currently absent from
direction, target, stop, and sizing).

Three findings are likely **bugs**, not design choices:

1. Strategy B candidates get a **fake "today" earnings date** because no
   coiled-only candidate carries a real one (`orchestrator.py:300`), silently
   mis-scoring expiry and vetoes for every Strategy B candidate.
2. **Short-premium strategies receive `None` for both target sell price and
   stop loss** (`exit_target.py:28-29`); the Telegram template silently omits
   those lines.
3. **`custom_risk_percent` is unbounded** (`Numeric(5,4)` allows up to 9.99 =
   999% risk); a user typo could produce a runaway sizing.

The rest of the report is "design needs work" — not "code is broken".

---

## A. Keep as-is (working well — do not touch)

Items here had agreement from multiple agents that the implementation is
sound, defensible, and likely to be made *worse* by changes.

### A1. Engineering hygiene (strong consensus)
- **Decimal-only money math** end to end (sizing, scoring, exit-target). No
  float drift. Confirmed in sizing (`HUNDRED`, `ZERO` Decimals), scoring
  (`combine_scores`), and exit-target (every result `.quantize(Decimal("0.01"))`).
- **Frozen dataclasses + pure-function scoring.** `CandidateContext`,
  `PipelineCandidate`, `PipelineOutcome`, `ExitTarget`, `SizingResult`. Easy to
  test, no hidden state.
- **Async everywhere; `asyncio.gather` fan-out.** No blocking I/O in pipeline
  steps.
- **Typed error model with non-aborting degradation.** `SizingError`,
  `SizingPermissionError`, `_fallback_market_snapshot`, `_fallback_news_bundle`,
  `_fallback_sizing`, `FINVIZ_FALLBACK_WARNING`. The pipeline keeps producing
  useful output even when a stage fails. Watch-only is a first-class state.
- **`broker_verification_required` flag on shorts.** Honest epistemic hygiene
  — admits the system doesn't model real margin.

### A2. Strategy A's data pipeline (strong consensus on the *infrastructure*, not the *filter set*)
- **Finviz retry/clean-context ladder** in `app/services/finviz/browser.py:42-82`
  matches the AGENTS.md spec exactly: retry page → retry with fresh context →
  fall back to backup sources. Stateless, no login persistence.
- **Reconciler consensus rule** (`reconciler.py:87-109`): "two sources agree =
  verified" with Counter-based vote. Sane and preserves Finviz primacy.
- **Shared Finviz infra** (runner, cache, browser, `Semaphore(2)`) reused
  across A and B via the singleton in `multi_strategy_service.py:184-204`.
- **Failure isolation between A and B** via `asyncio.gather(...,
  return_exceptions=True)` plus the disambiguating warning text constants
  (`COILED_FAILED_WARNING`, `CATALYST_ONLY_WARNING`, `COILED_ONLY_WARNING`,
  `BOTH_FAILED_WARNING`).
- **Cache key determinism** in `query.py:43` (sorted filters, includes `view`).

### A3. Scoring math architecture (strong consensus)
- **Hard vetoes truly zero the contract score** (`contract.py:92`). A vetoed
  contract cannot win.
- **Confidence is separated from score** at the finalist sort
  (`orchestrator.py:741-754`) and the action gate (`final.py:106`): a
  confidence < 40 forces `no_trade` regardless of how high the final score is.
- **PRD-anchored blend weights.** `0.45 * direction + 0.55 * contract` is
  explicitly mandated by `PRD2.md:762` and `Plan1.md:451`. **Defensible by
  spec — leave the weights alone unless the PRD is revised.** (Caveat in §B.)
- **Test surface** (`tests/test_scoring_engine.py`) covers golden tables,
  veto matrix, penalty stacking, confidence override, end-to-end selection.

### A4. Sizing engineering (strong consensus)
- **Clean fallback ladder.** Errors are caught at exactly two sites
  (`orchestrator.py:338`, `scoring/contract.py:250`) and degrade to
  watch-only. The pipeline does not crash because sizing failed.
- **`Decimal(str(user.account_size))` rebuilt at the orchestrator boundary**
  (`orchestrator.py:628`). No float coercion in the sizing path.
- **`//` floor-division for contract count.** Risk-conservative; correct.
- **Test coverage reproduces PRD §9.2 example** and parameterises the three
  risk profiles for `short_put`.

### A5. Target & stop architecture (strong consensus)
- **Greek Taylor expansion for long targets** (`exit_target.py:74-82`).
  Properly signed delta (works for puts), gamma curvature, theta on planned
  holding days, vega coupled to an explicit `expected_iv_change`. PRD §20.5
  endorses this. **Genuinely best-in-class for a deterministic engine — do
  not rip out.**
- **Deterministic fallback ladder** for target (`full_greeks → delta_fallback
  → intrinsic_fallback`) with `target_method` recorded for audit. Clean.
- **Alert-only stops, not broker orders** (`positions/monitor.py:314-327`).
  Correct, because retail brokers do not reliably trigger stop-loss orders on
  long options intraday.
- **Alert hysteresis** (`monitor.py:351-356`): requires re-crossing from above
  before re-firing. Good.
- **`exit_by_date`** capped at `expiry - 5 days` and pulled in to earnings
  date when the window crosses earnings.

---

## B. Needs improvement, ranked by severity

Severity scale:
- **CRITICAL**: behaviour likely incorrect or actively dangerous; user could
  reasonably interpret the output in a way that loses real money.
- **HIGH**: structural design gap; the product claim does not match the
  implementation.
- **MEDIUM**: defensible but undocumented / under-specified / brittle.
- **LOW**: polish, observability, code hygiene.

### B1. CRITICAL — Strategy B fabricates an earnings date (likely latent bug)
- **Where:** `app/pipeline/orchestrator.py:300` does
  `record.earnings_date or datetime.now(timezone.utc).date()`. Coiled-only
  candidates (Strategy B) have no earnings date in the spec, so they enter
  scoring with **today** as their catalyst date.
- **Downstream impact:** `is_valid_expiry` (`scoring/expiry.py:9-16`),
  vetoes (`scoring/vetoes.py:30`), penalties (`scoring/penalties.py:119`),
  and the exit-target's earnings-window logic all use that fake date. Strategy
  B candidates get expiry windows anchored to *today*, and the "trade crosses
  earnings" haircut/IV-crush logic may fire incorrectly.
- **Recommendation (chair):** treat as a bug. Thread `Optional[date]` through
  `CandidateContext.earnings_date` and short-circuit the earnings-dependent
  logic when `strategy_source == "coiled_setup"` and no real date exists.
  Alternatively, require Strategy B candidates to pass through the
  backup-earnings reconciler and drop rows without a real date.
- **Consensus:** Strategy B agent (high confidence, code-traced).

### B2. CRITICAL — Short-premium has no target and no stop
- **Where:**
  - Target: `exit_target.py:28-29` short-circuits to `None` for
    `position_side != "long"`.
  - Stop: same file, lines 102-105 only run after the long-only guard above.
  - Telegram renderer at `main_recommendation.py:66-73` simply omits both
    lines when they are `None`.
- **Downstream impact:** A user with `long_and_short` or `short_only`
  permission can receive a recommendation for a `short_put` or naked
  `short_call` with **no target, no stop, and no programmatic loss cut at
  all**. For naked short call this is unbounded loss.
- **Recommendation (chair):**
  - Implement Tastytrade canon for short_put: target = `entry_credit × 0.50`
    (close at 50% of max profit), stop = exit when loss reaches `2× credit
    received`.
  - **Gate naked `short_call` to `watch_only=True` unconditionally** until a
    real margin/buying-power estimator exists. Sizing for short_call already
    admits "Undefined" — that is a tell that the strategy should not produce
    actionable recommendations yet.
- **Consensus:** Target, stop, and sizing agents independently flagged
  short-premium gaps. Strong consensus.

### B3. CRITICAL — `custom_risk_percent` is unbounded
- **Where:** `Numeric(5,4)` column accepts values up to 9.9999. The only
  check is `> 0`.
- **Downstream impact:** A typo (entering "50" meaning 50% but treated as
  5000%) could allocate 50× the intended capital. The sizing math itself
  trusts the input.
- **Recommendation (chair):** clamp at the user_service ingestion layer
  (reject or coerce to ≤ 5–10%). Display the cap to the user. This is a
  one-line input-validation fix.
- **Consensus:** Sizing agent (single, but unambiguous code finding).

### B4. HIGH — Strategy A is misnamed; the "confluence" never happens
- **Where:** `app/services/finviz/strategies.py:5-11`. The query is just
  `("earningsdate_nextweek", "geo_usa")` sorted by `-marketcap`, top 5. PRD
  §5.2 mandates ~15 filters including `cap_midover`, `fa_epsqoq_pos`,
  `fa_epssurprise_pos`, `an_recom_buybetter`, `targetprice_above`, multiple
  SMA conditions, `sh_relvol_o1.5`, and `ta_rsi_50to70`, sorted by
  `-relativevolume`.
- **Why it matters:** "Catalyst Confluence" implies multiple corroborating
  catalysts; the code measures one (next-week earnings) plus a geography
  filter. The selection bias (top-5 by market cap) systematically returns the
  same megacaps every earnings season, which the post-earnings-drift
  literature suggests is *the least* edge-rich slice.
- **Recommendation (chair):**
  1. Add `earningsdate_thisweek` to `STRATEGY_A_EARNINGS_VALUES` (currently a
     1-tuple that makes the swap mechanism dead code). 2-line change.
  2. Implement **graded filter fallback**: try the full PRD §5.2 filter set
     first; on empty result, relax one tier at a time (drop `sh_relvol_o1.5`,
     then `fa_epssurprise_pos`, then `an_recom_buybetter`) before falling
     back to the current minimal net.
  3. Replace top-5-by-marketcap with `cap_midover` floor + `-relativevolume`
     sort to push toward mid-caps where earnings effects concentrate.
- **Open question for the user:** was the PRD §5.2 filter set abandoned
  deliberately (e.g. Finviz free-tier returned empty) or did it drift? The
  chair recommends checking telemetry on the full-filter URL's row count
  before deciding.
- **Consensus:** Strategy A agent (high confidence, code & PRD-cross-referenced).

### B5. HIGH — Strategy B is misnamed; nothing "coiled" is measured
- **Where:** `strategies.py:18-37`. Filters are SMA50/SMA200/52w-high-band,
  RSI 40-70, beta > 1, $20 floor, sort `-relativevolume`. Zero compression
  measurement (no ATR percentile, no Bollinger width, no Keltner squeeze, no
  IV-rank, no NR7). PRD `docs/PRD1.md:140-151,674-676` mandates
  `ta_pattern_channelup2`, `ta_pattern_triangleascending`, **`ta_volatility_wo4`**
  (weekly vol < 4% — the only true compression filter), and sort `-perfhalf`.
  Commit `361c4fc` stripped every compression filter.
- **Why it matters:** "Coiled Setup" implies volatility compression with a
  pending expansion. The current implementation is a vanilla "uptrend + RSI
  in range + high relvol" screen. The product claim does not match the
  implementation.
- **Recommendation (chair):**
  1. Restore `ta_volatility_wo4` at minimum, or
  2. Compute compression in the scoring layer using daily OHLC (ATR-percentile
     or BB-width-percentile against trailing 60 days). This is more durable
     than relying on Finviz pattern filters.
  3. Add IV-rank gating: long premium when IV-rank is low pre-event, short
     premium when IV-rank is high.
  4. Remove the dead 1-tuple variant swap (`STRATEGY_B_VARIANT_VALUES`) or
     restore the two pattern variants the PRD specifies.
- **Consensus:** Strategy B agent (high confidence, code & PRD-cross-referenced,
  with commit history).

### B6. HIGH — IV-rank and straddle-implied expected move are absent end-to-end
- **Where:**
  - `CandidateContext.expected_move_percent` defaults to `None` and is **never
    populated** at the orchestrator (`orchestrator.py:297-310`).
  - `exit_target.py:135-146` has a "prefer EM, fallback to IV·√(dte/365)"
    branch, but because EM is never set, the fallback always runs.
  - No code anywhere computes the dealer-standard straddle proxy
    (`(call_mid + put_mid)_ATM_front_expiry × 0.85`) despite the option chain
    already being pulled.
  - IV-rank / IV-percentile is not consulted in direction, strategy selection,
    sizing, target, or stop.
- **Why it matters:** This is the central axis of any earnings-options
  product. Tastytrade's entire framework, ORATS' earnings tools, and the
  academic IV-ramp/IV-crush literature all hang on these two numbers. A
  system that ignores them is leaving most of the available edge on the table
  and is exposed to IV-crush losses it cannot model.
- **Recommendation (chair):**
  1. Compute and populate `expected_move_percent` from the ATM straddle in
     `app/services/options/` before scoring runs.
  2. Compute IV-rank against trailing 30/60/252-day IV history.
  3. Use IV-rank to gate strategy selection (low IVR → long premium, high
     IVR → short premium or debit-spread preference).
  4. Scale target prices by EM, not by a fixed conviction factor.
  5. Scale stops by IV (a 100% IV name should not have the same 50%-of-debit
     stop as a 25% IV name).
- **Consensus:** Strategy A, Strategy B, scoring, target, and stop agents
  all independently raised this. Strongest consensus in the review.

### B7. HIGH — Earnings gap-risk is never disclosed to the user
- **Where:** Telegram template `main_recommendation.py:70-73` renders
  "🛑 Stop loss: $X.XX" as a price with no rule explanation. Nowhere in the
  customer-facing message does the bot warn that an overnight earnings gap
  can blow through the stop before it triggers.
- **Why it matters:** This is an earnings-only bot. The very event that
  creates the opportunity (the print) also creates the gap risk that defeats
  a premium-based stop. The user could reasonably submit a broker stop on a
  $1.30 option and get filled at $0.10 on a wide overnight spread.
- **Recommendation (chair):**
  1. Add one line to the template: "Mental alert only — not a broker order.
     An earnings gap can move the option past this stop before you can act."
  2. Consider a `--cut-before-earnings` alternative recommendation (close
     pre-print) for users who want to avoid gap risk entirely.
  3. Long-term: prefer **debit spreads** for earnings trades to structurally
     cap the loss rather than rely on an unfillable stop.
- **Consensus:** Stop and target agents both flagged this. Strong consensus.

### B8. HIGH — No portfolio-level risk awareness in sizing
- **Where:** `app/services/sizing.py` reads `account_size` and `risk_percent`
  but never queries `OpenPosition` rows (`db/models/open_position.py` exists,
  but is used only by the exit monitor).
- **Why it matters:** A weekly cadence with up-to-30-DTE expiries naturally
  produces overlapping positions. A user at 2% per trade can have four
  concurrent trades = 8% portfolio risk. The PRD intent reads as per-trade,
  not per-portfolio.
- **Recommendation (chair):**
  1. Sum open premium-at-risk across active `OpenPosition` rows for the user.
  2. Cap concurrent open risk at e.g. 6–10% of account_size; reduce or skip
     a new sized recommendation when the cap would be breached.
- **Consensus:** Sizing agent (single, but mechanically clear).

### B9. HIGH — Sizing / stop mismatch (capital efficiency)
- **Where:** `sizing.py:46` budgets for `max_loss_per_contract = ask × 100`
  (full premium loss). `exit_target.py:102` tells the user to cut at 50% of
  premium. The displayed "Estimated max loss" uses the sizing number; the
  displayed "Stop loss" implies a different exit. Two inconsistent risk
  numbers on the same card.
- **Recommendation (chair):**
  - Pick one of:
    - **Option A** (more capital-efficient): size off `0.50 × ask × 100` to
      match the planned cut. The user's displayed `account_risk_percent`
      becomes truthful.
    - **Option B** (more honest about gap risk): keep the 100% sizing but
      label the displayed stop as "intra-day alert; max loss truly is 100% on
      a gap".
  - Whichever you choose, **document it in the PRD**.
- **Consensus:** Stop and sizing agents (independent).

### B10. MEDIUM — Linear blend lets a strong contract paper over no-edge direction
- **Where:** `final.py:21-25`. A neutral direction (`score = 50`, neutral cap
  is 54) plus an excellent contract (`score = 92`) blends to 73 — past the 68
  "recommend" threshold. A neutral edge should not produce a trade.
- **Recommendation (chair):**
  Keep the 0.45/0.55 PRD weights (do not rewrite the blend), but add a hard
  floor: require `direction_score ≥ 55` AND `contract_score ≥ 60` for an
  action of `recommend`. This preserves the PRD spec while closing the
  papering-over loophole.
- **Consensus:** Scoring agent (single, but structurally clear).

### B11. MEDIUM — `MISSING_UNIT = 0.45` silently credits missing direction signals
- **Where:** `direction.py:18,120`. When a signal is missing, the factor
  resolves to 45% of its weight ("tepidly positive"). Multiple missing
  signals stack into "looks bullish" purely from absence.
- **Recommendation (chair):** missing signals should drop the factor toward 0
  (not 0.45). Confidence already separately penalises missing data, so this
  is double-mitigation in the wrong direction.
- **Consensus:** Scoring agent.

### B12. MEDIUM — Magic-number cliffs and missing provenance throughout
- **Examples (with file:line — strong consensus on the pattern):**
  - Scoring: `0.12` bias cutoff, `54` neutral cap, breakeven ratio buckets
    `1.25/1.0/0.85/0.7`, strike-fit delta bands, IV bands `0.40/0.60/0.80`,
    penalty deltas `-3/-5/-8/-10/-12/-15`, confidence weight sum `0.97`.
  - Target: conviction floors `0.40/0.65/1.0`, retention `0.50/0.75`, earnings
    haircut `0.75`.
  - Stop: the `0.50` factor.
  - Sizing: short-notional caps `10/20/35%`.
  - Strategy B: SMA50/200, 52w-high-band 20%, RSI 40-70, beta > 1, $20.
  - Strategy A: top-5 slice, 500ms `wait_for_timeout`, hardcoded UA.
- **Recommendation (chair):**
  - Short-term: add inline comment + provenance for each — even if the
    provenance is "PRD §X" or "Tastytrade canon" or "informal calibration",
    write it down. Drift is the failure mode here.
  - Medium-term: replace discrete cliffs with sigmoids / piecewise-linear
    interpolation so a 0.01 change in IV doesn't move a sub-score by 3 points.
  - Long-term: build a small backtest harness so any future change to a
    magic number is justified by data, not opinion.
- **Consensus:** All 6 agents flagged some version of this. Strongest
  cross-cutting consensus in the review.

### B13. MEDIUM — No slippage / commission buffer in sizing
- For sub-$1 contracts the round-trip $0.65–$1.30 broker fees are 5–10% of
  the premium-at-risk. Currently unmodelled.
- **Recommendation:** `max_loss = ask × 100 + commission_per_contract × 2 +
  slippage_pct × ask × 100`. Configurable defaults.

### B14. MEDIUM — Backup earnings sources are positionally weighted
- `_first_non_none` in the reconciler picks yfinance first when both
  Finnhub and yfinance return values, because yfinance is listed first in
  `get_candidate_service()`. yfinance dates are notoriously noisy; Finnhub
  is the authoritative one.
- **Recommendation:** reorder, or pick by `updated_at`/recency rather than
  position.

### B15. LOW — Polish items
- No jittered backoff between Finviz retries (`browser.py:108` uses a flat
  500ms).
- Hardcoded User-Agent string ("Chrome/124.0.0.0") will drift from real
  Chrome and is an easy bot fingerprint.
- No US-holiday handling in "next week" window.
- No BMO/AMC awareness — earnings timing within the day affects pre-event
  trade design.
- `FinvizScreenerCache` is only wired in the multi-strategy factory, not in
  `get_candidate_service()` solo-mode.
- `account_size` stored plaintext (`db/models/user.py:25`); every other
  money-adjacent secret is Fernet-encrypted.

---

## C. Best-practice references (compiled from agents' citations)

### Earnings options thesis
- Quantpedia — Post-Earnings Announcement Effect:
  https://quantpedia.com/strategies/post-earnings-announcement-effect
- Alpha Architect — New Facts for Post-Earnings Announcement Drift:
  https://alphaarchitect.com/new-facts-for-post-earnings-announcement-drift/
- ORATS University — Volatility around earnings:
  https://orats.com/university/volatility-around-earnings
- Six Figure Investing — Riding the IV Ramp Before Earnings:
  https://www.sixfigureinvesting.com/2013/01/riding-the-iv-ramp-before-amazon-earnings/
- MenthorQ — IV Crush guide:
  https://menthorq.com/guide/iv-crush-understanding-the-earnings-driven-volatility-spike-and-how-to-capitalize-on-it/

### Expected move from straddle
- Options AI — EM = 85% of ATM straddle:
  https://tools.optionsai.com/expected-move
- SpotGamma — Implied Earnings Moves:
  https://spotgamma.com/free-tools/implied-earnings-moves/

### Profit-target & stop management
- Tastytrade — close at % of max profit (50% canon):
  https://support.tastytrade.com/support/s/solutions/articles/43000435423
- Tastytrade Market Measures — IV-Rank-based profit targets:
  https://www.tastytrade.com/shows/market-measures/episodes/iv-rank-based-profit-targets-11-06-2019
- Tastytrade Market Measures — Earnings vs Short Premium:
  https://www.tastytrade.com/shows/market-measures/episodes/earnings-vs-short-premium-01-14-2019
- OptionAlpha — Three Best Option Strategies For Earnings:
  https://optionalpha.com/blog/the-three-best-option-strategies-for-earnings

### Stop-loss reality and gap risk
- Market Rebellion — Options During Earnings:
  https://marketrebellion.com/news/trading-insights/how-to-trade-options-during-earnings-pros-cons-and-strategies/
- Charles Schwab — Trading Options Around Earnings:
  https://www.schwab.com/learn/story/trading-options-around-earnings-announcements
- BrokerChooser — tastytrade stop-loss order type:
  https://brokerchooser.com/invest-long-term/risk-management/stop-loss-order-tastytrade

### Volatility compression (Strategy B)
- TradingView — TTM Squeeze:
  https://www.tradingview.com/support/solutions/43000516806-ttm-squeeze/
- Investopedia — Bollinger Squeeze:
  https://www.investopedia.com/terms/b/bollingerbands.asp
- Pattern site (Bulkowski) — pattern frequency stats:
  http://thepatternsite.com/Patterns.html

### Sizing / portfolio risk
- Tastylive — Buying-Power Reduction framework:
  https://www.tastylive.com/concepts-strategies/portfolio-management
- CBOE — Margin & options strategies:
  https://www.cboe.com/learncenter/margin-options-strategies/
- CME — Option pricing and portfolio risk:
  https://www.cmegroup.com/education/courses/introduction-to-options/option-pricing-and-portfolio-risk.html

### Scoring calibration (long-term)
- FastML — Platt scaling vs isotonic regression:
  https://fastml.com/classifier-calibration-with-platts-scaling-and-isotonic-regression/
- Niculescu-Mizil & Caruana (ICML 2005) — Predicting Good Probabilities:
  https://www.cs.cornell.edu/~alexn/papers/calibration.icml05.crc.rev3.pdf
- S&P — Multi-factor methodology:
  https://www.spglobal.com/spdji/en/documents/methodologies/methodology-sp-quality-value-momentum-multi-factor-indices.pdf

---

## D. Recommended sequencing (chair's view)

Fix-the-bugs first, then the product gaps, then the polish. Each phase ends
with the system in a strictly better state — no half-states.

**Phase 1 — Bugs & safety rails (low risk, high payoff):**
1. B1 fix the fake-earnings-date path for Strategy B (`orchestrator.py:300`).
2. B3 bound `custom_risk_percent` at the user_service layer.
3. B2 gate naked `short_call` to `watch_only=True` until margin estimator
   exists; add Tastytrade-style 50%/2× target/stop for `short_put`.
4. B7 add gap-risk disclosure to the Telegram template.

**Phase 2 — Make IV/EM a first-class signal (the biggest product win):**
5. B6 compute straddle-implied EM from the option chain and populate
   `CandidateContext.expected_move_percent`. Once populated, the
   `_expected_move_fraction` EM-preferred branch starts firing automatically.
6. Compute IV-rank against trailing IV history.
7. Use IV-rank in `strategy_select` to bias long-vs-short premium.

**Phase 3 — Fix the candidate funnel (Strategy A & B match their names):**
8. B4 graded filter fallback for Strategy A; restore `earningsdate_thisweek`
   in the variant swap; consider mid-cap-floor + relvol sort.
9. B5 restore real compression measurement in Strategy B (ATR-percentile or
   BB-width-percentile, or `ta_volatility_wo4`).

**Phase 4 — Math hardening (do not break anything that works):**
10. B10 add direction-and-contract floors for `recommend`, keep the 0.45/0.55
    PRD weights.
11. B11 drop `MISSING_UNIT` to 0 for missing signals.
12. B9 pick one side of the sizing/stop coupling and document it.
13. B8 add portfolio-level open-risk cap.
14. B12 short-term: add inline provenance comments. Replace step thresholds
    with sigmoids where a single test confirms behaviour is identical at
    knot points.

**Phase 5 — Polish & calibration:**
15. B13 slippage/commission buffer.
16. B14 reorder backup sources.
17. B15 jittered backoff, UA rotation, holiday calendar, BMO/AMC, solo-mode
    caching, encrypt `account_size`.
18. Build the backtest harness needed to justify any future change to a
    magic number.

---

## E. Open questions for the user

These are decisions the chair could not make without you:

1. **Is the simplified Strategy A URL deliberate?** Did the PRD §5.2 full
   filter set get abandoned because Finviz free-tier returned empty, or did
   it drift? Need telemetry on the full-filter URL's row count to decide.
2. **Should the system include debit/credit spreads** (vertical strategies)?
   The current universe is `long_call`, `long_put`, `short_put`, `short_call`
   only. Adding spreads is the structural answer to earnings gap risk, but
   it is a bigger lift.
3. **Cut-before-earnings vs hold-through-earnings**: should the system offer
   a pre-print exit alternative, or stay PRD §27 (always pick post-earnings
   expiry)?
4. **Backtest harness**: many recommendations want empirical validation
   before being adopted. Do you want a small backtest harness built (a few
   days of work) or do you trust Tastytrade / ORATS canon enough to adopt
   the well-cited defaults without one?
5. **Short-strategy stance**: do you actually want the bot to recommend
   `short_call` at all? If not, the right move is to remove it from the
   permission set rather than improve sizing for it.

---

*End of improvement plan.*
