# Earning-Edge — Project Evaluation Report

**Date:** 2026-05-15
**Scope:** Code review of `C:\Users\sseif\Desktop\Earning-Edge-main` against the design intent in `docs/` and `CLAUDE.md` / `AGENTS.md`. No code changes made.
**Test run:** 349 passed · 55 skipped (Postgres-dependent) · 1 xfailed · 5 environmental errors (Windows tmp-dir permissions, not code bugs).

## 1. Does it make sense as a whole?

**Yes.** The system is a coherent five-strategy weekly options scanner with a post-fill position monitor and an LLM-driven thesis revalidation layer. The pieces that the design documents promised are present, wired together, and reach each other through clean DI seams:

```
candidates → market data → news → options → scoring → sizing → LLM decide
                                                          ↓
                                                  Recommendation
                                                          ↓
                                   OpenPosition + PositionThesis
                                          ↓
                          PositionMonitor (every 2 min, NYSE hours)
                                          ↓
                   drift signals → RevalidationService (heavy LLM)
```

`PipelineOrchestrator` (`app/pipeline/orchestrator.py`) is the single source of truth. The monitor (`app/services/positions/monitor.py`) and revalidation (`revalidation_service.py`) are strictly separate from the recommendation flow but share the same notifier, market-hours gate, and run-lock primitives. Multi-strategy candidate fan-in goes through one `asyncio.gather` (`multi_strategy_service.py:88-93`).

## 2. Strategies — do they work?

All five exist and produce `CandidateBatch` via the same `ArmRunner` protocol (`multi_strategy_service.py:49-57`), are gathered concurrently, and dedupe in the documented priority **A → C → B → D → E** (matches `AGENTS.md`).

| # | Strategy | Status | Notes |
|---|---|---|---|
| A | `catalyst_confluence` | ✅ wired, Finviz + backup earnings | **Filter set is still minimal** (`("earningsdate_nextweek", "geo_usa")` sorted by `-marketcap`) — exactly what `docs/improvement.md` §B4 called "drift, not deliberate". The graded relaxation engine is **not built**. |
| B | `coiled_setup` | ✅ wired, Finviz only | **Still measures no compression.** No `ta_volatility_wo4`, no ATR percentile, no Bollinger width — `docs/improvement.md` §B5 unfixed. The name does not match the filter set. |
| C | `pead_continuation` | ✅ fully implemented | Surprise post-filter, tech exclusion, market-cap band, T+1 enforcement, fallback chain yfinance → Finnhub → Alpha Vantage, cross-arm dedupe against open A positions, `event_signal` populated. Faithful to `docs/strategy3_Claude.md` §2. |
| D | `sector_relative_strength` | ✅ fully implemented | Two-step screen with regime gate (sector ETF above SMA-50 AND ≥ 2% 4w return). Second-sector fallback also re-checks the gate. Faithful to `docs/strategy3_Claude.md` §3. |
| E | `activist_13d_followthrough` | ✅ fully implemented | SEC EDGAR client + parser + composite event score, three-tier filing lookback, universe + options-liquidity gates, tier-3 survivor gate, earnings-collision penalty. Faithful to `docs/strategy3_Codex.md` §6. |

**Score fairness for the new arms is in place** (`scoring/direction.py` `_V2_WEIGHTS_BY_STRATEGY`, `scoring/confidence.py` `_V2_CONFIDENCE`, `scoring/strategy_policy.py`). Every strategy row sums to **85 direction points** and **0.97 confidence weight** — I verified each row by hand. The `SCORING_FAIRNESS_V2` rollback flag exists in config; legacy weights are preserved.

**Per-strategy trade policies** are encoded (`strategy_policy.py:_POLICIES`): non-catalyst strategies require 14–45 DTE, 4+ trading days to exit, prob-of-touch ≥ 0.35, R:R ≥ 0.80, volume ≥ 5 / OI ≥ 10. Catalyst has looser floors (3 DTE, R:R 0.50, vol/OI 1). This is exactly the structure the PM 195C post-mortem (`docs/dumb.md`) prescribed.

## 3. The PM-195C class of failure — fixed?

Yes, structurally. The deterministic guards that `docs/dumb.md` demanded are all wired:

- `app/services/market_hours.py:trading_reference_date` — NYSE-aware valuation date (no more UTC drift).
- `app/services/exit_target.py:_planned_exit_date` — uses `previous_or_same_trading_session`; the Sunday-exit bug cannot recur.
- `app/scoring/probability.py:assess_option_reality` — emits `weekly_otm_no_catalyst`, `target_unreachable_by_exit`, `low_pot_no_catalyst`, `breakeven_outside_exit_move`, `invalid_exit_session`, `too_few_exit_sessions_no_catalyst`, `missing_exit_horizon_move`.
- `app/scoring/vetoes.py:109-159` — each of those flags is a hard veto. Risk-reward and liquidity floors fire from `policy`.
- `app/services/exit_target.py:_realistic_long_target` — refuses targets below 1.08× entry; uses Black-Scholes repricing when available and **caps the local-Greeks projection at the BS value** (avoids the gamma-overstated 4.09 PM target).

## 4. Validation / Revalidation — does it work?

Yes, end-to-end, and it integrates with the monitor instead of layering on top of it.

- **Capture:** `position_thesis_builder.py` creates a `PositionThesis` row when a position opens (or backfills on first poll). Stores entry premium, IV, greeks, plan, expected trajectory, catalyst kind, invalidation criteria, news baseline.
- **Drift (no LLM):** `app/services/positions/drift.py:evaluate_position_drift` checks 10 deterministic criteria (option/underlying stop breach, adverse drift > 0.75×EM, premium lag, IV adverse move, time-decay overshoot, catalyst-passed-no-follow-through, PEAD-specific failure, expiry imminent, material headline, data unavailable). Each criterion emits a severity (`kill` / `degrade` / `informational`).
- **Auto-escalation:** when the monitor's drift evaluation fires a `kill`/`degrade` code and `position_validation_shadow_mode` is off, it calls `RevalidationService.validate_position_auto` (`monitor.py:393-422`). Suppressed by per-code cooldown + per-session cap (`_auto_suppressed`).
- **Manual:** Telegram "Validate" button → `RevalidationService.validate_position_manual`. Both paths gated on `current_market_session is not None`.
- **LLM symmetry:** `_normalize_validation` enforces the design's symmetric guardrails — `close` requires a fired `kill` criterion or material headline (otherwise downgrades to `adjust_stop` or `insufficient_data`); `hold` with an unexplained `kill` is forced to `insufficient_data`; invalid adjustments fall back to `insufficient_data`. The `insufficient_data` escape hatch in `validation_schemas.py:ValidationAction` is present.
- **Plan overrides:** `PositionPlanOverride` rows feed `active_position_plan`; monitor reads the merged plan on the next tick.

This is more complete than the original `docs/validation.md` proposal — the `docs/validation2.md` critique (no underlying snapshot, no quote snapshot service) has been addressed via `PositionSnapshotService` + `PositionQuoteSnapshot`.

## 5. Scoring engine — sane?

Mostly yes, with two carryover issues from `improvement.md` still present.

**Working well:**
- Strategy-aware direction weights and confidence weights, weights sum verified, `event_signal` plumbed through `CandidateRecord → CandidateContext`.
- Hard vetoes correctly zero contract score; confidence < 40 forces `no_trade`; final blend `0.45 × direction + 0.55 × contract` unchanged.
- Action gate has guardrails beyond the basic threshold: `direction < 55` or `contract < 60` downgrades a 68+ score to `watchlist`; naked `short_call` needs `direction ≥ 65 AND confidence ≥ 60`.
- News-blackout downgrade: a non-catalyst `recommend` becomes `watchlist` when `news_article_count == 0` or `news_coverage == "none"` (`final.py:89-94, 131-143`).

**Still off:**
- **Dead-weight `previous_earnings_move_percent`** — the orchestrator never sets this field on `CandidateContext` (verified via grep: no assignment site exists in `app/`). For Strategy A the 8-point "earnings expectation context" factor in `_V2_WEIGHTS_BY_STRATEGY["catalyst_confluence"]` and the legacy 15-point factor both read it; both silently default to 0. `improvement.md` §B6 flagged this; not fixed.
- **`MISSING_UNIT = 0.45`** (`direction.py:20`) — missing signals still get 45% credit, which `improvement.md` §B11 said should be 0. A coiled candidate with 4 missing signals can still post a "tepidly positive" direction score from absence alone. Not fixed.

## 6. Sizing — sane?

- Long-option sizing matches PRD §9.2 (`ask × 100` budget against `risk_percent × account`), bounded by `max_contracts` and `max_option_premium`.
- Short put / short call sizing implements PRD §9.3, with naked short call gated on a real `uncovered_call_margin_requirement` (computed in `scoring/types.py`) — not the strike-notional shortcut. This is the §B2 fix `improvement.md` asked for.
- `custom_risk_percent` is now bounded — `validate_custom_risk_percent` raises if > 5% (`scoring/types.py:266-273`). `improvement.md` §B3 fixed.
- **Still missing:** no portfolio-level open-risk cap (`improvement.md` §B8) — sizing reads `account_size` but never queries `OpenPosition`. Four concurrent 2% trades still equals 8% portfolio risk silently. No slippage/commission buffer (§B13).

## 7. LLM router — sane?

- Two routes only (`summarize`, `decide`). `decide` raises `ValueError` if pointed at the lightweight model (`router.py:176-181`).
- `decide` uses `temperature=0`, `seed=0`, `response_format=json_object`, structured-schema validation, `reasoning={"effort": "medium", "exclude": True}` for thinking on Opus.
- 401/403 → `LLMAuthenticationError` (blocked no-trade); 429/5xx → tenacity retry then `LLMRateLimitError`/`LLMUnavailableError` (heuristic fallback).
- `summarize` carries the `reasoning={"effort":"low","exclude":True}` + JSON-mode upgrade the `dumb.md` post-mortem prescribed (so Gemini 3 Pro Preview doesn't burn its budget on hidden reasoning).
- `LLMDecisionStep` retries once with a targeted corrective prompt before falling back; `validate_llm_decision` recomputes the structural score so the user-visible number is deterministic regardless of LLM output.

## 8. News pipeline — sane?

- Fixed sources (Finnhub + SEC EDGAR), open-web search/scraping deliberately retired — matches `docs/news-poposed-solution.md` and `CLAUDE.md` directives.
- Fallback bundles set `news_coverage="none"` and `stale_news=True` and `brief_status="unavailable"` (`orchestrator.py:808-854`) — fixes `dumb.md` §P0-7 (no more "adequate" coverage with a "service unavailable" key uncertainty).
- News-blackout downgrade is in `scoring/final.py:_news_is_truly_unavailable` — only fires on `article_count == 0` or `coverage == "none"`, so a summarizer hiccup with raw headlines present does not silently kill a sector-RS recommend.

## 9. Test health

- 411 tests collected, 349 pass without Postgres (the rest skip cleanly via the `conftest.py` gate).
- The 5 errors I saw were Windows-only `WinError 5` permission failures on pytest's tmp dir under `C:\Users\sseif\AppData\Local\Temp\pytest-of-sseif`, not code defects. They affect `test_logging_service.py` + `test_qa_services.py` which write artifacts to disk; they'd pass under Docker or with that dir cleared.
- One `xfail`: `test_long_plain_message_is_flagged_for_missing_friendly_framing` — documented Phase-2 tone-rule TODO.
- The fairness regression suite (`tests/test_scoring_fairness.py`) exists and is green.

## 10. Things I'd genuinely worry about

Ranked by severity:

1. **Strategy A is still misnamed.** `("earningsdate_nextweek", "geo_usa")` sorted by `-marketcap` is a megacap-earnings dragnet, not "Catalyst Confluence." The graded-relaxation engine the improvement plan committed to has not been built. Every PRD §5.2 filter (`fa_epssurprise_pos`, `fa_revenuesurprise_pos`, analyst revisions, SMA confluence, RSI band) is absent. This is the single biggest gap between docs and code.
2. **Strategy B measures nothing "coiled."** No volatility-compression filter at any layer — Finviz, scoring, or otherwise. The product claim does not match the implementation.
3. **`previous_earnings_move_percent` is dead weight in Strategy A scoring.** The orchestrator never populates it, so the 8/15-point earnings-history factor and the `inconsistent_history` penalty both silently no-op. The A weight row in the rebalance still allocates 15 points to a factor that always returns 0 → A candidates are systematically under-scored on direction relative to the design.
4. **`MISSING_UNIT = 0.45`** — missing direction signals still get half-credit. Multi-signal absence can stack into "looks bullish" purely from missing data.
5. **No portfolio-level open-risk cap.** Sizing is per-trade only. A user with 2% risk profile and 4 concurrent open positions is at 8% portfolio exposure with no warning.
6. **PRD §6.4 cache TTL drift.** `PRD2.md` §6.4 documents news cache TTL = 7200s. The current `NewsService` caches by article-set hash rather than time-bounded TTL (deterministic-cache design from `PLAN_News.md`). The PRD doc has not been updated to reflect that — minor doc/code divergence but worth fixing the doc.
7. **Strategy E SEC client must run with a real user-agent string.** `activist_13d_user_agent` setting exists but defaults must be configured at deploy; otherwise EDGAR returns 403 after a few requests. Production deploy notes should mention this.

## 11. Bottom line

The system makes sense. The architecture documented across the `docs/` files is largely realized in code, with one notable exception (the Strategy A / Strategy B filter sets never caught up to either the PRD or the improvement plan). The five-strategy expansion, scoring rebalance, position revalidation, market-hours gating, probability/reality gates, short-premium real margin estimator, and news-blackout guard are all real and tested. Failure modes are documented and degrade gracefully — fallbacks beat aborts at every external boundary.

It is closer to "shippable with two known product gaps to close before the weekly run is trustworthy" than to "broken." Issues 1–4 above are the load-bearing ones; the rest are polish.
