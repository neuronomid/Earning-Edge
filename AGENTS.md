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
- Do not sign out of the TradingView account during phase-4 work unless the
  user explicitly asks for it.
- Reuse the same persistent browser profile and saved auth state when possible
  before attempting a fresh TradingView sign-in.
- If live browser checks are needed for phase 4, use the TradingView screener at
  `https://www.tradingview.com/screener/`, apply the `Upcoming earnings date =
  Next week` filter, and work from the top five visible rows.
- After applying `Upcoming earnings date = Next week`, do not change any other
  TradingView filters or sorting unless the user explicitly asks for it.
- If TradingView sign-in is blocked by captcha or another interactive challenge
  the agent cannot solve, stop and message the user that there is a problem
  signing in to the TradingView account and ask the user to help solve the
  captcha in the visible browser window before continuing.
- After a successful TradingView sign-in, immediately save or refresh the
  browser's persistent session/auth state so future runs are less likely to
  require another captcha.

## Phase 4 Notes

- The public phase-4 entry point is `app/services/candidate_service.py`.
- Keep browser automation retry-safe:
  1. retry the page once
  2. retry with a clean browser context
  3. fall back to backup earnings sources if TradingView is still unusable
- Before falling back, if the blocker is an unsolved TradingView captcha, ask
  the user to complete it in the visible browser window and then resume with
  the same persistent profile/session.
- If TradingView fails and backup candidates are used, surface the PRD warning:
  `⚠️ TradingView did not load correctly, so I used backup earnings data for this scan.`
