# Earning Edge

Telegram-based agent that scans upcoming earnings and recommends a single options
contract per weekly run. See [`docs/PRD1.md`](docs/PRD1.md) for the product spec
and [`docs/Plan1.md`](docs/Plan1.md) for the phased build plan.

## Status

Phase 0 — Project Foundation (FastAPI skeleton + Docker dev env).

## Stack

- Python 3.12, FastAPI
- `uv` for dependency management
- Postgres 16, Redis 7
- Playwright (Phase 4+)
- Docker Compose for local dev

## Quick start

```bash
cp .env.example .env

# one-command local dev startup
./dev.sh

# run tests inside the container
docker compose exec app pytest -q

# pre-commit (host)
uv sync
uv run pre-commit install
uv run pre-commit run --all-files
```

`./dev.sh` syncs the host virtualenv, starts Postgres + Redis, applies
migrations before the app boots, waits for the API health check, and then starts
the Telegram bot with localhost database/redis overrides.

The `playwright` service is defined under the `browser` profile and only starts
when explicitly requested (`docker compose --profile browser up playwright`).
It will be wired into the workflow in Phase 4.

## Layout

```
app/            application code
  core/         config + logging
  main.py       FastAPI entry point
tests/          pytest suite
docs/           PRD + Plan
```

## Development without Docker

```bash
uv sync
uv run uvicorn app.main:app --reload
uv run pytest -q
```
