# Strategy 3: Two New Complementary Screens (4-Strategy Pipeline)

**Status:** Design proposal. No code changes yet. Pairs with `strategy2.md` (which defines Strategy A and Strategy B).

**Purpose:** Extend the weekly options pipeline from two screens to four. Each screen contributes its top 5 visible candidates, producing a merged pool of up to 20 deduplicated tickers. The existing scoring engine picks the best 4 finalists and the heavy LLM route chooses one contract. This document specifies the two new screens (Strategy C and Strategy D), justifies them with cited academic evidence, and lays out a phased implementation plan with tests.

This proposal is the output of a 10-agent scholastic-consensus session moderated by Opus 4.7. Ten parallel Sonnet 4.6 agents independently researched short-horizon options edges, cited papers, and proposed strategies. Their proposals clustered into three viable themes; two are documented here as production strategies and the third (Insider Cluster Conviction) is captured as future work in Appendix A.

---

## 1. Why two more screens

Strategy A is **pre-earnings, catalyst-driven**. It surfaces stocks reporting next week. Strategy B is **structure-driven, trend-continuation** near 52-week highs. They are complementary but they leave two clear gaps:

1. **Post-earnings continuation.** Strategy A enters before earnings (gamma + IV-crush risk). It does nothing with the post-earnings momentum window, which is one of the most replicated anomalies in academic finance (Bernard & Thomas 1989; Garfinkel, Hribar, Hsiao 2024).
2. **Sector-first signals.** Strategy B picks single stocks near their high. A stock can pass B while sitting in a deteriorating sector (a known Strategy B false positive in late-cycle markets — Moskowitz & Grinblatt 1999 show sector momentum explains a large fraction of stock momentum). The system has no top-down sector view.

Strategy C closes gap (1). Strategy D closes gap (2). Both are deliberately **non-technology-biased** because (a) the user has asked for non-tech coverage to balance the typically tech-heavy output of A and B, and (b) the underlying edges (PEAD, sector momentum) are empirically stronger outside large-cap tech, where analyst coverage is deep and news diffuses fastest.

---

## 2. Strategy C — Post-Earnings Drift Continuation (PEAD)

**Role:** Post-earnings momentum diversifier and natural complement to Strategy A.

**Premise:** Stocks that beat consensus earnings estimates by a material amount and gap up on the announcement day continue drifting higher for 2–3 weeks. The drift is concentrated in mid-cap and small/mid-cap names outside technology — where analyst coverage is thinner and information diffuses more slowly. By entering **1–3 trading days after** the announcement we (a) avoid the binary risk of holding through the report, (b) enter after IV has crushed back toward normalized levels (a 30–60% IV collapse is typical), and (c) capture the institutional accumulation phase that follows the surprise.

### 2.1 Academic basis (cited)

- Bernard, V. L. & Thomas, J. K. (1989). *Post-Earnings-Announcement Drift.* Journal of Accounting Research, 27, 1–36. Documented top-decile SUE stocks outperforming bottom-decile by ~18% annualized over the 60 days post-announcement.
- Garfinkel, J. A., Hribar, P. & Hsiao, S. (2024). *Earnings Autocorrelation and the Post-Earnings-Announcement Drift.* JFQA 59(6), 2799–2837. A long-top / short-bottom SUE hedge portfolio still earns 5.1% risk-adjusted return over three months in modern data.
- Hou, K., Xue, C. & Zhang, L. (2015). PEAD alpha survives q-factor adjustment.
- Meursault et al. (2023). Text-based earnings-surprise variants still detect PEAD in 2008–2019 data.

**Honest decay note.** PEAD has largely been arbitraged away in mega-cap names since 2001. What persists concentrates in mid-cap and small/mid-cap names (roughly $300M–$10B market cap) outside the technology sector. The strategy must be filtered accordingly.

### 2.2 Required Finviz URL

```text
https://finviz.com/screener?v=111&f=earningsdate_prevweek,geo_usa,sh_opt_option,sh_price_o10,sh_avgvol_o500,ta_change_u&o=-change
```

Process: pull the top 20 rows; enrich each with earnings-surprise data from yfinance (primary) and Finnhub (fallback); keep only rows where the most recent reported quarter beat estimates by ≥ 5% and the day-1 reaction was ≥ +3%; apply a non-technology sector bias (excluded sectors below); take the top 5 by composite score.

The `earningsdate_prevweek` filter is the only confirmed-working Finviz filter for "recently reported" (the agent panel verified `earningsdate_prev5days` does **not** work — Finviz silently drops it). `earningsdate_yesterday` is a tighter variant the implementation may run as a second sweep.

### 2.3 Filter and post-filter table

| Layer | Filter | Value | Why |
|---|---|---|---|
| Finviz: Descriptive | Country | USA | Liquidity and data coverage. |
| Finviz: Descriptive | Earnings Date | Previous Week | Captures the 1–5 trading days after a report — the post-IV-crush window. |
| Finviz: Descriptive | Optionable | Yes | Mandatory. |
| Finviz: Descriptive | Price | Over $10 | Cuts penny-stock noise. |
| Finviz: Descriptive | Average Volume | Over 500K | Floor for options liquidity. |
| Finviz: Technical | Change | Up | Stock is still trending up after the report (not a faded gap). |
| Finviz: Sort | Change | Descending | Bias toward the strongest day-1 reactions. |
| Post-filter (yfinance) | EPS surprise % | ≥ +5% | Surprise magnitude predicts drift magnitude. |
| Post-filter (yfinance) | Day-1 reaction | ≥ +3% close-over-prior-close | Market confirmed the news. |
| Post-filter (Finviz sector column) | Sector | NOT `Technology`, NOT `Communication Services` | PEAD edge concentrates outside large-cap tech. |
| Post-filter | Market cap | $300M – $10B | Mid/small-mid is where the academic edge survives. |

**Negative variant.** A symmetric short variant (negative-surprise + day-1 reaction ≤ −3% → long puts) is recorded for completeness but is **out of scope for v1**. PEAD on the downside is partially confounded by analyst-upgrade overhangs and management buybacks; v1 ships long-call only.

### 2.4 Composite ranking

```text
score_C = (eps_surprise_pct / 0.05) × 0.50
       + (day1_change_pct / 0.03)    × 0.30
       + non_tech_bonus              × 0.20

non_tech_bonus = 1.0 if sector ∈ {Healthcare, Industrials, Energy, Materials,
                                  Consumer Defensive, Consumer Cyclical,
                                  Financials, Utilities, Real Estate}
non_tech_bonus = 0.0 otherwise (post-filter excludes tech anyway; this gates a tiebreaker)
```

Top 5 by `score_C`. If fewer than 5 rows pass the post-filters, ship fewer — do not pad with unconfirmed names. The existing pipeline handles partial batches gracefully (see `MultiStrategyCandidateService`'s `screener_status` handling).

### 2.5 Why short-term (under 4 weeks)

The PEAD literature documents drift over 1–3 months, but for the small/mid-cap sub-universe the majority of the excess return concentrates in the first 2–3 weeks (Garfinkel et al. 2024). Selecting contracts that expire in **21–28 days** lets the drift materialize while keeping theta decay manageable. This is exactly the window the existing exit-target engine is tuned for.

### 2.6 Direction and contract preference

- Direction: **long calls** (positive surprise only in v1).
- Delta: **0.40–0.55** at entry — slightly OTM to ATM. Captures continuation drift without paying full ATM vega.
- Expiry: **3–5 weeks DTE** (next standard monthly or weekly).
- Liquidity gate: open interest > 200 at the chosen strike, bid-ask ≤ 15% of mid.

These match the same conventions Strategy A uses; no scoring-engine changes are needed.

### 2.7 Sources used

| Source | Use | Auth | Status |
|---|---|---|---|
| Finviz screener | Universe + sector column | None | Existing |
| yfinance `Ticker.get_earnings_history()` | Quarterly surprise %, actual vs. estimate | None | Already in stack |
| Finnhub `/stock/earnings` | Surprise % fallback | Free API key | Already wired |
| Alpaca options chain | Contract selection | User key | Existing |
| Alpha Vantage `EARNINGS` | Tertiary fallback | User key | Existing |

No new sources required.

### 2.8 Failure modes

1. **Same-day entry against still-elevated IV.** Mitigated by enforcing T+1 minimum from announcement date (the `earningsdate_prevweek` filter naturally pushes entries 1–5 trading days post-announcement, but the post-filter must verify the announcement is not same-day).
2. **Guidance disappointment reversal.** A beat with weak forward guidance can reverse in days 2–5. Mitigated by requiring `ta_change_u` (still up) at scan time, not just the announcement-day pop.
3. **Stale earnings data.** yfinance `get_earnings_history()` lags Finnhub by a few hours after a fresh report. Fallback order: yfinance → Finnhub → Alpha Vantage.
4. **Cross-strategy duplicate position.** If Strategy A opened a position on the same ticker pre-earnings, Strategy C must not reopen post-earnings. Cross-check against `open_positions` before persisting.
5. **PEAD continued decay.** This is the primary unquantified risk — the effect is real but smaller every decade. The honest evidence rating is 6/10, upgradeable to 7 with the full filter stack.

---

## 3. Strategy D — Non-Tech Sector Relative Strength

**Role:** Sector-first momentum diversifier. Closes the structural gap that Strategy B leaves: B picks stocks one at a time without checking whether the underlying sector is leading or trailing the market.

**Premise:** Cross-sectional momentum (Jegadeesh & Titman 1993; Asness, Moskowitz & Pedersen 2013) is one of the most replicated anomalies in finance. Sector-level momentum is more stable than single-stock momentum because the sector aggregate filters out idiosyncratic single-name crashes (Moskowitz & Grinblatt 1999 show industry momentum explains a large share of stock-level momentum). For a 4-week options window, ranking the nine non-tech sector SPDRs by 4-week return, taking the leader, and then picking the top 5 momentum names *inside that sector* gives a clean sector-aligned momentum signal that is orthogonal to Strategy B's single-stock technical pattern.

### 3.1 Academic basis (cited)

- Jegadeesh, N. & Titman, S. (1993). *Returns to Buying Winners and Selling Losers.* Journal of Finance 48(1), 65–91. The foundational cross-sectional momentum result.
- Asness, C., Moskowitz, T. & Pedersen, L. (2013). *Value and Momentum Everywhere.* Journal of Finance 68(3), 929–985. Momentum persistence across 8 asset classes and 4 continents.
- Moskowitz, T. & Grinblatt, M. (1999). *Do Industries Explain Momentum?* Journal of Finance 54(4), 1249–1290. Industry momentum is a primary driver of single-stock momentum.
- Faber, M. (2007). *A Quantitative Approach to Tactical Asset Allocation.* Sector rotation by relative strength beats buy-and-hold with lower drawdown.

**Honest decay note.** Momentum suffered severe drawdowns in 2009 and 2020 due to sharp reversals in prior losers. Short-horizon (1–3 month) momentum is more exposed to sentiment reversal than 6–12 month momentum (Daniel, Hirshleifer & Sun 2020). The strategy is fragile in chop and high-VIX regimes — hence the regime gate below.

### 3.2 Two-step screen

**Step 1 — Sector ETF ranking (yfinance, no auth).** Pull 4-week price return for these 9 non-tech sector SPDRs:

| ETF | Sector | Finviz `sec_` filter |
|---|---|---|
| XLE  | Energy | `sec_energy` |
| XLF  | Financials | `sec_financial` |
| XLI  | Industrials | `sec_industrials` |
| XLV  | Health Care | `sec_healthcare` |
| XLU  | Utilities | `sec_utilities` |
| XLP  | Consumer Staples | `sec_consumerdefensive` |
| XLY  | Consumer Discretionary | `sec_consumercyclical` |
| XLB  | Materials | `sec_basicmaterials` |
| XLRE | Real Estate | `sec_realestate` |

Hard-excluded: `XLK` (Technology) and `XLC` (Communication Services — tech-heavy with GOOG/META/NFLX).

**Step 2 — Stock screen inside the top sector.** Once the leading non-tech sector is known at scan time, build a dynamic Finviz query of the form:

```text
https://finviz.com/screener?v=111&f={leading_sector_filter},geo_usa,sh_opt_option,sh_price_o10,sh_avgvol_o500,ta_sma50_pa&o=-perf4w
```

Process: take the top 5 visible rows sorted by 4-week stock performance descending.

The `ta_sma50_pa` filter (price above 50-day SMA) is a single-stock continuation check that mirrors the spirit of Strategy B without replicating its full filter set. We deliberately do not stack RSI / 52w-high / beta filters on top — Strategy D's edge is sector alignment, not single-stock technicals.

### 3.3 Regime gate (required)

Apply both gates before Step 2. If either fails, return an empty batch and let the pipeline run with three strategies that week:

1. **Top-sector ETF must be above its 50-day SMA** at scan time. Without this, momentum is firing into a downtrend (the "least bad" loser problem).
2. **Top-sector 4-week return must be ≥ +2%.** Below this dispersion floor, sector ranking is noise.

Returning an empty batch is fine — `MultiStrategyCandidateService` already handles partial results gracefully (`CandidateBatch.screener_status="empty"` with a warning). Do not pad.

### 3.4 Composite ranking

The dynamic Finviz sort `-perf4w` is the primary rank. Apply a secondary tiebreaker:

```text
score_D = stock_perf_4w_rank        × 0.60
       + sector_alignment_strength × 0.40   # 1.0 if sector_perf_4w > 5%, 0.5 if 2-5%
```

Top 5 by `score_D`. If the top sector returns fewer than 5 names that pass the Finviz filters, drop to the second-ranked non-tech sector and fill from there until 5 — never from a sector below the regime gate.

### 3.5 Why short-term (under 4 weeks)

Momentum at the 1-month horizon has a 4–8 week half-life before reversal risk climbs. Targeting **21–28 DTE expiries** sits in the middle of the continuation window. Beyond 6 weeks the momentum signal decays and reversal risk dominates — past the system's hard horizon anyway.

### 3.6 Direction and contract preference

- Direction: **long calls** only.
- Delta: **0.45–0.55** at entry (ATM or one strike OTM).
- Expiry: **3–4 weeks DTE**.
- Position-monitor escalation: if the leading sector ETF falls below entry-day price while a Strategy D position is open, mark the position with a `regime_warning` flag in the monitor (no auto-exit; surface it on the next alert).

### 3.7 Sources used

| Source | Use | Auth | Status |
|---|---|---|---|
| yfinance `download(['XLE',...], period='2mo', interval='1d')` | Sector ETF 4-week returns and 50-day SMA | None | Already in stack |
| Finviz screener (dynamic query) | Top 5 stocks inside leading sector | None | Existing browser path |
| Alpaca options chain | Contract selection | User key | Existing |
| Alpha Vantage `SECTOR` | Optional cross-check on sector ranking | User key | Existing |

No new sources required.

### 3.8 Failure modes

1. **Momentum crash.** The biggest 4-week winner becomes the biggest 4-week loser in sharp reversals (e.g., March 2020). Mitigated by the regime gate (Step 1) and the `ta_sma50_pa` per-stock filter.
2. **Sector correlation collapse.** XLE + XLB often move together (commodity-driven). If both are at the top, the strategy is effectively a one-factor bet. Acceptable — the pipeline trades one ticker per scan, not a portfolio.
3. **Flat market.** When all sectors are within 1% over 4 weeks, ranking is noise. The +2% dispersion floor in the regime gate handles this.
4. **Finviz filter code drift.** Finviz occasionally renames filters. The implementation must treat zero-row returns as a hard error (not silent empty) so the fallback path triggers.
5. **Late entry.** If the sector has been leading for 8+ weeks already, the strategy may pick names near the end of their run. Single-stock RSI is intentionally not filtered out here so the scoring engine's overbought penalties pick up the slack downstream.

---

## 4. Merge, score, and LLM flow (4 strategies)

The merge stage extends the existing two-strategy logic in `MultiStrategyCandidateService.get_candidates()`:

1. Run A, B, C, D **concurrently** with `asyncio.gather(..., return_exceptions=True)`.
2. Each contributes up to 5 candidates — total pool up to 20.
3. Dedupe by ticker. **Tie-breaking precedence: A > C > B > D.** A wins because earnings is the strongest single catalyst. C beats B because a confirmed surprise + drift is more actionable than pure structure. D last because sector alignment is the broadest signal.
4. Enrich every surviving candidate with market data, news, earnings data, and options chain (existing fan-out).
5. Score all candidates with the existing engine.
6. Pass only the top 4 by `(final_score, confidence, direction_score)` to the heavy LLM (`DECISION_FINALIST_LIMIT=4` — already correct).
7. LLM picks one ticker + one exact contract from the supplied options, or returns no trade.

The screener-status reporting must extend so the user can see which strategies fired:

```text
| Strategy | Status   | Candidates |
|----------|----------|------------|
| A        | success  | 5          |
| B        | success  | 5          |
| C        | partial  | 2          |   # only 2 names passed the surprise post-filter
| D        | empty    | 0          |   # regime gate closed
```

This builds on the existing `CandidateBatch.screener_status` and `strategy_reports` machinery.

---

## 5. Codebase integration

### 5.1 New / changed files

```text
app/services/finviz/strategies.py
    + STRATEGY_C_BASE (PEAD: earningsdate_prevweek + sh_opt_option + ta_change_u)
    + STRATEGY_C_EARNINGS_PREFIX / STRATEGY_C_EARNINGS_VALUES
    + STRATEGY_D_BUILDER  (function: build_strategy_d_query(sector_filter: str) -> FinvizQuery)

app/services/pead_service.py                              # NEW
    PEADCandidateService
      - get_top_five() -> CandidateBatch
      - _compute_surprise(ticker) via yfinance + Finnhub
      - _post_filter(rows) by surprise, day1 change, non-tech sector

app/services/sector_relative_strength_service.py          # NEW
    SectorRelativeStrengthService
      - get_top_five() -> CandidateBatch
      - _rank_sectors() via yfinance (XLE, XLF, XLI, XLV, XLU, XLP, XLY, XLB, XLRE)
      - _regime_gate(top_etf) -> bool
      - _screen_top_sector(sector_filter) via FinvizQueryRunner

app/services/multi_strategy_service.py
    MultiStrategyCandidateService.__init__
      + pead: PEADCandidateService
      + sector_rs: SectorRelativeStrengthService
    .get_candidates()
      gather A, B, C, D concurrently; extend tie-breaking precedence; extend strategy_reports

app/services/candidate_models.py
    StrategySource = Literal[
        "catalyst_confluence",   # A
        "coiled_setup",          # B
        "pead_continuation",     # C  (new)
        "sector_relative_strength",  # D  (new)
    ]
    ScreenerStatus already supports "success" / "partial" / "failed" / "empty" — sufficient.

app/services/strategy_catalog.py
    + _PEAD_DEFINITION (StrategyDefinition for C)
    + _SECTOR_RS_DEFINITION (StrategyDefinition for D — query_urls computed dynamically at runtime)
    extend _DEFINITIONS dict and build_strategy_report()

app/pipeline/orchestrator.py
    PipelineOrchestrator constructor — add pead and sector_rs injection seams
    get_pipeline_orchestrator() — wire defaults

app/core/config.py
    + PEAD_MIN_SURPRISE_PCT: Decimal = Decimal("0.05")
    + PEAD_MIN_DAY1_REACTION: Decimal = Decimal("0.03")
    + SECTOR_RS_MIN_4W_RETURN: Decimal = Decimal("0.02")
    + SECTOR_RS_SMA_WINDOW: int = 50
```

### 5.2 Database migration

A new Alembic revision is required because `strategy_source` is persisted on `candidates`, `option_contracts`, `recommendations`, `open_positions`, and `workflow_runs`. The fork at `0004_*` (`recommendation_parent_chain` and `strategy_source` as siblings) is preserved — the new migration is the next linear step after `0009_recommendation_news_coverage`.

```text
alembic/versions/0010_strategy_source_extends_pead_sector_rs.py
    op.execute(
        "ALTER TYPE strategy_source ADD VALUE IF NOT EXISTS 'pead_continuation';"
        "ALTER TYPE strategy_source ADD VALUE IF NOT EXISTS 'sector_relative_strength';"
    )
```

If `strategy_source` is stored as a free-form `VARCHAR` (rather than a Postgres ENUM), the migration is a no-op data-only step; only the SQLAlchemy `Literal` widens. Check `app/db/models/` before writing the revision and pick the right form — both are reversible without data loss.

### 5.3 Conventions preserved

- All async. No new sync DB sessions, no `requests`. Use `httpx` for any HTTP, and `asyncio.to_thread` for the synchronous yfinance calls (matches existing pattern in `app/services/market_data/`).
- `Decimal` for all surprise %, return %, and SMA comparisons.
- Frozen dataclasses for new return types.
- Fallbacks beat aborts. PEAD: yfinance → Finnhub → Alpha Vantage. Sector RS: yfinance failure → return empty batch (regime gate logic also acts as a guard).
- All settings via `get_settings()` — no direct `os.environ` reads.
- Ruff strict, black, mypy strict — same as the rest of the codebase.

### 5.4 Pipeline run lock and Redis

No changes. The per-user run lock in `app/services/run_lock.py` covers all four strategies under a single TTL — they run inside one `asyncio.gather`.

### 5.5 Telegram reporting

`PipelineOutcome` is frozen and additive. The reporting layer should surface a per-strategy status table (Section 4) on the run summary card. The existing `LoggingService` already records `strategy_reports`; the bot needs a small renderer extension to print all four lines instead of two.

---

## 6. Phased build plan

Each phase is independently shippable. Phase ordering minimizes pipeline risk: ship the data plumbing and tie-breaking first, then add strategies one at a time so a failure in C does not block D.

### Phase 0 — Schema and Literal widening (1 small PR)

- Add `pead_continuation` and `sector_relative_strength` to `StrategySource` `Literal` in `app/services/candidate_models.py`.
- Write the Alembic revision `0010_*`.
- Confirm `ScreenerStatus` Literal already covers `success | partial | failed | empty` (it does — re-use).
- Run migration locally; run mypy strict to confirm no callers need updating.

Tests: migration upgrade and downgrade idempotency on `earning_edge_test`. No behavior change.

### Phase 1 — Four-arm merge plumbing without new screens (1 PR)

- Refactor `MultiStrategyCandidateService.__init__` to accept four arms (`catalyst`, `coiled`, `pead`, `sector_rs`).
- Inject `pead` and `sector_rs` as **stub services** that return `CandidateBatch(candidates=(), screener_status="empty")` so behavior is unchanged.
- Extend `get_candidates()` to gather four results, dedupe with the A > C > B > D tie precedence, and produce a four-row `strategy_reports` list.
- Extend `PipelineOrchestrator` injection seams.
- Update the Telegram run-summary renderer to print four lines.

Tests:
- `tests/test_multi_strategy_service.py::test_four_arm_merge_empty_stubs` — A and B both populated, C and D empty, output identical to today.
- `tests/test_multi_strategy_service.py::test_tie_precedence_a_over_c_over_b_over_d` — same ticker present in all four batches resolves to A.
- `tests/test_multi_strategy_service.py::test_partial_when_one_arm_raises` — one arm raises, the other three succeed, batch reports `partial` for the failed arm.

### Phase 2 — Strategy C (PEAD Continuation) (1 PR)

- Add `STRATEGY_C_BASE` to `app/services/finviz/strategies.py`.
- Create `app/services/pead_service.py` with `PEADCandidateService.get_top_five()`.
- Implement `_compute_surprise(ticker)` with the yfinance → Finnhub → Alpha Vantage fallback chain.
- Implement the non-tech sector post-filter using the Finviz `Sector` column already parsed by the extractor.
- Wire `PEADCandidateService` into `MultiStrategyCandidateService` (replaces the stub from Phase 1).
- Add `_PEAD_DEFINITION` to `strategy_catalog.py`.
- Add config keys `PEAD_MIN_SURPRISE_PCT` and `PEAD_MIN_DAY1_REACTION`.

Tests:
- `tests/test_pead_service.py::test_post_filter_drops_below_surprise_threshold`
- `tests/test_pead_service.py::test_post_filter_drops_tech_sector`
- `tests/test_pead_service.py::test_yfinance_failure_falls_back_to_finnhub`
- `tests/test_pead_service.py::test_all_three_data_sources_fail_returns_empty_batch`
- `tests/test_pead_service.py::test_top_5_ranking_by_composite_score`
- `tests/test_pead_service.py::test_partial_batch_when_fewer_than_5_pass`
- Integration: `tests/test_pipeline_orchestrator.py::test_pead_arm_contributes_to_finalists`

### Phase 3 — Strategy D (Non-Tech Sector Relative Strength) (1 PR)

- Add the dynamic query builder `build_strategy_d_query(sector_filter)` to `app/services/finviz/strategies.py`.
- Create `app/services/sector_relative_strength_service.py` with `SectorRelativeStrengthService.get_top_five()`.
- Implement `_rank_sectors()` using yfinance batch download for the 9 non-tech SPDRs (XLE, XLF, XLI, XLV, XLU, XLP, XLY, XLB, XLRE).
- Implement `_regime_gate()` — top sector above 50-day SMA AND 4-week return ≥ +2%.
- Implement `_screen_top_sector()` — call `FinvizQueryRunner` with the dynamic query.
- Implement the sector → Finviz filter mapping table.
- Wire `SectorRelativeStrengthService` into `MultiStrategyCandidateService` (replaces the stub from Phase 1).
- Add `_SECTOR_RS_DEFINITION` to `strategy_catalog.py` (note: `query_urls` are computed at runtime; expose them via the strategy report so the Telegram message shows the active sector).
- Add config keys `SECTOR_RS_MIN_4W_RETURN`, `SECTOR_RS_SMA_WINDOW`.

Tests:
- `tests/test_sector_relative_strength_service.py::test_ranks_etfs_by_4w_return`
- `tests/test_sector_relative_strength_service.py::test_regime_gate_blocks_when_top_below_sma50`
- `tests/test_sector_relative_strength_service.py::test_regime_gate_blocks_when_dispersion_below_2pct`
- `tests/test_sector_relative_strength_service.py::test_drops_to_second_sector_when_first_returns_fewer_than_5`
- `tests/test_sector_relative_strength_service.py::test_excludes_xlk_and_xlc_unconditionally`
- `tests/test_sector_relative_strength_service.py::test_dynamic_finviz_url_built_correctly`
- Integration: `tests/test_pipeline_orchestrator.py::test_sector_rs_arm_contributes_to_finalists`

### Phase 4 — End-to-end and dogfooding (1 small PR)

- Add a full 4-strategy integration test using the existing pipeline fixtures.
- Verify `WorkflowRun` rows correctly record the four strategy contributions in `strategy_reports`.
- Verify the position monitor still works: a position opened by C or D flows through `app/services/positions/monitor.py` unchanged (the monitor is strategy-agnostic).
- Manual dogfood: run a real scan against the user's actual cron, verify the Telegram message renders 4 strategy lines, verify a C or D recommendation can be filled and tracked end-to-end.

Tests:
- `tests/test_pipeline_orchestrator.py::test_all_four_strategies_concurrent`
- `tests/test_pipeline_orchestrator.py::test_three_succeed_one_empty_runs_to_completion`
- `tests/test_logging_service.py::test_strategy_reports_persists_all_four`

---

## 7. Test plan summary

| Scope | New tests | What they prove |
|---|---|---|
| Migration | upgrade + downgrade idempotent on `earning_edge_test` | Schema widening is safe to ship |
| Merge logic | 3 tests in `test_multi_strategy_service.py` | Tie-precedence works; partial failures degrade gracefully |
| PEAD service | 6 tests in `test_pead_service.py` | Surprise filter, tech exclusion, fallback chain, top-5 ranking, empty batch |
| Sector RS service | 6 tests in `test_sector_relative_strength_service.py` | ETF ranking, regime gate, second-sector fallback, XLK/XLC exclusion, dynamic URL |
| Pipeline | 3 tests in `test_pipeline_orchestrator.py` | Four-strategy run, partial run, full run to LLM finalist selection |
| Logging | 1 test in `test_logging_service.py` | `strategy_reports` writes all four rows |

Total: ~19 new tests. All use pytest's async-mode auto and the existing fixture conventions in `tests/conftest.py` (skip-if-no-postgres pattern preserved).

---

## 8. Risks and what kills this proposal

1. **Finviz filter drift.** `earningsdate_prevweek` or `sec_consumerdefensive` could be renamed. Mitigation: the existing retry-once + clean-context + backup-source pattern in `app/services/finviz/` already handles `0` returns from a bad query.
2. **PEAD continued decay.** If the effect has fully decayed by 2026, Strategy C produces noise. Mitigation: the post-filter (surprise ≥ 5%, day-1 reaction ≥ 3%, non-tech, mid-cap) is the published "edge survives" subset. If even that decays, Strategy C will simply contribute empty batches and the system runs effectively on A + B + D.
3. **Sector RS momentum crash.** A 2020-style reversal would have Strategy D recommending the worst names within a week. Mitigation: the regime gate (top ETF above SMA-50 AND ≥ +2% dispersion) is designed to fail closed in those regimes.
4. **Pipeline runtime.** Four arms running concurrently with options-chain fan-out per ticker raises the total run time. Mitigation: per-arm `asyncio.gather` is unchanged in shape; the Redis run-lock TTL (900s default) has headroom; if real measured runs cross 600s, raise the lock TTL or split into two phases.
5. **Data-source rate limits.** Alpha Vantage free tier is 25 calls/day. PEAD's surprise post-filter could exhaust it on a busy earnings week. Mitigation: yfinance is the primary path; Alpha Vantage is the tertiary fallback only.
6. **Tie-precedence reshuffles outcomes.** Inserting C between B and D in tie precedence will, in some weeks, change which strategy gets credit for a given ticker. Cosmetic only — the underlying decision is identical.

---

## 9. Out of scope for v1

- **Strategy C bearish variant** (negative-surprise → long puts). Recorded for v2 after positive variant is observed live.
- **Strategy D regime gate variants** (use sector RSI or ATR instead of SMA-50). Defer until live data motivates the change.
- **Macro-calendar gating** (FOMC/CPI/NFP weeks). The 10-agent panel's third candidate theme. Captured in `improvement.md` as future work.
- **Insider Cluster Conviction (Form 4)**. Documented as Appendix A. Strong signal but adds an external scraping dependency we don't want in v1.
- **Replacing existing scoring weights or LLM routing.** The 0.45 direction × 0.55 contract blend stays untouched — these strategies feed into it without changing it.

---

## Appendix A — Strategy E (deferred): Insider Cluster Conviction

Documented for completeness. **Not** implemented in v1.

**Premise:** When 3+ distinct corporate insiders at the same company file Form 4 *open-market purchases* within a 10-trading-day window for ≥ $25,000 each (cluster total ≥ $100,000), the cluster predicts 2.1% monthly abnormal returns vs. 0.9% for solitary insider buys (Alldredge & Blank 2019). The signal is front-loaded in the first 2 weeks of the disclosure window (Jeng, Metrick & Zeckhauser 2003) — a clean fit for 2–3 week long-call positions.

**Sources:**
- OpenInsider.com cluster page (free, no login, public scrape) — primary
- SEC EDGAR EFTS Form 4 search (free, no auth, 10 req/sec with User-Agent) — fallback
- yfinance / Alpaca for downstream enrichment — existing

**Why deferred:**
1. OpenInsider is a scraping target, not an official API — page structure changes break parsing.
2. The clean academic edge concentrates in small/mid-cap names where options liquidity is thinnest.
3. Adds a new external dependency at the edge of the data stack.

If shipped as Strategy E later, the implementation slot is `app/services/insider/form4_cluster_service.py`, with sector filter excluding `Technology`. Expected build cost: same as Strategy C (Phase-2-equivalent), plus the OpenInsider parser.

---

## Appendix B — Rejected outliers from the 10-agent panel

For the record, these themes were considered and rejected:

- **Short-Interest Squeeze.** Academic evidence runs *against* the squeeze narrative as a long signal (Boehmer, Jones & Zhang 2008; Cohen, Diether & Malloy 2007). The agent recommending it rated it 4/10 and suggested it become a scoring modifier, not a screen.
- **Unusual Options Volume (Pan & Poteshman 2006).** The academic edge requires *signed* intraday order flow that is not available in free data. Agent rating: 3/10 implementability.
- **Pre-catalyst Biotech (FDA PDUFA gambling).** Incompatible with a long-premium-only system due to IV crush at the event. The compatible version (post-catalyst drift) was considered but defers to Strategy C and Strategy D for sector coverage.
- **IV Term-Structure Inversion.** Academically supported but free yfinance/Alpaca IV data is too noisy for thinly traded names; implementation fragility too high.

---

## References

1. Asness, C., Moskowitz, T., & Pedersen, L. (2013). Value and momentum everywhere. *Journal of Finance*, 68(3), 929–985.
2. Alldredge, D., & Blank, B. (2019). Do insiders cluster trades with colleagues? *Journal of Financial Research*, 42(2), 331–360.
3. Bernard, V. L., & Thomas, J. K. (1989). Post-Earnings-Announcement Drift: Delayed Price Response or Risk Premium? *Journal of Accounting Research*, 27, 1–36.
4. Boehmer, E., Jones, C. M., & Zhang, X. (2008). Which Shorts Are Informed? *Journal of Finance*, 63(2), 491–527.
5. Cohen, L., Diether, K. B., & Malloy, C. (2007). Supply and demand shifts in the shorting market. *Journal of Finance*, 62(5), 2061–2096.
6. Cohen, L., Malloy, C., & Pomorski, L. (2012). Decoding inside information. *Journal of Finance*, 67(3).
7. Daniel, K., Hirshleifer, D., & Sun, L. (2020). Short- and long-horizon behavioral factors. *Review of Financial Studies*, 33(4), 1673–1736.
8. Faber, M. (2007). A quantitative approach to tactical asset allocation. *Journal of Wealth Management*, Spring 2007.
9. Garfinkel, J. A., Hribar, P., & Hsiao, S. (2024). Earnings autocorrelation and the post-earnings-announcement drift. *Journal of Financial and Quantitative Analysis*, 59(6), 2799–2837.
10. Hou, K., Xue, C., & Zhang, L. (2015). Digesting anomalies: An investment approach (q-factor model). *Review of Financial Studies*.
11. Jegadeesh, N., & Titman, S. (1993). Returns to buying winners and selling losers. *Journal of Finance*, 48(1), 65–91.
12. Jeng, L. A., Metrick, A., & Zeckhauser, R. J. (2003). Estimating the returns to insider trading. *Review of Economics and Statistics*, 85(2), 453–471.
13. Meursault, V., Liang, P., Routledge, B., & Scanlon, M. (2023). Enhancing post earnings announcement drift measurement with LLMs. FinNLP / ACL Anthology.
14. Moskowitz, T., & Grinblatt, M. (1999). Do industries explain momentum? *Journal of Finance*, 54(4), 1249–1290.
15. Pan, J., & Poteshman, A. M. (2006). The information in option volume for future stock prices. *Review of Financial Studies*, 19(3), 871–908.
