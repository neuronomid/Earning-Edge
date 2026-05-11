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

**User decisions locked in (2026-05-11):**
- **Q1 — Strategy A filter drift:** Not deliberate. Build a system that tries
  the full PRD §5.2 filter set first and **progressively relaxes** filters
  until matches appear. Goal is "best filtered results," not just "any
  results." Concrete relaxation tier proposed in §B4.
- **Q2 — Vertical spreads:** **Not in this version.** Keep on the radar for
  a future release.
- **Q3 — Volatility-ramp (cut-before-earnings):** **Chair recommends
  deferring.** See §E1 for rationale. Decision: drop from this version, keep
  current hold-through architecture.
- **Q4 — Backtest harness:** Use Tastytrade / ORATS canon defaults now. Add
  a structured **outcome log** so future versions can re-tune from data.
  See §B16.
- **Q5 — Naked `short_call`:** Keep as a real recommendation type. Build a
  proper margin estimator, IV-scaled stops, and gap-risk language — do NOT
  gate to watch-only.

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
- **Recommendation (chair) — per user Q5 decision (keep short_call):**
  - **short_put (the easy half):** Implement Tastytrade canon — target =
    `entry_credit × 0.50` (close at 50% of max profit); stop = exit when loss
    reaches `2× credit received`. Both are well-cited industry defaults.
  - **short_call (the hard half) — full build, not watch-only gate:**
    1. **Replace the strike-notional sizing cap** in `sizing.py:64-100` with a
       proper Reg-T-style buying-power estimate: `BPR ≈ max(20% × underlying
       − OTM amount + premium, 10% × strike) × 100`. Reference: CBOE margin
       rules. Until then the system over-sizes naked calls in low-priced
       volatile names.
    2. **IV-scaled stop:** premium-based stops fail catastrophically on
       short calls because the option price can multiply 5×–10× on a gap.
       Use an **underlying-touch stop** (close when underlying breaches the
       short strike or a configurable buffer above it, e.g. strike × 1.02),
       converted into the option-price domain via current delta only for the
       monitor's alert threshold.
    3. **Mandatory gap-risk disclosure** in the Telegram template for
       short_call: "naked short — overnight gap can multiply loss." Plus a
       per-trade max-loss cap derived from the user's account size.
    4. **Conviction floor:** require `direction_score ≥ 65` AND
       `confidence ≥ 60` before a naked short_call can produce a `recommend`
       action (it stays as `watchlist` below those thresholds). The risk
       asymmetry justifies a higher bar than long premium.
    5. **`broker_verification_required = True` stays.** Keep telling the
       user the broker's real margin number may differ.
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
- **Recommendation (chair) — per user Q1 decision (drift, not deliberate):**

  Build a **graded relaxation engine** that runs the full PRD §5.2 filter
  set first and progressively drops filters only when row count falls below
  a target threshold. Each relaxation step is logged and surfaced in the
  Telegram message as a transparency note (e.g. "Used Tier-3 relaxed
  filters — analyst-revision signals dropped").

  **Design principles for the relaxation order** (so we keep the highest-
  signal filters longest):
  - **Never relax** filters that define product eligibility — without these
    we cannot recommend an option at all.
  - **Relax cosmetic technicals first** (narrow-band RSI, short-term SMAs)
    because they exclude many otherwise-good candidates without adding much
    signal.
  - **Relax analyst-revision filters next** — they're directional but soft.
  - **Keep fundamental-surprise filters (`fa_epssurprise_pos`,
    `fa_revenuesurprise_pos`) almost last** — these are the most durable
    edge in the post-earnings-drift literature (Alpha Architect, Quantpedia).
  - **Keep relative-volume last among the "soft" filters** because attention/
    volume is a strong attention proxy around earnings.

  **Proposed tier structure** (run top-down until row count ≥ target, e.g.
  ≥ 5 distinct names, ideally ≥ 10 so re-ranking has room to work):

  | Tier | Drop from previous tier | Rationale |
  |------|-------------------------|-----------|
  | 0 — Full PRD §5.2 | (nothing — start here) | Best case; all 15 filters active |
  | 1 | `ta_rsi_50to70` | Narrow RSI band is the most-restrictive technical |
  | 2 | `ta_sma20_pa` | Short-term trend; SMA50/200 still enforce uptrend |
  | 3 | `ta_perf_qup` | Quarterly performance up — could exclude reversion plays |
  | 4 | `targetprice_above` | Analyst target — soft directional signal |
  | 5 | `an_recom_buybetter` | Analyst recs — soft |
  | 6 | Relax `sh_relvol_o1.5` → `sh_relvol_o1` | Still want above-average attention |
  | 7 | `ta_sma50_pa`, `ta_sma200_pa` | Drop trend confluence — keep fundamentals |
  | 8 | `fa_epsqoq_pos`, `fa_salesqoq_pos` | Drop QoQ growth confluence |
  | 9 — Confluence floor | Keep only: `earningsdate_*`, `geo_usa`, `sh_opt_option`, `sh_price_o20`, `cap_midover`, `fa_epssurprise_pos`, `fa_revenuesurprise_pos`, `sh_avgvol_o1000` | Surprise-history + tradability essentials |
  | 10 — Last resort | Current minimal net: `earningsdate_*`, `geo_usa` | Triggers `FINVIZ_FALLBACK_WARNING`-style transparency note |

  **Never-relax set (eligibility, not preference):**
  `earningsdate_nextweek` OR `earningsdate_thisweek` (need an earnings event);
  `geo_usa` (US-listed); `sh_opt_option` (must have options); `sh_price_o20`
  (avoid penny-stock data noise); `cap_midover` (avoid micro-caps where
  Finviz data quality drops).

  **Additional fixes alongside the tier engine:**
  1. Add `earningsdate_thisweek` to `STRATEGY_A_EARNINGS_VALUES` so the
     variant swap actually runs both windows and dedupes (today it's a
     1-tuple = dead code). Two-line change.
  2. Replace top-5-by-marketcap with `-relativevolume` sort. Mid/large-cap
     stocks with elevated relative volume are the canonical PEAD/IV-ramp
     setup; sorting by raw marketcap just returns the same megacaps every
     week regardless of edge.
  3. Re-rank surviving rows by a composite of (relativevolume, surprise
     history, analyst target delta) before slicing top 5 — that way the
     "best filtered results" survive even when an outer tier relaxed.
  4. Log the active tier per run in `StrategyRunReport` so we can later see
     which tier triggers most often in production.
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
- **Recommendation (chair) — per user Q2/Q3 decisions (no spreads, no
  ramp this version):**
  1. Add one line to the Telegram template: "Mental alert only — not a
     broker order. An earnings gap can move the option past this stop
     before you can act."
  2. Add a separate, stronger line for naked `short_call`: "Naked short
     call — an overnight gap above the strike can multiply your loss.
     Manage actively."
  3. Future versions (deferred per user): debit/credit spreads to floor the
     loss structurally, and a pre-earnings volatility-ramp exit path. Both
     listed in §E2.
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

### B16. NEW — Recommendation outcome log (per user Q4 decision)

User chose to **adopt Tastytrade / ORATS canon defaults now and build a
structured outcome log for future re-tuning** instead of building a full
backtest harness up-front. This is the sensible middle path: ship with
well-cited defaults; capture data; calibrate later.

**Why this fits the existing system:** the database already stores every
`Recommendation` (entry price, target, stop, strategy, IV, expected_move,
chosen contract) and the `positions/monitor.py` service already watches
open positions for target/stop touches. The missing piece is a **post-trade
outcome row** that links each recommendation to its realised result.

**Proposed outcome log (logical columns — not a final schema):**
- `recommendation_id` (FK to existing `recommendations` table)
- `entry_filled_at`, `entry_fill_price` (from user confirmation or
  monitor's first observation)
- `exit_event` ∈ {`hit_target`, `hit_stop`, `time_exit`, `pre_earnings_cut`,
  `expired_worthless`, `expired_itm`, `manual_close`, `unobserved`}
- `exit_at`, `exit_price`
- `realised_pnl_per_contract` (Decimal)
- `realised_pnl_pct` (Decimal — vs entry premium)
- `iv_at_entry`, `iv_at_exit`, `iv_change_pct`
- `actual_underlying_move_pct` (vs entry-day close)
- `expected_move_used` (the EM the system computed at recommend-time)
- `move_realisation_ratio` = `actual_move / expected_move`
- `days_held`
- `strategy_source` (catalyst_confluence vs coiled_setup), `strategy`,
  `confidence`, `final_score`, `direction_score`, `contract_score`

**What this unlocks (without building anything more right now):**
- After a few months of weekly runs you have a flat-file dataset
  (~50–200 trades) sufficient to re-fit the magic numbers in §B12.
- Aggregations by `strategy_source` show whether Strategy A or Strategy B
  actually has edge.
- Aggregations by `iv_rank_bucket × strategy` validate or refute the
  Tastytrade canon defaults in your specific universe.
- Move-realisation-ratio histograms tell you if straddle-implied EM is
  well-calibrated for your candidate pool.

**Effort estimate:** small — one Alembic migration, one new repository, one
new service called from the monitor's exit-detection hook. No code yet (per
user instruction), but worth scoping into Phase 5.

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

## D. Recommended sequencing (chair's view, post-decisions)

Fix-the-bugs first, then the product gaps, then the polish. Each phase ends
with the system in a strictly better state — no half-states. Updated to
reflect the user's Q1–Q5 decisions: short_call gets a real build, no
spreads, no volatility-ramp, canon defaults + outcome log instead of full
backtest harness.

**Phase 1 — Bugs & safety rails (low risk, high payoff):**
1. **B1** fix the fake-earnings-date path for Strategy B
   (`orchestrator.py:300`).
2. **B3** bound `custom_risk_percent` at the user_service ingestion layer
   (cap at e.g. 5–10%).
3. **B2 (easy half)** — add Tastytrade-style targets/stops for `short_put`
   (close at 50% of max profit; stop at 2× credit received).
4. **B7** add gap-risk disclosure lines to the Telegram template (general
   line for longs; stronger naked-short-call-specific line).

**Phase 2 — Make IV/EM a first-class signal (biggest product win):**
5. **B6 (part 1)** compute straddle-implied expected move from the ATM
   front-expiry chain and populate `CandidateContext.expected_move_percent`.
   The dead "EM-preferred" branch in `exit_target.py:135-146` starts firing
   automatically. Single highest-leverage change in the plan.
6. **B6 (part 2)** compute IV-rank against trailing 30/60/252-day IV
   history (per CBOE / Tastytrade methodology).
7. **B6 (part 3)** use IV-rank in `strategy_select` to bias long-vs-short
   premium — low IVR favours long premium, high IVR favours short premium.
8. Scale target prices by EM (replace conviction-scale floors with
   `target = entry + delta × (EM × IVR-bucket-scalar × move-fraction)`).
   Replace fixed 50% stop with IV-scaled stop. Both per the agents' canon
   citations.

**Phase 3 — Fix the candidate funnel (Strategy A & B match their names):**
9. **B4** — implement the graded filter relaxation engine for Strategy A
   per the tier table in §B4. Add `earningsdate_thisweek` to the variant
   swap. Replace `-marketcap` sort with `-relativevolume` + composite
   re-rank (relvol, surprise-history, analyst delta). Log active tier in
   `StrategyRunReport`.
10. **B5** — restore real compression measurement for Strategy B (compute
    ATR-percentile and/or BB-width-percentile from yfinance OHLC in the
    scoring layer; do not rely on Finviz pattern filters). Remove the dead
    1-tuple `STRATEGY_B_VARIANT_VALUES` swap.

**Phase 4 — Math hardening + short_call full build:**
11. **B2 (hard half)** — naked `short_call` real margin estimator
    (`BPR ≈ max(0.20 × underlying − OTM amount + premium, 0.10 × strike) × 100`),
    underlying-touch stop (close on underlying ≥ strike × 1.02 or
    user-configurable buffer), conviction floor (`direction ≥ 65 AND
    confidence ≥ 60` for `recommend`), mandatory gap-risk language.
12. **B10** add direction-and-contract floors for `recommend` (e.g.
    `direction ≥ 55 AND contract ≥ 60`), keep the 0.45/0.55 PRD blend
    weights.
13. **B11** drop `MISSING_UNIT = 0.45` to 0 (missing signals should not
    silently credit).
14. **B9** pick one side of the sizing/stop coupling and document it. The
    chair's recommendation is **Option A** (size off `0.50 × ask × 100` to
    match the planned cut) — that makes the displayed `account_risk_percent`
    truthful for the modal case (longs that hit the stop). The gap-risk
    language in §B7 covers the worst-case (gap-through-stop).
15. **B8** add portfolio-level open-risk cap (sum open premium-at-risk
    across `OpenPosition` rows; cap at 6–10% combined).
16. **B12 (short-term half)** add inline provenance comments to every
    magic number — PRD section, Tastytrade article, or "informal" if
    that's the truth. Replace step thresholds with sigmoids/piecewise
    linear where a single test confirms behaviour is identical at the
    knot points.

**Phase 5 — Outcome log, polish & calibration prep:**
17. **B16** ship the recommendation outcome log (Alembic migration, new
    repository, hook into `positions/monitor.py` exit handlers). One
    schema. No analyzer yet. This is the foundation for future
    data-driven re-tuning.
18. **B13** slippage / commission buffer in sizing.
19. **B14** reorder backup earnings sources (Finnhub before yfinance).
20. **B15** jittered backoff, UA rotation, US-holiday calendar, BMO/AMC
    awareness, solo-mode caching, encrypt `account_size`.

**Out of scope this version (see §E2):** vertical spreads,
volatility-ramp / cut-before-earnings, full backtest harness, calibrated
probability outputs, direction-probability features (skew / OI / gamma).

---

## E. Decisions made + deferred items

### E1. Chair's reasoning on the deferred decisions

**Volatility-ramp (Q3) — chair recommended defer, user accepted.**

The user offered to add the volatility-ramp (cut-before-earnings) path if the
chair recommended it. After weighing the work:
- The Phase 1–4 plan already adds significant new behavior: graded Finviz
  relaxation, IV-rank computation, expected-move population, short_call
  margin estimator, gap-risk UX, sizing/stop reconciliation. That is enough
  net-new surface for one release.
- Volatility-ramp is not just "exit earlier" — it requires a parallel
  decision branch in `decide.py` (ramp vs hold), a separate exit-target
  computation path (target = pre-event premium peak, not post-event move),
  separate Telegram messaging to avoid user confusion, and separate outcome
  tracking. Order-of-magnitude bigger than the Phase 1 bug fixes.
- The Phase 2 work (IV-rank + expected-move) *unlocks* a clean ramp
  implementation later. Deferring does not burn the work — it preserves the
  foundation.
- The user's earnings-options thesis is direction-betting (hold-through);
  volatility-ramp is a different product. Keeping product focus tight on
  one thesis per release reduces test surface and decision fatigue.

**Vertical spreads (Q2) — user deferred to a future version.** Spreads are
the structural answer to gap risk; the gap-risk language added in B7 is the
interim workaround. When spreads ship, B7's "mental alert only" disclosure
gets weaker because the loss is structurally floored.

**Backtest harness (Q4) — user chose canon now, outcome log for later.**
Canon defaults (Tastytrade 50% / 2× rules, ORATS straddle-implied EM,
IV-rank gating) are well-cited and battle-tested. The outcome log (§B16)
captures everything needed to validate them in your specific universe
later, without delaying this release.

### E2. Deferred items (future versions)

These are explicitly out of scope for this version but should not be lost:

1. **Vertical spreads** (debit/credit) as 5th and 6th strategy types.
   Structurally caps loss; preferred for earnings trades in the academic
   and trader-desk literature. Estimated 3–5 days of work when prioritised.
2. **Volatility-ramp / cut-before-earnings** as a parallel recommendation
   mode. Most cleanly built after IV-rank and EM are in (Phase 2 here).
3. **Full backtest harness.** Once the outcome log (§B16) has 3–6 months
   of data, build a runner that re-simulates the pipeline against history
   and re-fits the magic numbers in §B12.
4. **Calibrated probability output** (isotonic regression on
   direction-score → realised-PnL-sign). Requires the backtest harness.
5. **Direction-probability features** beyond price-returns: 25Δ
   risk-reversal skew, put/call OI ratios, overnight gamma exposure. The
   scoring agent flagged these as the highest-quality additions to
   `direction.py`.

---

*End of improvement plan.*
