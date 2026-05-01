# Plan 1 — Phased Development Roadmap

**Source PRD:** [PRD1.md](./PRD1.md) (V1.1)
**Goal of this document:** Break the V1 build into self-contained phases. Each phase is sized for one focused work session and has its own scope, packages, files, tests, and Definition of Done. Pick one phase at a time.

## Confirmed product decisions

- **Multi-user from V1** — encrypted per-user API keys.
- **Docker Compose** for local development (mirrors VPS prod).
- **aiogram 3.x** for the Telegram bot.
- **Tests inside every phase** (pytest + pytest-asyncio).
- **Python 3.12**, **uv** as the dependency/lockfile manager.

## PRD coverage matrix

| PRD § | Topic | Phase |
|---|---|---|
| §1, §2, §32 | Product summary, behavior examples | 11 |
| §3.1, §3.2 | Workflow, manual trigger | 3, 11 |
| §4.1, §4.2 | Must / must-not requirements | Cross-cutting |
| §5 | TradingView Screener integration | 4 |
| §6.1–6.5 | Data sources, fallback rule | 5, 6 |
| §7.1–7.5 | OpenRouter, Opus, Gemini, model separation | 7 |
| §8.1–8.3 | User settings, timezones, defaults | 2 |
| §9.1–9.4 | Risk profile, sizing, short-option caps | 10 |
| §10.1–10.6 | Telegram UX, tone, buttons | 2, 3, 11 |
| §11.1–11.2 | Onboarding flow | 2 |
| §12.1–12.5 | Cron management + run-lock | 3 |
| §13.1–13.3 | Recommendation, no-trade, short templates | 11 |
| §14.1–14.3 | Candidate selection + validation | 4 |
| §15.1–15.3.6 | Direction & contract scoring, vetoes, penalties | 9 |
| §16.1–16.3 | Long/short strategy mapping | 9 |
| §17.1–17.4 | Expiry selection (BMO/AMC rule) | 9 |
| §18.1–18.3 | Strike selection + multi-strike compare | 9 |
| §19.1–19.6 | Liquidity, spread, retrieval order | 6, 9 |
| §20.1–20.4 | IV, expected move, breakeven | 9 |
| §21.1–21.3 | Final selection / no-trade rule | 11 |
| §22.1–22.4 | News research | 8 |
| §23.1–23.6 | Logging, recommendation cards, V2 prep | 12 |
| §24.1–24.7 | DB schema (7 tables) | 1 |
| §25.1–25.2 | Architecture, services | 0 (skeleton) + all phases |
| §26.1–26.3 | Error handling | Cross-cutting + 13 |
| §27.1–27.7 | Data confidence system | 9 (compute), 11 (display) |
| §28.1–28.4 | Acceptance criteria | 13 |
| §29.1–29.2 | MVP scope guardrails | Whole plan |
| §30, §30.1 | V2 — Feedback Agent | Out of scope; only `feedback_events` stub created (Phase 1) |
| §31 | PRD's suggested phases | Reference (this plan refines it) |
| §33 | Build priorities | Used to order phases |
| §34 | DoD for V1 | Phase 13 final gate |

## Phase index

| # | Phase | One-line goal |
|---|---|---|
| 0 | Project Foundation | Reproducible Docker dev env + FastAPI skeleton |
| 1 | Database & Encryption | All 7 PRD tables + Fernet-encrypted secrets |
| 2 | Telegram Bot, Onboarding & Settings | Full §10/§11/§8 in aiogram 3.x |
| 3 | Schedule, Cron & Run-Lock | APScheduler + manual run + duplicate-run lock |
| 4 | TradingView & Candidate Validation | Playwright top-5 extraction + backup earnings calendar |
| 5 | Market Data Service | yfinance + Alpha Vantage + indicators + Redis cache |
| 6 | Options Service | Alpaca primary, yfinance fallback, filters |
| 7 | LLM Router | OpenRouter → Opus 4.7 Thinking + Gemini 3.1 Flash |
| 8 | News & Web Research | Search + Gemini-summarized news brief |
| 9 | Scoring Engine | Direction + Contract + Final scores, vetoes, expiry/strike, confidence |
| 10 | Risk & Position Sizing | Long/short sizing per risk profile |
| 11 | Recommendation Pipeline & Telegram Output | Orchestrator + §13 templates |
| 12 | Logging & Evidence Cards | Per-run JSON snapshots, recommendation cards |
| 13 | E2E Tests, Hardening, Deploy | §28 acceptance + §34 DoD + VPS notes |

> **Ordering note:** PRD §31 lumps LLM into its Phase 5. This plan promotes the LLM router to Phase 7 (before News and Scoring) so both downstream phases consume it without rework. PRD §31 leaves DB and infra implicit; this plan makes them Phase 0 and Phase 1.

---

## Phase 0 — Project Foundation

**Goal:** Reproducible dev environment + minimal FastAPI service.

### Scope (in)
- Repo layout under `app/` for code, `tests/` for tests, `alembic/` for migrations (added in Phase 1), `deploy/` for prod-only files (added in Phase 13).
- `pyproject.toml` (managed by `uv`), lockfile committed.
- `docker-compose.yml` with services: `app`, `postgres:16`, `redis:7`, plus a separate `playwright` service (used in Phase 4).
- `Dockerfile` (app) and `Dockerfile.playwright` (browser-capable).
- FastAPI bootstrap with `GET /health` returning 200.
- `pydantic-settings` config loading from `.env`.
- `structlog` JSON logging.
- `pre-commit` running `ruff`, `black`, `mypy`.
- README explaining bring-up.

### Out of scope
- DB models (Phase 1), Telegram bot (Phase 2), any business logic.

### Packages
```
fastapi, uvicorn[standard], pydantic, pydantic-settings,
structlog, python-dotenv, httpx, tenacity,
ruff, black, mypy, pre-commit,
pytest, pytest-asyncio, pytest-mock, respx, freezegun
```

### Files to create
- `pyproject.toml`, `uv.lock`, `.gitignore`, `.dockerignore`, `.env.example`
- `docker-compose.yml`, `Dockerfile`, `Dockerfile.playwright`
- `.pre-commit-config.yaml`
- `app/main.py`, `app/core/config.py`, `app/core/logging.py`
- `tests/conftest.py`
- `README.md`

### Tests
- `tests/test_health.py` — 200 OK on `/health`.

### Definition of Done
- `docker compose up` brings up app + postgres + redis.
- `curl localhost:8000/health` returns 200.
- `pytest` runs (1 test passes).
- `pre-commit run --all-files` passes.

---

## Phase 1 — Database & Encryption

**Goal:** Persistence layer matching PRD §24, with per-user encrypted secrets.

### Scope (in)
- SQLAlchemy 2.0 async + `asyncpg` engine.
- Alembic initialized; first migration creates all 7 tables.
- Models for: `users`, `cron_jobs`, `workflow_runs`, `candidates`, `option_contracts`, `recommendations`, `feedback_events` (stub for V2).
- Repository module per table with typed CRUD.
- `app/core/crypto.py` — Fernet wrapper. Master key from env (`APP_ENCRYPTION_KEY`). API key columns store ciphertext bytes (`text` in PRD; `bytea` is fine too — pick one and stick with it).
- Indexes: `users.telegram_chat_id` (unique), `cron_jobs.user_id`, `workflow_runs(user_id, status)`, `recommendations(user_id, created_at desc)`.
- JSONB for `key_evidence_json`, `key_concerns_json` per §24.6.
- Store both `timezone_label` and `timezone_iana` per §8.2.

### Out of scope
- API-key validation (lives in Phase 2 — needs the bot UX to surface failures).

### Packages
```
sqlalchemy[asyncio]>=2.0, asyncpg, alembic, cryptography
```

### Files to create
- `app/db/base.py`, `app/db/session.py`
- `app/db/models/{user.py,cron_job.py,workflow_run.py,candidate.py,option_contract.py,recommendation.py,feedback_event.py}`
- `app/db/repositories/{user_repo.py,cron_repo.py,run_repo.py,candidate_repo.py,contract_repo.py,recommendation_repo.py,feedback_repo.py}`
- `app/core/crypto.py`
- `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py`

### Tests
- Encrypt → decrypt roundtrip; wrong-key decrypt fails.
- CRUD smoke test for each repository (against a test database, e.g. spun-up via `pytest-postgresql` or just a docker test DB).
- Migration up + down.

### Definition of Done
- `alembic upgrade head` creates all 7 tables exactly as specified in PRD §24.
- Encryption util has property-based tests.
- All repositories pass CRUD tests.

---

## Phase 2 — Telegram Bot, Onboarding & Settings

**Goal:** PRD §10 (UX) + §11 (onboarding) + §8 (settings) end-to-end.

### Scope (in)
- aiogram 3.x dispatcher; long-polling in dev, webhook-ready code path for prod.
- Persistent reply keyboard for the §10.2 main menu.
- FSM onboarding (every step from §11.1):
  1. Welcome message
  2. Account size (number)
  3. Risk profile (Conservative / Balanced / Aggressive)
  4. Timezone (PT/MT/CT/ET/AT/NT — labels per §8.2; backend stores IANA per §8.2 mapping)
  5. Broker (Wealthsimple / IBKR / Questrade / Other)
  6. Strategy permission (Long only / Short only / Long and short)
  7. OpenRouter API key (mandatory)
  8. Alpaca key + secret (skippable; explain yfinance fallback as PRD §11.1 step 9 says)
  9. Alpha Vantage key (optional)
  10. Default cron job auto-created: Monday 10:30 AM `America/Toronto` (§12.1, §8.3) — actual scheduler firing wired in Phase 3
  11. Setup summary
  12. Confirm → main menu
- Settings screens (§10.5) for every editable field, including key replacement / removal.
- API-key validation per §7.1: lightweight test call (OpenRouter ping; Alpaca account endpoint; Alpha Vantage quote). Reject and re-prompt on failure.
- Tone helper enforcing §10.6 — light emoji, friendly, never hype, never cold.
- Inline buttons after a future recommendation (wired here as no-op handlers, fully populated in Phase 11): "I bought it" / "I skipped it" → write to `feedback_events`.

### Out of scope
- Cron firing (Phase 3); recommendation generation (Phase 11).

### Packages
```
aiogram>=3.4, redis (FSM storage), python-dateutil
```
(`zoneinfo` is stdlib in Python 3.12, no `pytz` needed.)

### Files to create
- `app/telegram/bot.py` — dispatcher bootstrap
- `app/telegram/keyboards/{main_menu.py,settings.py,confirm.py}`
- `app/telegram/handlers/{start.py,onboarding.py,settings.py,menu.py,help.py}`
- `app/telegram/fsm/onboarding_states.py`
- `app/services/api_key_validators.py` — `OpenRouterValidator`, `AlpacaValidator`, `AlphaVantageValidator`
- `app/services/user_service.py` — encrypts keys before persisting
- `app/telegram/tone.py` — pre-send tone linter

### Tests
- FSM state transitions for the full onboarding (use aiogram test utilities + a fake Telegram update factory).
- Each validator: success and failure paths, mocked via `respx`.
- Saving a user encrypts each key correctly; reading decrypts.
- Settings edit roundtrip.
- Tone linter rejects "guaranteed", flags missing emoji-friendly framing on long messages.

### Definition of Done
- A fresh Telegram chat completes onboarding against local Postgres.
- Bad keys are rejected with the specified prompts and the user can retry.
- All §8.1 settings reachable and editable via buttons (no slash commands required).

---

## Phase 3 — Schedule, Cron & Run-Lock

**Goal:** PRD §3 + §12, with the §12.5 duplicate-run rule.

### Scope (in)
- APScheduler 3.x with SQLAlchemy jobstore so cron persists across restarts.
- Per-user multiple cron jobs (§12.2). Add / Edit / Delete / Pause / Resume from Telegram (§10.4, §12.3).
- Default cron created at the end of onboarding: Monday 10:30 AM `America/Toronto`.
- DST-correct firing using IANA timezones.
- Manual "🚀 Run Scan Now" button from the main menu (§3.2, §10.2).
- Redis-backed per-user run-lock. If a scan is running for that user, second trigger replies with the §12.5 message verbatim.
- Workflow runner stub: creates a `workflow_runs` row with `status="running"` and finishes with `status="success"` (or `"failed"`), but the body is a placeholder. The real pipeline is filled in in Phase 11.

### Out of scope
- Pipeline body (Phase 11).

### Packages
```
apscheduler>=3.10
```
(`redis` already added in Phase 2.)

### Files to create
- `app/scheduler/scheduler.py` — APScheduler bootstrap, jobstore wiring
- `app/scheduler/jobs.py` — `run_workflow(user_id, trigger_type)` placeholder
- `app/services/run_lock.py` — Redis lock helper
- `app/telegram/handlers/schedule.py` — Schedule UI

### Tests
- Schedule fires at the right local time (use `freezegun` and frozen scheduler).
- DST transition: Sunday 02:30 in spring-forward week fires exactly once.
- Concurrent run blocked: second call within lock window returns the §12.5 message.
- Pause then resume.
- Multiple cron jobs per user fire independently.

### Definition of Done
- A user can create three different crons via buttons; all fire at correct local times.
- Manual + scheduled overlap shows the duplicate-run message; only one workflow run row is created.

---

## Phase 4 — TradingView Browser Automation & Candidate Validation

**Goal:** PRD §5 + §14.

### Scope (in)
- Playwright (Python, async). Headed in dev, headless in prod via env flag.
- Open `https://www.tradingview.com/screener/`, apply "Upcoming earnings date = Next week", sort market cap descending, pick top 5 rows.
- Extraction strategy order from §5.3:
  1. Browser accessibility snapshot.
  2. Visible table text.
  3. Screenshot + vision (uses Phase 7's Gemini route — for Phase 4 this path is stubbed and returns NotImplemented; wired live after Phase 7 lands).
  4. Manual fallback (admin-only entry point, optional).
- Fields per §5.4: required (Ticker, Company, Market cap, Earnings date), preferred (price, change %, volume, sector).
- Backup earnings calendar (§14.2): `yfinance` and Finnhub free tier (or Alpha Vantage if user provided a key). Reconcile and reject only on §14.3 hard reasons.
- §26.1 retry/clean-context behaviour. If TradingView fails and backup is used, the workflow run carries a flag that Phase 11 will surface in Telegram with the §26.1 warning text.
- **Hard rule (§5.3):** never use hidden TradingView APIs.

### Out of scope
- Actually wiring TradingView into a real workflow run (that happens in Phase 11). For Phase 4 the public entry point is `candidate_service.get_top_five()` callable from a test or admin tool.

### Packages
```
playwright, beautifulsoup4, lxml, finnhub-python (optional)
```
(`yfinance` arrives in Phase 5 but can be added here if convenient.)

### Files to create
- `app/services/tradingview/{browser.py,parser.py,extractor.py}`
- `app/services/earnings_calendar/{yfinance_source.py,finnhub_source.py,reconciler.py}`
- `app/services/candidate_service.py`
- `tests/fixtures/tradingview/*.html` — captured snapshots for parser tests

### Tests
- Parser unit tests against fixture HTML.
- Reconciler conflict tests (TradingView vs yfinance vs Finnhub).
- Mock-browser path returns the expected 5 rows.
- Live integration test gated behind `RUN_LIVE_BROWSER=1` so CI skips it.

### Definition of Done
- `await candidate_service.get_top_five()` returns 5 validated rows in dev (live Playwright session).
- TradingView failure path correctly switches to backup and tags the run.

---

## Phase 5 — Market Data Service

**Goal:** PRD §6.1, §15.1 (everything the scoring engine needs about each stock).

### Scope (in)
- `yfinance` for OHLCV, market cap, sector classification.
- Alpha Vantage when user provided a key (§6.4): company overview, news sentiment endpoint, time-series cross-check.
- Indicators: 1d / 5d / 20d / 50d returns; volume vs 20-day average; relative strength vs SPY, QQQ, sector ETF.
- Redis cache, key `mkt:{ticker}:{date}`, TTL = end of US trading day.
- `tenacity` retry on transient failures.
- Source-conflict detection per §27.6 — record into the candidate's data-confidence accumulator.

### Packages
```
yfinance, alpha-vantage, pandas, numpy
```

### Files to create
- `app/services/market_data/{yf_client.py,av_client.py,indicators.py,cache.py,service.py,types.py}`
- `app/services/market_data/types.py` defines `MarketSnapshot` (typed dataclass).

### Tests
- Indicator math against fixed CSV fixtures.
- Cache hit / miss.
- AV-missing path still returns a valid snapshot.
- Conflict detection drops confidence with a logged reason.

### Definition of Done
- `await market_data.fetch(ticker)` returns a `MarketSnapshot` with every field downstream needs.

---

## Phase 6 — Options Service (Alpaca primary, yfinance fallback)

**Goal:** PRD §6.1–6.3 + §19.

### Scope (in)
- `alpaca-py` for Options Snapshots: full chain, bid / ask, latest trade, Greeks + IV when available.
- `yfinance` `Ticker.option_chain` fallback when Alpaca creds missing or fail (§6.3).
- Same-day cache (§19.6); freshness rule per the table in §19.6.
- Source-conflict detection: if Alpaca and yfinance disagree on price by more than a threshold, downgrade confidence and log.
- Per-contract enrichment: mid, spread %, breakeven, liquidity score (§23.4 fields).
- Filter functions returning `(passed: bool, penalty_pts: int, reason: str)` for:
  - Hard rejects (§19.1)
  - Balanced thresholds (§19.2)
  - Spread rules (§19.4) including the absolute-spread table for cheap contracts (§19.4)
- Strategy permission (long / short / both) enforced when filtering candidate contracts.

### Packages
```
alpaca-py
```

### Files to create
- `app/services/options/{alpaca_client.py,yfinance_client.py,fallback_chain.py,filters.py,service.py,types.py}`
- `OptionsChain` and `OptionContract` typed dataclasses in `types.py`.

### Tests
- Alpaca client mocked via `respx`.
- Fallback path triggers when Alpaca returns 401 or empty.
- Spread / liquidity filter tests as a parametrized table.
- Conflict-detection test.

### Definition of Done
- `await options_service.get_chain(ticker, expiry_window)` returns a normalized chain populated with every §23.4 field.
- Filters reject only the §19.1 cases; everything else stays in the chain with possible soft penalties.

---

## Phase 7 — LLM Router (OpenRouter, Opus 4.7 Thinking, Gemini 3.1 Flash)

**Goal:** PRD §7 fully implemented before News, Scoring, and Recommendation.

### Scope (in)
- OpenRouter HTTP client. Per-user API key decrypted at call time.
- Two named routes (env-configurable):
  - `MARKET_ANALYSIS_MODEL` → Opus 4.7 Thinking (§7.2)
  - `LIGHTWEIGHT_MODEL` → Gemini 3.1 Flash (§7.3)
- Structured outputs via pydantic schemas to enforce §7.5 input discipline.
- Token + cost telemetry.
- Retry with backoff; on key failure, raise a typed exception that Phase 2's settings UI catches and prompts the user to update the key (§7.1).
- **Code-level invariant for §7.4:** the router exposes only two functions:
  - `summarize(prompt, context) -> str` — light model only
  - `decide(structured_input: pydantic.BaseModel) -> StructuredDecision` — heavy model only
  - `decide()` cannot be invoked against the light model; tested.

### Packages
```
httpx (already in Phase 0); tiktoken (optional, for cost estimation)
```
Use raw `httpx` for OpenRouter (its OpenAI-compatible endpoint works without the `openai` SDK).

### Files to create
- `app/llm/router.py`, `app/llm/schemas.py`, `app/llm/telemetry.py`
- `app/llm/prompts/{decide_recommendation.md,summarize_news.md,draft_telegram.md}`

### Tests
- OpenRouter mocked via `respx`.
- Structured output validation rejects malformed responses.
- Invalid-key path raises the typed exception.
- Attempting `decide()` against the light model raises `ValueError`.

### Definition of Done
- Both router functions work end-to-end against a real OpenRouter sandbox key in dev.

---

## Phase 8 — News & Web Research

**Goal:** PRD §22.

### Scope (in)
- Web search abstraction. Default provider: DuckDuckGo via `duckduckgo-search` (free). Tavily / SerpAPI behind an interface for later.
- Article fetcher with `trafilatura` for clean text.
- Company IR-page fallback when search yields little (§6.1).
- Gemini 3.1 Flash summarization producing the §22.4 structured `NewsBrief`:
  - Bullish evidence
  - Bearish evidence
  - Neutral / contextual evidence
  - Key uncertainty
  - News confidence (0–100)
- Per-ticker news bundle attached to the run.

### Packages
```
duckduckgo-search, trafilatura
```

### Files to create
- `app/services/news/{search.py,fetcher.py,summarizer.py,service.py,types.py}`

### Tests
- Summarizer schema validation (mock LLM with respx).
- Cache.
- Missing-news path downgrades news confidence.
- Offline fixture run end-to-end.

### Definition of Done
- `await news_service.brief(ticker)` returns a `NewsBrief` matching §22.4.

---

## Phase 9 — Scoring Engine + Data Confidence

**Goal:** PRD §15, §16, §17, §18, §20, §27.

### Scope (in)
- **Direction Score (§15.3.1)** — 8-factor weighted: trend (20), RS (15), volume (10), news / catalyst (15), earnings expectation context (15), market / sector (10), price structure (10), data confidence (5). Range 0–100.
- **Contract Opportunity Score (§15.3.2)** — 7-factor weighted: breakeven (20), liquidity (15), expiry fit (15), strike fit (15), IV setup (15), premium / risk fit (10), direction compatibility (10).
- **Final Score** = `0.45 × Direction + 0.55 × Contract` (§15.3.3).
- Strategy mapping (§16.3): bullish → {long call, short put}; bearish → {long put, short call}; respect user `strategy_permission`.
- **Expiry logic (§17):**
  - Window: same day after earnings to 30 days after earnings.
  - BMO → same-day expiry allowed if it expires after the earnings event.
  - AMC → earliest valid expiry is the next available *after* the event.
  - Strategy preferences from §17.4.
- **Strike selector (§18.3):** evaluates ATM, slight ITM, slight OTM, moderate OTM, best-liquidity strike, best-breakeven strike. Picks the highest contract score.
- **Hard vetoes (§15.3.5)** and **soft penalties (§15.3.6)** as a structured rules engine returning `(score_delta, reason)`.
- IV / expected-move / breakeven calc (§20).
- **Data confidence score (§27.2)** with critical-field override (§27.4), missing-Greeks rule (§27.5), source-conflict rule (§27.6).
- **PRD §4.2 invariant:** never produce both a call and a put for the same stock — guaranteed by strategy mapping returning a single chosen strategy per stock.

### Packages
None new.

### Files to create
- `app/scoring/{direction.py,contract.py,final.py,vetoes.py,penalties.py,strategy_select.py,expiry.py,strike.py,confidence.py,types.py}`

### Tests
- Golden tables for each scorer (input → expected score).
- Expiry rule under BMO and AMC scenarios.
- Veto matrix: each hard-veto condition triggers correctly.
- Soft-penalty stacking accumulates correctly.
- Confidence override blocks recommendation despite numerical pass.
- Strategy mapping never returns both a call and a put for the same ticker.

### Definition of Done
- Given a `MarketSnapshot + OptionsChain + NewsBrief`, the engine outputs the chosen strategy + chosen contract + Direction Score + Contract Score + Final Score + reason list.

---

## Phase 10 — Risk & Position Sizing

**Goal:** PRD §9.

### Scope (in)
- Long sizing (§9.2): `max_loss = ask × 100`; `trade_budget = account × risk_pct`; `qty = floor(trade_budget / max_loss)`. Reproduce the §9.2 example exactly.
- Short put sizing (§9.3, §9.4): `qty = floor(max_short_notional / (strike × 100))` with risk-profile caps from the §9.4 table.
- Short call sizing: returns `qty` but max-loss field renders as "Undefined for naked short call" or "Broker/margin dependent" per §9.3.
- Risk-profile defaults from §9.1; user can edit later (post-V1).
- Strategy-permission gate at sizing boundary too (defense in depth).

### Files to create
- `app/services/sizing.py`
- `app/services/sizing_types.py` — `SizingResult` typed dataclass.

### Tests
- Reproduce the exact §9.2 example: $5,000 / Balanced / $0.85 ask → 1 contract.
- Zero-quantity result returns `watch_only=True` rather than failing.
- Short-call labeling renders the correct max-loss text.
- Strategy-permission gate blocks short sizing when user disabled shorts.

### Definition of Done
- `sizing.size(...)` returns `(quantity, max_loss_text, account_risk_pct, broker_verification_required, watch_only)`.

---

## Phase 11 — Recommendation Pipeline & Telegram Output

**Goal:** PRD §3.1, §13, §21, §32.

### Scope (in)
- Pipeline orchestrator that, per workflow run, executes:
  1. TradingView candidate extraction (Phase 4)
  2. Candidate validation (Phase 4)
  3. Market data fetch (Phase 5)
  4. News brief (Phase 8)
  5. Options chain fetch + filter (Phase 6)
  6. Scoring per candidate (Phase 9)
  7. Sizing per candidate (Phase 10)
  8. LLM `decide()` over the structured 5-candidate bundle (Phase 7)
  9. Final pick or no-trade (§21.2, §21.3)
- Threshold tiers (§15.3.4, §21.3):
  - Final ≥ 78 → "Strong recommendation"
  - 68–77 → "Recommendation"
  - 60–67 → "Watchlist only" (still send the message, but no quantity)
  - < 60 → No-trade with watchlist names
- Message templates implementing §13.1 (main), §13.2 (no-trade), §13.3 (short-option labeling). Gemini polishes wording, Opus output supplies facts.
- Inline buttons after the recommendation (§10.3): "🔍 Why this?", "⚖️ Risk / Sizing", "📈 Alternatives", "📘 Save Note", "✅ I bought it", "❌ I skipped it".
- Status messages from §32 (pre-scan friendly note + post-scan summary).
- Tone linter applied to every outgoing string (and back-applied to Phase 2/3 messages).

### Packages
None new.

### Files to create
- `app/pipeline/orchestrator.py`
- `app/pipeline/steps/{candidates.py,market_data.py,news.py,options.py,scoring.py,sizing.py,decide.py}`
- `app/telegram/templates/{main_recommendation.py,no_trade.py,short_option.py,status.py}`
- `app/telegram/handlers/recommendation.py` — handles the inline buttons

### Tests
- End-to-end pipeline against fixtures (no live network) producing a recommendation card.
- No-trade path.
- Watchlist-only path.
- Short-call template renders "Broker/margin dependent" / "Undefined for naked short call".
- Tone linter rejects forbidden phrases (e.g. "guaranteed").
- §13.1 template structurally matches the PRD exactly.

### Definition of Done
- Tapping "🚀 Run Scan Now" with seeded fixtures produces a Telegram-ready message that matches §13 exactly.
- All inline buttons return the correct view.

---

## Phase 12 — Logging & Evidence Cards

**Goal:** PRD §23, V2 readiness.

### Scope (in)
- Per-run JSON snapshots (§23.5):
  - `run_summary.json`
  - `candidate_cards.json`
  - `option_contracts.json`
  - `recommendation_card.json`
  - `telegram_message.txt`
  Stored in DB and optionally archived to disk under `var/runs/{run_id}/`.
- Recommendation card fields (§23.2) populated from pipeline outputs.
- Per-candidate logs (§23.3) and per-contract logs (§23.4) — including rejected contracts with `rejection_reason`.
- Telegram "📘 Logs" handler (§10.2) showing the last N runs with pagination.
- V2 prep: data shape sufficient for the future Feedback Agent (§23.6, §30.1).

### Files to create
- `app/services/logging_service.py`
- `app/telegram/handlers/logs.py`

### Tests
- Every §23.2/3/4 field present.
- Rejected contracts present with reasons.
- JSON archive readable.
- Logs handler paginates correctly.

### Definition of Done
- Every run produces a complete card readable by a future V2 Feedback Agent.

---

## Phase 13 — End-to-End Tests, Hardening, Deploy Polish

**Goal:** PRD §26 hardening + §28 acceptance + §34 V1 DoD.

### Scope (in)
- Acceptance tests covering §28.1–28.4.
- Error scenarios from §26:
  - TradingView failure → backup calendar + warning message verbatim from §26.1.
  - Alpaca failure → yfinance fallback + confidence drop.
  - Critical field missing → no-trade with the §27.4 reason.
- Test matrix from §31 Phase 7:
  - Bad OpenRouter key
  - Bad Alpaca key/secret
  - Missing option chain
  - Long-call / long-put / short-put / short-call paths each end-to-end
  - DST cron transition
  - Multiple users isolated
- VPS deploy notes: production compose file, secrets handling, Playwright headless, log rotation, Postgres backup.
- Final pass against the §34 DoD checklist.

### Files to create
- `tests/e2e/{test_workflow_strong.py,test_workflow_no_trade.py,test_workflow_watchlist.py,test_strategies.py,test_failures.py,test_dst.py}`
- `deploy/README.md`
- `deploy/docker-compose.prod.yml`

### Definition of Done
- Every line of PRD §34 is checked off.
- All §28 acceptance criteria pass automated tests.

---

## Cross-cutting concerns (apply in every phase)

- **Error handling rule (§26.3):** non-critical missing data → continue with confidence penalty; critical missing data → reject candidate or contract.
- **Free-data-first (§6):** never invent data. If all sources fail for a critical field, downgrade confidence or return no-trade.
- **Tone (§10.6):** every user-facing string passes the tone linter (Phase 11). Forbidden words: "guaranteed", "execute according to parameters", etc.
- **No-commands UX (§10.1):** every flow reachable via buttons; slash commands are fallback only.
- **PRD §4.2 must-nots** as code-level invariants:
  - Never recommend both call and put for the same stock — guaranteed by Phase 9 strategy mapping.
  - No broker SDKs in dependencies.
  - Never invent missing data — guaranteed by §27.4 critical-field override.

## Quick command reference (for future sessions)

```bash
# bring up dev env
docker compose up -d

# run migrations
docker compose exec app alembic upgrade head

# run tests
docker compose exec app pytest -q

# pre-commit
pre-commit run --all-files

# launch the bot in long-poll mode (after Phase 2)
docker compose exec app python -m app.telegram.bot
```

## How to use this document

1. Read the target phase top-to-bottom.
2. Confirm the "Out of scope" list is truly out of scope for this session.
3. Install the listed packages.
4. Create the listed files.
5. Implement until every item under "Tests" is green.
6. Verify against "Definition of Done".
7. Move to the next phase only after DoD is met.
