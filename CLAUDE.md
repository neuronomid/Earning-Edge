# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Earning Edge is a Telegram-based agent that scans upcoming earnings and recommends a single options contract per weekly run. The product spec lives in `docs/PRD1.md` and the phased build plan in `docs/Plan1.md`.

Stack: Python 3.12 / FastAPI, `uv` for deps, Postgres 16, Redis 7, SQLAlchemy async + Alembic, APScheduler, aiogram (Telegram), Playwright (Finviz scraping), OpenRouter (LLM).

## Common commands

Local dev (full stack — Postgres, Redis, migrations, FastAPI app, Telegram bot):

```bash
cp .env.example .env   # first time
./dev.sh
```

`./dev.sh` syncs `.venv` from `uv.lock` (frozen), starts compose services, runs `alembic upgrade head`, waits for `/health`, then launches the Telegram bot on the host with localhost overrides (`REDIS_PORT=16379`, `POSTGRES_PORT=15432`). It writes the bot PID to `var/run/dev-bot.pid` and kills any stray previous bot before starting.

Without Docker (API only):

```bash
uv sync
uv run uvicorn app.main:app --reload
```

Tests (pytest is async-mode auto):

```bash
docker compose exec app pytest -q          # in the running container
uv run pytest -q                           # from the host (needs Postgres reachable)
uv run pytest tests/test_scoring_engine.py # single file
uv run pytest tests/test_scoring_engine.py::test_name  # single test
```

`tests/conftest.py` skips DB tests if Postgres isn't reachable. It points the test session at the `earning_edge_test` DB on `localhost`; bring up `docker compose up -d postgres` and create the DB if running tests outside the app container.

Lint / format / type-check (also wired into pre-commit):

```bash
uv run ruff check .
uv run ruff format .
uv run black .
uv run mypy app
uv run pre-commit run --all-files
```

Migrations:

```bash
docker compose run --rm --no-deps app alembic upgrade head
docker compose run --rm --no-deps app alembic revision -m "..." --autogenerate
```

Browser/Finviz container is gated behind the `browser` profile — it does **not** start by default:

```bash
docker compose --profile browser up playwright
```

## Architecture

The system is a single weekly pipeline run, scheduled per user, that turns "upcoming earnings" into one options recommendation (or a "no trade" verdict). All persistence is async SQLAlchemy + Alembic; all external fan-out is async.

### Run lifecycle

`app/scheduler/` owns time. `SchedulerService` boots an `AsyncIOScheduler` with a `SQLAlchemyJobStore` (in-process `MemoryJobStore` under `APP_ENV=test`) and reconciles cron rows from the `cron_jobs` table → APScheduler jobs on startup. Each tick calls `app.scheduler.jobs.run_workflow`, which goes through `WorkflowRunner`:

1. Acquire a per-user Redis lock via `app/services/run_lock.py` (TTL `WORKFLOW_RUN_LOCK_TTL_SECONDS`, default 900s). If the lock is held, return `already_running` — the user gets a friendly Telegram message instead of a duplicate run.
2. Insert a `WorkflowRun` row with `status="running"`.
3. Hand off to `PipelineOrchestrator` (`app/pipeline/orchestrator.py`).
4. On any exception, mark the run `failed` with the message; always release the lock in `finally`.

The orchestrator is constructed once via `@lru_cache` (`get_pipeline_orchestrator`). Treat its constructor signature as the DI seam — every step has a default implementation but accepts an injected one for tests.

### Pipeline (`app/pipeline/`)

`PipelineOrchestrator.run()` executes these steps in `app/pipeline/steps/` in this order:

1. **Candidates** (`candidates.py` → `app/services/candidate_service.py`) — Finviz is the primary screener (see "Finviz rules" below). On Finviz failure, fall back to `FinnhubEarningsSource` / `YFinanceEarningsSource` and surface the `FINVIZ_FALLBACK_WARNING` text on the final Telegram message.
2. **Per-candidate fan-out**, run with `asyncio.gather`:
   - **Market data** (`app/services/market_data/`) — Alpha Vantage + yfinance with caching and confidence notes. Failures degrade to a `_fallback_market_snapshot` with a `-20` confidence delta rather than aborting the candidate.
   - **News** (`app/services/news/`) — DuckDuckGo search → trafilatura/BS4 fetch → LLM summary via the `summarize` route. `LLMAuthenticationError` flips `has_valid_openrouter_api_key=False` for that user's downstream context.
   - **Options chain** (`app/services/options/`) — Alpaca primary, yfinance fallback. Empty chain is tolerated; the candidate gets no `chosen_contract`.
3. **Scoring** (`app/scoring/`) — Pure functions over a `CandidateContext`. Composes direction (`direction.py`), strategy permission filter (`strategy_select.py`), strike picker (`strike.py`), per-contract score (`contract.py`), data confidence (`confidence.py`), vetoes (`vetoes.py`), penalties (`penalties.py`), then a final blended score (`final.py`: `0.45 * direction + 0.55 * contract`).
4. **Sizing** (`app/services/sizing.py`) — Risk-budget-driven contract count. `SizingError` / `SizingPermissionError` degrade to a watch-only `_fallback_sizing` rather than failing the run.
5. **Decision** (`app/pipeline/steps/decide.py`) — Top `DECISION_FINALIST_LIMIT=4` candidates by `(final_score, confidence, direction)` are sent to the heavy LLM via the `decide` route. The decision is structured (`StructuredDecision`) and includes `action ∈ {trade, watchlist, no_trade}`, a chosen ticker + contract, and reasoning.
6. **Persist + notify** — Every analysed candidate and every considered contract is written to `candidates` / `option_contracts`. The selected one becomes a `Recommendation` linked to the run. Telegram messages are then dispatched via `AiogramNotifier` and tracked by `LoggingService`.

`PipelineOutcome` is the contract between the orchestrator and presentation/persistence — keep it frozen and additive.

### LLM routing (`app/llm/router.py`)

Two — and only two — public routes:

- `summarize` → lightweight model (`LIGHTWEIGHT_MODEL`, default `google/gemini-3.1-flash-lite-preview`) for browsing/news/draft messages.
- `decide` → heavy reasoning model (`MARKET_ANALYSIS_MODEL`, default `anthropic/claude-opus-4.7`) for the final trade decision.

The PRD §7.4 separation is enforced at call time: invoking `decide` against the lightweight model raises `ValueError`. **Do not append `-thinking` to model IDs** — OpenRouter rejects it. Thinking mode is enabled via the `reasoning` parameter inside the router, not via the model name.

### Database (`app/db/`)

- `Base = DeclarativeBase`, models in `app/db/models/`, repositories in `app/db/repositories/`.
- Async engine + sessionmaker are `@lru_cache`'d in `session.py`. Tests reset that cache via `reset_engine_cache()` when they swap engines.
- Migrations live in `alembic/versions/`. The numbering has a deliberate fork at `0004_*` (`recommendation_parent_chain` and `strategy_source` are siblings) — keep that history intact, do not renumber.
- User secrets (`openrouter_api_key`, `alpha_vantage_api_key`, `alpaca_*`) are stored Fernet-encrypted using `APP_ENCRYPTION_KEY`; always go through `app.services.user_service.decrypt_or_none` rather than reading the encrypted column directly.

### Telegram (`app/telegram/`)

`bot.py` is the long-polling entry point (`python -m app.telegram.bot`). FSM storage is Redis in dev/prod, in-memory under `APP_ENV=test`; `build_runtime_storage` pings Redis on startup and falls back to memory in dev (raises in production). Router order in `build_dispatcher` is significant — onboarding must run before the menu router so a user mid-onboarding doesn't trip the main-menu reply handler.

`tone.py` + `enforce_tone` gate every outbound message. The orchestrator's `AiogramNotifier.send_text` calls `enforce_tone` before sending; if you add a new message path, route it through the notifier or call `enforce_tone` yourself.

### Run-lock + Redis

`app/services/run_lock.py` uses a single `Redis.from_url` client cached by `lru_cache`. The lifespan in `app/main.py` calls `close_redis_client()` on shutdown — preserve that ordering when adding new shutdown hooks.

## Conventions

- **Async everywhere.** No sync DB sessions, no `requests` (use `httpx`), no blocking I/O inside pipeline steps.
- **Decimal for money.** Prices, account size, premiums, risk percents are `decimal.Decimal`. Don't introduce floats into scoring/sizing math.
- **Frozen dataclasses** are the default for the data passed between steps (`CandidateContext`, `PipelineCandidate`, `PipelineOutcome`, `MarketSnapshot`, `NewsBundle`, etc.). Use `dataclasses.replace` rather than mutating.
- **Fallbacks beat aborts.** Each pipeline stage has a documented fallback path (see `_fallback_market_snapshot`, `_fallback_news_bundle`, `_fallback_sizing`). Prefer adding a fallback + confidence penalty over raising out of `_analyze_candidate`.
- **Config via `get_settings()`** (cached). `Settings` reads `.env`; do not read environment variables directly in app code.
- Ruff (`E,F,W,I,B,UP,N,ASYNC,S,RUF`), black, and mypy `strict` are all enforced. `pyproject.toml` excludes `.agents`, `.claude`, `docs`, `var`, and `alembic/versions` from formatting/lint.

## Finviz rules (from `AGENTS.md`)

- The retired phase-4 screener is gone. Do not reintroduce it.
- Finviz is the **primary** visible screener. Use the URL `https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap` and the top five visible rows.
- Browser automation must stay retry-safe and stateless: (1) retry the page once, (2) retry with a clean browser context, (3) fall back to backup earnings sources. No login or persistent-auth assumptions.
- Public phase-4 entry point: `app/services/candidate_service.py`. The Finviz client lives in `app/services/finviz/`.
- When falling back to backup data, surface the warning `⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.` (constant `FINVIZ_FALLBACK_WARNING`).

## Branch policy

This worktree is on `claude/add-claude-documentation-ftKDv`. Per the harness instructions, develop and push to that branch; do not push elsewhere without explicit permission, and do not open a PR unless the user asks.
