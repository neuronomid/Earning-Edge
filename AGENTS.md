# AGENTS.md

## Purpose

This file stores repo-specific operating instructions for Codex agents working in
`Earning-Edge`.

## Primary Screener

## Required Behaviour

- Do not use the retired phase-4 screener provider. The phase-4 screener has
  been replaced.
- Use Finviz as the primary visible screener when a live browser check is
  needed.
- Use the Finviz screener URL
  `https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap`
  and work from the top five visible rows.
- Keep browser automation retry-safe and stateless. Do not add login-only or
  persistent-auth assumptions to the Finviz flow.

## Phase 4 Notes

- The public phase-4 entry point is `app/services/candidate_service.py`.
- Keep browser automation retry-safe:
  1. retry the page once
  2. retry with a clean browser context
  3. fall back to backup earnings sources if Finviz is still unusable
- If Finviz fails and backup candidates are used, surface the warning:
  `⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.`
