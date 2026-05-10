# PLAN_News.md — News Pipeline Redesign

## 1. Problem Statement

The scanner produces consistent symbol/strike/premium across runs but the **confidence score varies between runs** for the same trade. Investigation traced this to non-determinism in the news pipeline:

- The LLM-generated `news_confidence` integer (0–100) produced by Gemini in [app/services/news/summarizer.py](../app/services/news/summarizer.py) is not bit-deterministic across API calls, even at `temperature=0`.
- `_recency_score()` in [app/services/news/service.py](../app/services/news/service.py) calls `datetime.now()` directly, causing day-boundary discontinuities that shift which articles survive into the top-N set fed to the LLM.
- Cache TTL boundaries (7200s) cause some scans to use cached briefs and others to refetch, producing different LLM outputs.
- Article counts vary between runs due to source flakiness, which changes the cap applied by `_apply_coverage_policy`.

A deeper architectural issue was identified during analysis: **Gemini (a small extraction model) was making bullish/bearish classification calls that fed directly into the deterministic scoring math**. This is the wrong model doing the wrong job — directional judgment is a high-stakes call that should belong to Opus (a much more capable model with the full picture: market data + news + technicals).

## 2. Decision Summary

Two integrated changes:

1. **Remove `news_confidence` from the scoring system entirely.** The field is consumed in three places: [app/scoring/confidence.py](../app/scoring/confidence.py), [app/scoring/direction.py](../app/scoring/direction.py), [app/scoring/penalties.py](../app/scoring/penalties.py). All three sites lose their news contribution. Other scoring criteria (price, IV, options chain, technicals) remain exactly as they are.

2. **Strip Gemini of bullish/bearish classification.** Gemini becomes a pure factual extractor. Opus reads the neutral factual brief alongside market data and produces the directional call.

The deterministic direction math in `direction.py` is preserved exactly — only its news inputs are removed. Direction continues to be computed from market data using the existing formula.

## 3. Target Architecture

### Gemini's role — pure factual extraction

Output: a structured `NewsBrief` containing:
- `summary` — paragraph-length neutral overview (no length cap; scales with substance)
- `key_facts` — unbounded list of preserved facts (numbers, dates, named events, with full context including source attribution)
- `quoted_statements` — verbatim quotes from executives and analysts with attribution
- `named_actions` — analyst upgrades/downgrades, M&A actions, regulatory events with full detail
- `key_uncertainty` — factual gaps in available information

**Removed from the contract**: `news_confidence`, `bullish_evidence`, `bearish_evidence`.

**Model selection**: use **Gemini Pro 3.1 Preview** for extraction (verify availability via OpenRouter before committing). Cost is not the optimization axis. The brief is the only path through which news reaches Opus, so quality is paramount. Preview-tier risk (model deprecation/replacement) is handled by the `PROMPT_VERSION` and `BRIEF_SCHEMA_VERSION` constants — when the model is swapped, bumping the version invalidates cached briefs cleanly.

**Prompt requirements**:
- Preserve every figure verbatim (guidance ranges, EPS estimates, percentage changes)
- Quote executives and analysts directly
- Name every analyst with their action
- Include all dates of upcoming events
- Capture regulatory and M&A specifics
- End with an explicit "completeness check" instruction telling the model to verify before returning that no quantitative figure, quoted statement, or named action was summarized away

### Deterministic scoring — preserved with surgical removal

- `confidence.py`: delete `_news_score()` and `_W_NEWS = 0.03`. Do not renormalize remaining weights. Maximum raw confidence becomes 97; this is acceptable.
- `direction.py`: delete the news block (the bullish/bearish multiplier and `news_confidence` weighting). Direction becomes a pure function of market data.
- `penalties.py`: delete the mixed-news penalty branch.
- `service.py`: delete `_apply_coverage_policy` (becomes dead code without `news_confidence`).

### Direction output — two tiers, two purposes

After scoring, two directional calls exist:

- **Structural direction tier** — derived by binning the deterministic direction score into `bullish / neutral / bearish`. Pure market data signal. Threshold suggestion: score < 40 = bearish, 40–60 = neutral, > 60 = bullish (tune after observation).
- **Opus direction tier** — Opus reads the structural tier, the factual brief, and all market data, then produces its own tier. Opus does not produce a 0–100 number; if it expresses strength, it uses a small enum (weak/moderate/strong).

The continuous structural direction score is preserved internally for any sizing or ranking logic that needs granularity.

### Opus's role — synthesis and final call

Opus's pipeline position is unchanged. Inputs change in shape only:
- Receives the structural tier and structural confidence
- Receives the rich factual brief (instead of pre-classified evidence)
- Receives all market data as before
- Produces the final recommendation including its directional tier and a one-line rationale

## 4. Part 4 Resolution — Selected: Solution (a)

When the structural direction tier and Opus's tier disagree:

- **Show Opus's tier to the user.** Opus has the full picture (math + news); the structural tier has math only.
- **Surface a one-line rationale** alongside Opus's call (e.g., "guidance cut announced pre-market, not yet reflected in price"). This is cheap, valuable, and debuggable.
- **Log every divergence** with full context (run ID, structural tier, Opus tier, key facts cited, rationale). These logs are the audit trail that makes solution (a) safe — if Opus ever overrides for bad reasons, the evidence exists to identify and fix it.

**Additional product surfaces** to add alongside (a):

- `news_coverage` enum on output — derived deterministically from article count and source diversity (`none / sparse / adequate / rich`). Replaces the *informational* role `news_confidence` was poorly serving without putting it back into scoring math.
- `stale_news` flag — if the most recent article in the bundle is older than a threshold (e.g., 14 days), surface this. Today nothing communicates news staleness to the user.

## 5. Critical Additions (Engineering Safeguards)

These ship alongside the core change. Without them, the architecture quietly regresses.

### 5.1 Freeze the reference timestamp at scan entry

Capture `reference_dt = datetime.now(UTC)` once at scan start. Thread it through every site that currently calls `datetime.now()` or `date.today()`:
- `_recency_score()` and `_article_sort_key()` in [service.py](../app/services/news/service.py)
- `FinnhubNewsSource.today_provider` in [sources.py](../app/services/news/sources.py)
- `SecEdgarNewsSource` year boundary in [sources.py](../app/services/news/sources.py)
- Any other `now()` / `today()` callers in the news path

Eliminates day-boundary discontinuities in article ranking. Without this, article ordering still drifts between scans even after fixing news_confidence.

### 5.2 Content-addressed news brief cache

Cache the brief by `sha256(sorted article URLs + published timestamps)`. Indefinite TTL. Invalidated only when:
- The article set changes
- The prompt version changes
- The schema version changes

Same articles in → same brief out, forever. Robust to cache TTL boundaries and to Gemini's residual extraction variance.

### 5.3 Prompt and schema versioning

Add `PROMPT_VERSION` and `BRIEF_SCHEMA_VERSION` constants. Both participate in the cache key. When either changes, old cached entries become unreachable rather than wrongly served. Required before evolving the prompt or schema.

### 5.4 Tier all LLM directional outputs

Opus's directional output is a tier (3 values). Strength, if expressed, is a small enum (weak/moderate/strong). Never request a 0–100 numeric score from any LLM in this pipeline — three buckets absorb LLM jitter cleanly.

### 5.5 Explicit Gemini-failure mode

Today, `news_confidence` has implicit defaults if the LLM call fails. After this change, the brief is the only news input Opus receives. Define explicitly what happens if Gemini errors:
- Pass an empty `NewsBrief` with `key_uncertainty = ["news service unavailable"]`, OR
- Skip the candidate, OR
- Fall back to most recent cached brief with a `stale_brief` flag

Pick one and code it deliberately. Do not let the failure mode default to whatever happens.

## 6. Operational Layer (Required, Not Optional)

This is what makes the system trustworthy in production.

### 6.1 Run-ID and snapshot logging

Every scan gets a UUID. Per-scan logs (jsonl files at minimum):
- Run ID
- Frozen reference timestamp
- Article-set hash
- Full Gemini brief verbatim
- Deterministic scores (confidence, structural direction)
- Structural direction tier
- Opus's full reasoning trace
- Opus's directional tier
- Final user-facing tier
- Divergence flag (true if structural tier ≠ Opus tier)
- Rationale field

Enables answering "why did the system recommend X for SYMBOL on DATE" weeks later.

### 6.2 Determinism test in CI

Integration test that runs the new pipeline twice with stubbed news and market data, asserts structural confidence and direction tier are bit-identical. Non-skippable. This is a regression test against the original bug — it locks in the determinism guarantee so it can never silently regress as the codebase evolves.

### 6.3 Gemini brief quality eval

Eval set of 10–20 historical news events with known material facts:
- Guidance cut
- Analyst downgrade
- M&A announcement
- Regulatory action
- Earnings beat/miss
- Quiet day (no material news)

For each, assert the new factual brief preserves the material fact verbatim or with no loss of precision. Run on every prompt change. Guards against the most dangerous failure mode — Gemini sanitizing away signal.

## 7. Implementation Order

Six steps. Each independently shippable and reversible. No big-bang release.

### Step 1 — Foundation (low risk, no user-visible change)
- Freeze reference timestamp at scan entry, thread through all `now()` / `today()` callers in the news path
- Add `PROMPT_VERSION` and `BRIEF_SCHEMA_VERSION` constants
- Set up run-ID generation and snapshot logging infrastructure
- Add the determinism test to CI (will fail until step 3, but lock in the contract)

### Step 2 — Gemini upgrade (additive)
- Update Gemini prompt: pure factual extraction, completeness check instruction
- Add new `NewsBrief` fields (`key_facts`, `quoted_statements`, `named_actions`) **alongside** existing fields
- Switch to Gemini Pro 3.1 Preview
- Build and run the brief quality eval suite
- Validate brief substance manually on real scans

### Step 3 — Scoring removal (mechanical)
- Delete `_news_score()` and `_W_NEWS` from `confidence.py`
- Delete news block from `direction.py`
- Delete mixed-news branch from `penalties.py`
- Delete `_apply_coverage_policy` from `service.py`
- Remove `news_confidence` from `NewsBrief` model
- Bump `BRIEF_SCHEMA_VERSION`
- Determinism test goes green here

### Step 4 — Gemini cleanup
- Remove `bullish_evidence` and `bearish_evidence` from Gemini's prompt and schema
- Bump `PROMPT_VERSION` and `BRIEF_SCHEMA_VERSION`
- Update all consumers (Telegram alerts, templates, dashboards) to read `key_facts` instead

### Step 5 — Tier output and divergence logging
- Add structural direction tier (bin the continuous score)
- Update Opus's output contract to produce a directional tier and one-line rationale (no 0–100)
- Implement Solution (a): show Opus's tier to user, log divergence
- Add `news_coverage` enum and `stale_news` flag to output

### Step 6 — Content-addressed brief cache
- Implement article-set hashing
- Switch cache key to use the hash
- Set TTL to indefinite (with prompt/schema version invalidation)

## 8. Honest Tradeoffs Accepted

1. **News no longer moves the deterministic direction or confidence scores.** Direction is purely market-derived; confidence omits the 3-point news weight. News influences only Opus's synthesis. Major news events won't shift the structural numbers; they'll shift Opus's interpretation. The structural tier will lag fast-moving news; Opus is responsible for catching up. This is deliberate.

2. **Maximum raw confidence becomes 97 (was 100).** Cosmetic only. Relative ordering is unaffected. Other scoring weights are not renormalized per the constraint to leave existing scoring criteria untouched.

3. **More analytical risk consolidates in Opus.** With Gemini stripped of judgment, Opus is the only place news interpretation happens. Mitigated by: structural tier as a parallel sanity check, divergence logging, Opus rationale field, brief quality eval.

4. **Gemini's brief becomes mission-critical.** If Gemini drops a material fact, Opus has no other path to learn about it. Mitigated by: more capable Gemini variant, longer/precise prompt, completeness check, eval suite, explicit failure mode.

5. **Tier output reduces granularity in the user-visible result.** Mitigated by keeping the continuous structural direction score available internally for any sizing/ranking logic that needs it.

6. **Existing cached `NewsBundle` entries become stale.** Mitigated by cache version bump in Step 3 — old entries become unreachable rather than wrongly served.

## 9. Success Criteria

- Two consecutive scans of the same symbol with the same article set produce **identical** structural confidence and structural direction tier
- Gemini brief preserves 100% of material facts in the eval suite (verified per prompt change)
- Every divergence between structural tier and Opus tier is logged with full context
- Determinism test in CI is green and stays green
