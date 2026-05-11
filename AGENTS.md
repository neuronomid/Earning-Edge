# AGENTS.md

## Purpose

This file stores repo-specific operating instructions for Codex agents working in
`Earning-Edge`.

## Current Candidate Flow

- The live pipeline candidate step is `app/pipeline/steps/candidates.py`.
- The pipeline uses `app/services/multi_strategy_service.py`, not the older
  single-service phase-4 shape.
- `app/services/candidate_service.py` still exists, but it now acts as the
  catalyst strategy service used inside the multi-strategy flow.
- The Finviz browser/query stack lives in `app/services/finviz/`.

## Required Behaviour

- Do not reintroduce the retired TradingView or legacy phase-4 screener flow.
- Finviz is the only visible screener in the current app. Build encoded
  screener URLs and load them with `page.goto(url)`.
- Do not add login-only, cookie-dependent, or persistent-auth assumptions to
  the Finviz flow.
- Do not introduce hidden or private Finviz APIs. Stay on the public screener
  pages.
- Keep browser automation retry-safe and stateless:
  1. retry the same page load once
  2. retry with a clean browser context
  3. then let the service-level fallback path handle the failure

## Current Finviz Strategies

- Strategy A is `catalyst_confluence`.
- Strategy A uses the broad visible screener URL
  `https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap`.
- Strategy A works from the top five visible rows and validates earnings date,
  liquidity, and other quality checks downstream.
- Strategy B is `coiled_setup`.
- Strategy B uses the visible screener URL
  `https://finviz.com/screener?v=111&f=cap_midover,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,ta_sma50_pa,ta_sma200_pa,ta_highlow52w_b20h,ta_beta_o1,ta_rsi_40to70&o=-relativevolume`.
- Strategy B also works from the top five visible rows.
- When both strategies return the same ticker, preserve the catalyst result and
  dedupe the coiled result behind it.

## Fallback And Warning Rules

- Strategy A falls back to backup earnings sources when Finviz fails or returns
  no usable rows.
- The current backup earnings sources are `YFinanceEarningsSource` and
  `FinnhubEarningsSource`.
- If Strategy A falls back to backup candidates, surface the exact warning:
  `⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.`
- Strategy A currently preserves visible Finviz rows when backup earnings dates
  conflict. Keep the screener row and attach the validation note instead of
  silently dropping it.
- Strategy B is Finviz-only. `app/services/coiled_setup_service.py` currently
  logs Finviz errors and degrades to an empty tuple rather than raising.
- `app/services/multi_strategy_service.py` only treats a strategy as `failed`
  when the service raises. If you change that contract, update the warnings and
  tests together.

## Implementation Anchors

- Runtime candidate entry point:
  `app/pipeline/steps/candidates.py`
- Multi-strategy merge and warnings:
  `app/services/multi_strategy_service.py`
- Catalyst strategy and backup fallback:
  `app/services/candidate_service.py`
- Coiled strategy:
  `app/services/coiled_setup_service.py`
- Finviz strategy definitions:
  `app/services/finviz/strategies.py`
- Finviz browser retry ladder:
  `app/services/finviz/browser.py`
- Finviz query runner, ranking, and merge:
  `app/services/finviz/runner.py`
