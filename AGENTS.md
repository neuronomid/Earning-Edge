# AGENTS.md

## Purpose

This file stores repo-specific operating instructions for Codex agents working in
`Earning-Edge`.

## TradingView Agent Account

- Service: TradingView
- Sign-in method: Email/password
- Email: `edgeagent@atomicmail.io`
- Password: `Edgeagent2026!`

## Required Behaviour

- Any agent that needs to sign in to TradingView for this repo must use the
  TradingView account above.
- Do not use hidden or private TradingView APIs. Only interact through the
  visible browser session, matching the PRD and Plan requirements.
- Prefer persistent browser/session state when possible so repeated phase-4
  debugging does not keep re-prompting for sign-in.
- If live browser checks are needed for phase 4, use the TradingView screener at
  `https://www.tradingview.com/screener/`, apply the `Upcoming earnings date =
  Next week` filter, sort by `Market cap` descending, and work from the top five
  visible rows.

## Phase 4 Notes

- The public phase-4 entry point is `app/services/candidate_service.py`.
- Keep browser automation retry-safe:
  1. retry the page once
  2. retry with a clean browser context
  3. fall back to backup earnings sources if TradingView is still unusable
- If TradingView fails and backup candidates are used, surface the PRD warning:
  `⚠️ TradingView did not load correctly, so I used backup earnings data for this scan.`
