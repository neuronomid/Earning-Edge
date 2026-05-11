# Earning Edge Dashboard

Standalone Next.js dashboard for the existing `Earning Edge` recommendation engine.

## What it does

- Mirrors the Telegram recommendation structure with a richer visual layout
- Shows the lead recommendation, ranked alternatives, and workflow run history
- Includes settings, schedule, API status, and model status panels
- Adds a local paper-trading simulator with persistent browser storage

## Why it is isolated

This dashboard lives in its own `dashboard/` workspace so the current FastAPI,
Telegram, Finviz, and database flow can remain untouched.

## Run it

```bash
cd dashboard
npm install
npm run dev
```

Then open `http://localhost:3000`.
