---
name: tradingview-phase4
description: Detailed TradingView phase-4 Playwright workflow for Earning-Edge. Use whenever the task involves the TradingView screener, phase 4 candidate extraction, Playwright CLI browser automation, TradingView sign-in, captcha handoff, applying `Upcoming earnings date = Next week`, adding the `Upcoming earnings date` column, extracting the top five visible rows, or resuming an existing TradingView browser session. Use this skill even if the user only says "run phase 4", "open TradingView", "continue the screener", "get the top five", or "help with the TradingView session".
hidden: true
---

# TradingView Phase 4

Repo-specific workflow for the browser portion of phase 4 in `Earning-Edge`.

## Goal

Use Playwright CLI to:

1. open or resume the TradingView screener
2. sign in with the repo TradingView account if needed
3. apply `Upcoming earnings date = Next week`
4. avoid any other filter or sorting changes unless the user explicitly asks
5. add the `Upcoming earnings date` column if it is missing
6. extract the top five visible rows exactly as TradingView presents them

Stop after browser extraction. Do not continue into market-data, scoring, or
recommendation work from this skill alone.

## Read First

- Read `AGENTS.md` before starting. It contains the TradingView account,
  persistence rules, captcha escalation rule, and fallback warning text.
- Use only the visible TradingView browser session. Never use hidden or
  private TradingView APIs.
- Do not sign out of TradingView unless the user explicitly asks for it.
- Prefer a headed Chrome session with a persistent profile and saved auth
  state.
- If the user asks for a step-by-step demo, do one concrete browser action at a
  time, report the result, and wait for user input before continuing.

## Tooling

Use the Playwright CLI wrapper:

```bash
export CODEX_HOME="${CODEX_HOME:-$HOME/.codex}"
export PWCLI="$CODEX_HOME/skills/playwright/scripts/playwright_cli.sh"
mkdir -p output/playwright/phase4-demo
```

Use these repo-local paths:

- persistent Chrome profile:
  `output/playwright/phase4-demo/chrome-profile`
- saved auth state:
  `output/playwright/phase4-demo/tradingview-auth-state.json`

Use short Playwright session names such as `p4` or `tv`.

Why: long session names can break on macOS because Playwright CLI uses Unix
socket paths under a temp directory, and long names can exceed the OS path
limit.

## Session Bootstrap

### 1. Verify prerequisites

- Confirm `npx` exists before using the wrapper.
- If `npx` is missing, stop and ask the user to install Node/npm.

### 2. Prefer session reuse over fresh login

First, check whether a suitable browser server is already running:

```bash
"$PWCLI" list
```

If there is an existing TradingView browser server or a browser already using
the persistent profile, attach to it instead of opening a second browser:

```bash
"$PWCLI" --session p4 attach "<browser-name-from-list>"
```

If no suitable server exists, open Chrome in headed persistent mode:

```bash
"$PWCLI" --session p4 open https://www.tradingview.com/screener/ \
  --browser chrome \
  --headed \
  --persistent \
  --profile "$PWD/output/playwright/phase4-demo/chrome-profile"
```

If `open` fails but leaves a browser server running, use `list` and `attach`
instead of retrying blindly.

If the attached page is `about:blank`, navigate explicitly:

```bash
"$PWCLI" --session p4 goto https://www.tradingview.com/screener/
```

If a saved auth state exists and the session is not already signed in, load it
after the browser is open:

```bash
"$PWCLI" --session p4 state-load output/playwright/phase4-demo/tradingview-auth-state.json
"$PWCLI" --session p4 reload
```

Prefer the persistent profile first. Use `state-load` as a backup, not a
replacement for the persistent profile.

## Snapshot Discipline

Always snapshot before using element refs.

Snapshot again after:

- navigation
- attach-to-running-browser
- opening or closing a dialog
- sign-in state changes
- filter application
- reload
- any failed `ref not found` action
- any major table refresh

When a ref fails, do not guess. Snapshot again and use the new ref.

## Browser Workflow

### 1. Confirm the screener is ready

- Open or attach to the screener.
- Snapshot and verify the page title is the TradingView stock screener.
- Confirm the screener controls and table are visible before touching filters.

### 2. Trigger TradingView's visible auth gate only through the UI

Open the `Upcoming earnings date` filter first. TradingView may:

- open the filter menu directly, or
- interrupt with a sign-in modal

Do not try to pre-login through hidden endpoints or alternative pages.

### 3. Sign in when TradingView requires auth

If a sign-in modal appears:

1. click `Email`
2. fill the TradingView credentials from `AGENTS.md`
3. click `Sign in`

If TradingView presents captcha or another human challenge:

- stop immediately
- tell the user there is a problem signing in to the TradingView account
- ask the user to solve the captcha in the visible browser window
- after the user confirms, resume the same browser session and click `Sign in`
  again if needed

Do not close the browser or switch profiles during this handoff.

Confirm successful sign-in by checking that:

- the sign-in modal is gone
- signed-in TradingView UI is visible
- the screener remains accessible

Immediately save auth state after successful sign-in:

```bash
"$PWCLI" --session p4 state-save output/playwright/phase4-demo/tradingview-auth-state.json
```

### 4. Verify persistence once after login

After sign-in, it is reasonable to reload once to confirm the session survives
refresh.

If reload or snapshot reports a modal state such as a `beforeunload` dialog:

- handle it with `dialog-accept` or `dialog-dismiss` if it is still present
- then retry snapshot or reload

If the dialog disappears before the handler runs, simply snapshot again and
continue.

Do not sign out as part of persistence verification.

### 5. Apply the required TradingView filter

Open `Upcoming earnings date`, then select `Next week`.

After that filter is applied:

- do not change any other TradingView filters
- do not change sorting
- do not click `Change sort`
- do not try to improve or normalize the visible ranking

The selection set is the first five visible rows exactly as TradingView shows
them after `Next week` is applied.

### 6. Add the `Upcoming earnings date` column only if needed

Inspect the visible column headers first.

If `Upcoming earnings date` is already visible, leave the table alone.

If the column is missing:

1. open `Column setup`
2. search for `Upcoming earnings date`
3. select that column
4. snapshot again and confirm the header is visible

Observed TradingView quirk:

- direct clicking on `Column setup` can be blocked by a right-side panel or a
  live table cell intercepting pointer events

Preferred workaround:

```bash
"$PWCLI" --session p4 keydown Shift
"$PWCLI" --session p4 press c
"$PWCLI" --session p4 keyup Shift
```

Then use the dialog search field to find `Upcoming earnings date` and select
it.

This is better than forcing clicks through overlays or changing unrelated UI.

### 7. Extract the top five visible rows

Once the `Next week` filter is applied and the earnings-date column is visible,
extract the first five visible rows exactly as shown.

Required fields:

- ticker
- company name
- market cap
- upcoming earnings date

Preferred fields when visible:

- current price
- daily change %
- volume
- sector
- analyst rating

Do not scroll or sort to build a different top five. Use the first five visible
rows only.

Recommended output format:

```text
- AMD — Advanced Micro Devices, Inc. — 587.13 B USD — earnings 2026-05-05
- PLTR — Palantir Technologies Inc. — 345.6 B USD — earnings 2026-05-04
- ARM — Arm Holdings plc DR — 223.36 B USD — earnings 2026-05-06
- ANET — Arista Networks, Inc. — 221.22 B USD — earnings 2026-05-05
- MCD — McDonald's Corporation — 203.91 B USD — earnings 2026-05-07
```

Capture a screenshot if it helps preserve evidence of the exact visible rows.

### 8. Stop condition

The TradingView/browser portion ends after extraction.

Do not continue browser work unless the user asks for more.

Non-browser candidate validation belongs to the phase-4 service layer in:

- `app/services/candidate_service.py`
- `app/services/earnings_calendar/*`

Phase 5 market-data work is separate and not part of this browser skill.

## Troubleshooting

### Long Playwright session names fail on macOS

Symptom:

- Playwright CLI fails while creating a Unix socket path

Action:

- use a short session id such as `p4`
- if the browser daemon was already launched, use `list` and `attach`

### Persistent profile is "already in use"

Symptom:

- `open --persistent --profile ...` fails because the profile is locked

Action:

- do not delete the profile
- inspect `"$PWCLI" list`
- attach to the existing browser server that is already using the profile

### Attached browser shows `about:blank`

Action:

- run `goto https://www.tradingview.com/screener/`
- snapshot again

### Ref is stale or missing

Symptom:

- `Ref eNNNN not found`

Action:

- snapshot again
- use the fresh ref

### Snapshot says modal state blocks the tool

Symptom:

- snapshot reports a dialog such as `beforeunload`

Action:

- accept or dismiss the dialog if it is still present
- retry snapshot
- if the dialog has already disappeared, just snapshot again

### Click is intercepted by another element

Symptom:

- Playwright says another subtree intercepts pointer events

Action:

- do not brute-force random clicks
- re-snapshot
- prefer a keyboard shortcut if TradingView provides one
- for `Column setup`, use `Shift+C`

### Captcha appears during sign-in

Action:

- stop and ask the user for help
- keep the current browser session and persistent profile alive
- after the user solves it, resume and complete sign-in

### TradingView remains unusable

If the page still fails after:

1. retrying the page once
2. retrying with a clean browser context

then follow the repo fallback rule outside this skill and surface the warning:

```text
⚠️ TradingView did not load correctly, so I used backup earnings data for this scan.
```

## Demo Mode

If the user wants to watch the workflow step by step:

- open or attach to the browser
- do one concrete action
- summarize the result
- stop and wait for the user's next instruction

This mode is for guided debugging. The normal mode can complete the whole
browser flow end to end.
