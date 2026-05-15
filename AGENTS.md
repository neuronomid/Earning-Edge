# AGENTS.md

## Purpose

This file stores repo-specific operating instructions for Codex agents working in
`Earning-Edge`.

## Current Runtime Architecture

- Runtime orchestration starts in `app/pipeline/orchestrator.py`.
- The candidate pipeline step is `app/pipeline/steps/candidates.py`.
- Candidate selection is handled by `app/services/multi_strategy_service.py`.
- The multi-strategy service runs five arms concurrently, merges rows in the
  configured arm order, and dedupes by ticker while preserving the first
  strategy result.
- The default merge priority is Strategy A, Strategy C, Strategy B, Strategy D,
  then Strategy E: catalyst rows win first, then PEAD, coiled setup, sector
  relative strength, and activist 13D rows.
- Candidate rows use `app/services/candidate_models.py`; keep
  `StrategySource`, `StrategyRunReport`, `CandidateRecord`, and
  `CandidateBatch` aligned when adding or renaming strategies.
- Strategy metadata for labels, providers, criteria summaries, filter codes, and
  query URLs lives in `app/services/strategy_catalog.py`.
- The live pipeline analyzes candidates in two passes:
  1. score all candidates with market data, option chain data, deferred news,
     deterministic scoring, and sizing
  2. refresh live news for the decision finalists, then choose with the LLM
     decision step and heuristic fallback
- The decision layer is `app/pipeline/steps/decide.py`; tests use the
  deterministic heuristic step, while non-test runtime uses the LLM step with
  structured validation and heuristic fallback.
- Persisted candidates, contracts, recommendations, run summaries, and Telegram
  strategy summaries depend on strategy reports. If report shape changes, update
  logging, templates, migrations, and tests together.

## Current Candidate Strategies

- Strategy A is `catalyst_confluence`.
  - Service: `app/services/candidate_service.py`.
  - Provider: Finviz plus backup earnings sources.
  - Uses the broad public Finviz screen for USA companies reporting earnings
    next week, sorted by market cap.
  - Keeps visible Finviz rows when backup earnings dates conflict; attach the
    validation note instead of silently dropping the row.
- Strategy B is `coiled_setup`.
  - Service: `app/services/coiled_setup_service.py`.
  - Provider: Finviz-only.
  - Uses the visible public Finviz screen for optionable, liquid, above-trend
    stocks near 52-week highs with RSI 40-70, sorted by relative volume.
- Strategy C is `pead_continuation`.
  - Service: `app/services/pead_service.py`.
  - Provider: Finviz plus earnings surprise enrichment from yfinance, Finnhub,
    and Alpha Vantage.
  - Starts from recent-earnings public Finviz rows, then requires positive
    surprise, confirmed day-1 reaction, non-tech sector, and configured market
    cap bounds.
  - Skips tickers with recent active catalyst positions for the same user.
- Strategy D is `sector_relative_strength`.
  - Service: `app/services/sector_relative_strength_service.py`.
  - Provider: yfinance sector ETF ranking plus dynamic public Finviz sector
    screens.
  - Excludes tech and communication services; gates on sector ETF four-week
    performance and SMA trend before screening the leading sector.
- Strategy E is `activist_13d_followthrough`.
  - Service: `app/services/activist_13d_service.py`.
  - Provider: SEC EDGAR, market data, and real option-chain liquidity.
  - Parses recent Schedule 13D and 13D/A filings, requires active-intent or
    substantive amendment evidence, applies universe and option-liquidity gates,
    and ranks by deterministic event score.

## Finviz Rules

- Do not reintroduce the retired TradingView or legacy phase-4 screener flow.
- Finviz is the only visible web screener in the current app. Build encoded
  public screener URLs and load them with `page.goto(url)`.
- The Finviz browser/query stack lives in `app/services/finviz/`.
- Query definitions live in `app/services/finviz/strategies.py`.
- URL construction is owned by `app/services/finviz/query.py`; avoid hand-built
  URL strings outside strategy definitions and tests.
- Do not add login-only, cookie-dependent, or persistent-auth assumptions to the
  Finviz flow.
- Do not introduce hidden or private Finviz APIs. Stay on the public screener
  pages.
- Keep browser automation retry-safe and stateless:
  1. retry the same page load once
  2. retry with a clean browser context
  3. then let the service-level fallback or empty-strategy path handle failure
- The Finviz runner may query variants concurrently, cache by strategy source
  and stable query hash, merge duplicate tickers by best visible rank, and stamp
  the returned `strategy_source`.

## Fallback And Warning Rules

- Strategy A falls back to backup earnings sources when Finviz fails or returns
  no usable rows.
- The Strategy A backup earnings sources are `YFinanceEarningsSource` and
  `FinnhubEarningsSource`.
- If Strategy A falls back to backup candidates, surface the exact warning:
  `⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.`
- Strategy B is Finviz-only. It logs Finviz errors and degrades to an empty
  `CandidateBatch` rather than raising.
- Strategy C logs Finviz/enrichment failures and usually returns an empty batch
  rather than raising.
- Strategy D returns an empty batch when yfinance sector ranking is unavailable
  or the regime gate blocks the scan; report-level warnings carry the reason.
- Strategy E may return partial or empty batches with report-level warnings when
  too few qualified activist candidates pass all gates.
- `app/services/multi_strategy_service.py` treats a strategy as `failed` only
  when an arm raises. Empty batches are not failures unless that contract is
  changed intentionally.
- Multi-strategy warning strings are user-visible. If changing strategy status
  semantics or warning text, update `tests/test_multi_strategy_service.py`,
  Telegram run-summary tests, logging tests, and e2e failure tests together.
- If both legacy Finviz arms, Strategy A and Strategy B, are empty while newer
  strategies return rows, preserve the legacy-empty warning so the user knows the
  original screens found no setups.

## Pipeline Service Boundaries

- Market data step: `app/pipeline/steps/market_data.py` delegates to
  `app/services/market_data/service.py`.
- News step: `app/pipeline/steps/news.py` delegates to
  `app/services/news/service.py`; live news is refreshed only for finalists.
- Options step: `app/pipeline/steps/options.py` delegates to
  `app/services/options/service.py`; Alpaca credentials are optional and
  yfinance fallback behavior is expected.
- Scoring step: `app/pipeline/steps/scoring.py` delegates to deterministic
  scoring in `app/scoring/`.
- Sizing step: `app/pipeline/steps/sizing.py` delegates to
  `app/services/sizing.py`; sizing failures degrade to fallback sizing text.
- Candidate context must carry `strategy_source` and optional `event_signal` into
  scoring, decision input, persistence, logging, and Telegram rendering.

## Implementation Anchors

- Runtime orchestrator:
  `app/pipeline/orchestrator.py`
- Runtime candidate entry point:
  `app/pipeline/steps/candidates.py`
- Multi-strategy merge, dedupe, warnings, and default arm order:
  `app/services/multi_strategy_service.py`
- Strategy definitions and report metadata:
  `app/services/strategy_catalog.py`
- Candidate models and strategy literals:
  `app/services/candidate_models.py`
- Catalyst strategy and backup fallback:
  `app/services/candidate_service.py`
- PEAD strategy:
  `app/services/pead_service.py`
- Coiled setup strategy:
  `app/services/coiled_setup_service.py`
- Sector relative-strength strategy:
  `app/services/sector_relative_strength_service.py`
- Activist 13D strategy:
  `app/services/activist_13d_service.py`
- Finviz strategy definitions:
  `app/services/finviz/strategies.py`
- Finviz browser retry ladder:
  `app/services/finviz/browser.py`
- Finviz query runner, ranking, cache, and merge:
  `app/services/finviz/runner.py`
