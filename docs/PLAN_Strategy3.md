# PLAN — Strategy 3: Add Three New Strategies (5-Strategy Pipeline)

**Status:** Implementation plan. No code changes yet.
**Pairs with:** [docs/strategy3_combined.md](strategy3_combined.md), [docs/strategy3_Claude.md](strategy3_Claude.md), [docs/strategy3_Codex.md](strategy3_Codex.md).
**Author:** Plan synthesised from the three source documents and grounded in the current codebase ([CLAUDE.md](../CLAUDE.md)).

---

## 1. Goal

Extend the weekly options pipeline from **2 screens → 5 screens**. Each screen contributes its top 5 candidates → merged pool of up to **25 deduplicated tickers**. The pool then runs through a **rebalanced (strategy-neutral) scoring system** that gives all 5 strategies equal a-priori opportunity. The top **4 finalists** by `final_score` are passed to the heavy LLM, which picks **one** contract (or no-trade).

The flow must work end-to-end when the user presses **"Run scan now"** in Telegram or, when wired, the dashboard — both paths route through `WorkflowRunner.run_workflow()` ([app/scheduler/jobs.py](../app/scheduler/jobs.py), [app/telegram/handlers/menu.py:51](../app/telegram/handlers/menu.py#L51)).

```
A (5)  ─┐
B (5)  ─┤
C (5)  ─┼──► dedupe ► up to 25 candidates ► strategy-neutral scoring ► top 4 ► LLM ► 1 contract or no-trade
D (5)  ─┤
E (5)  ─┘
```

The three new strategies, taken from the consensus winners in [strategy3_combined.md §Winners](strategy3_combined.md):

| # | Slug | Source spec | Score |
|---|------|-------------|------:|
| C | `pead_continuation` | [strategy3_Claude.md §2](strategy3_Claude.md) | 26.7 |
| D | `sector_relative_strength` | [strategy3_Claude.md §3](strategy3_Claude.md) | 24.1 |
| E | `activist_13d_followthrough` | [strategy3_Codex.md §6](strategy3_Codex.md) | 23.8 |

Existing strategies are unchanged: A = `catalyst_confluence` (pre-earnings), B = `coiled_setup` (52-week-high structure).

## 2. Non-goals (v1)

- No multi-leg contracts (debit spreads, calendars, condors). All new strategies ship single-leg long calls (or long puts for PEAD bearish in v2).
- No bearish PEAD variant — v1 ships positive-surprise long calls only ([strategy3_Claude.md §2.3](strategy3_Claude.md)).
- No Form 4 insider cluster strategy — Claude's panel deferred it to Appendix A; Codex's variant lost the consensus vote. Captured as future work.
- No changes to the **outer** `direction_score × 0.45 + contract_score × 0.55` blend in [app/scoring/final.py](../app/scoring/final.py). The fairness work in §6 is **inside** `direction_score` and `compute_data_confidence` — the outer blend is unchanged.
- No changes to `DECISION_FINALIST_LIMIT = 4` in [app/pipeline/orchestrator.py:67](../app/pipeline/orchestrator.py#L67).
- No new external paid sources, no logged-in scrapers, no SEC user-agent gymnastics beyond the existing EDGAR pattern in [app/services/news/sources.py](../app/services/news/sources.py).

## 3. Architecture impact at a glance

| Layer | Change |
|---|---|
| Schema | Widen `strategy_source` accepted values + add new `screener_status="empty"` |
| Models | Widen `StrategySource` `Literal`, refactor missing-earnings exemption to a set, add `event_score` field to `CandidateContext` |
| Services | 3 new candidate services (`pead_service.py`, `sector_relative_strength_service.py`, `activist_13d_service.py`) + thin SEC filings client |
| Multi-strategy | `MultiStrategyCandidateService` becomes a strategy-runner list, not a hard-coded 2-arm gather |
| Catalog | Add 3 `StrategyDefinition` entries to `strategy_catalog.py` |
| **Scoring (rebalanced for fairness)** | **Strategy-aware direction weights, strategy-aware confidence weights, strategy-aware vetoes/penalties, new `event_signal` factor that lets C/D/E surface their edge into `direction_score`** — see §6 |
| Pipeline | No structural change; orchestrator gathers 5 batches concurrently and trims pool to top 25 deduped before per-candidate fan-out |
| Telegram | Per-strategy status table (5 rows instead of 2) on the run-summary card |
| Dashboard | No new endpoint required for v1 trigger (still routes through `WorkflowRunner`) |

## 4. Strategy specs (condensed)

Full reasoning, citations, and failure modes live in the source documents. The spec below is the **implementation contract** — anything not stated here defers to the source doc.

### 4.1 Strategy C — Post-Earnings Drift Continuation (`pead_continuation`)

**Source:** [strategy3_Claude.md §2](strategy3_Claude.md).

- **Trigger:** Recently reported earnings, positive surprise, day-1 reaction confirmed.
- **Finviz URL:** `https://finviz.com/screener?v=111&f=earningsdate_prevweek,geo_usa,sh_opt_option,sh_price_o10,sh_avgvol_o500,ta_change_u&o=-change` — pull top 20 rows.
- **Post-filters (Decimal-typed):**
  - `eps_surprise_pct ≥ 0.05` (yfinance primary, Finnhub fallback, Alpha Vantage tertiary).
  - `day1_change_pct ≥ 0.03`.
  - Sector ∉ {`Technology`, `Communication Services`}.
  - Market cap in `[300M, 10B]`.
  - Announcement date is **not** the same trading day (T+1 minimum).
- **Composite ranking:**
  ```
  score_C = (eps_surprise_pct / 0.05) * 0.50
          + (day1_change_pct  / 0.03) * 0.30
          + non_tech_bonus            * 0.20
  ```
- **Output:** Top 5 by `score_C`. If fewer than 5 pass, ship fewer (no padding).
- **Direction / contract:** long call, delta 0.40–0.55, 21–28 DTE, OI > 200, bid/ask ≤ 15% of mid.
- **Cross-arm rule:** must not reopen on a ticker Strategy A already pre-opened — checked against `open_positions` before persisting (consistent with existing position-monitor de-dupe).

### 4.2 Strategy D — Non-Tech Sector Relative Strength (`sector_relative_strength`)

**Source:** [strategy3_Claude.md §3](strategy3_Claude.md).

- **Trigger:** Two-step screen.
- **Step 1 — sector ETF ranking** via yfinance batch download (`period='2mo', interval='1d'`):

  | ETF | Sector | Finviz `sec_` |
  |---|---|---|
  | XLE | Energy | `sec_energy` |
  | XLF | Financials | `sec_financial` |
  | XLI | Industrials | `sec_industrials` |
  | XLV | Health Care | `sec_healthcare` |
  | XLU | Utilities | `sec_utilities` |
  | XLP | Consumer Staples | `sec_consumerdefensive` |
  | XLY | Consumer Discretionary | `sec_consumercyclical` |
  | XLB | Materials | `sec_basicmaterials` |
  | XLRE | Real Estate | `sec_realestate` |

  Hard-excluded: `XLK`, `XLC`.
- **Regime gate (must both pass):**
  - Top sector ETF closing price ≥ its 50-day SMA.
  - Top sector 4-week return ≥ `+0.02` (Decimal).
  - On failure, return `CandidateBatch(candidates=(), screener_status="empty")` — pipeline runs as 4-strategy that week.
- **Step 2 — stock screen inside the leading sector:**
  Dynamic Finviz URL: `https://finviz.com/screener?v=111&f={leading_sector_filter},geo_usa,sh_opt_option,sh_price_o10,sh_avgvol_o500,ta_sma50_pa&o=-perf4w` — top 5 rows.
  If top sector returns < 5 names, drop to the second-ranked non-tech sector that **also passes the regime gate** and fill from there.
- **Composite ranking:**
  ```
  score_D = stock_perf_4w_rank      * 0.60
          + sector_alignment_score  * 0.40
  # sector_alignment_score = 1.0 if sector_perf_4w > 5%, 0.5 if 2–5%
  ```
- **Direction / contract:** long call only, delta 0.45–0.55, 21–28 DTE.
- **Position-monitor extension:** if leading-sector ETF closes below entry-day price while a `sector_relative_strength` position is open, set a `regime_warning` flag on the position; surface on the next scheduled alert (no auto-exit). v1 may stub this as a TODO note in the position record's existing `validation_notes`-like field — no new schema column.

### 4.3 Strategy E — Activist 13D Follow-Through (`activist_13d_followthrough`)

**Source:** [strategy3_Codex.md §6](strategy3_Codex.md).

- **Trigger:** Fresh activist Schedule 13D filings on EDGAR.
- **Universe filters (v1):** US-listed, optionable, price ≥ $15, ADV ≥ 750k, market cap ≥ $500M, sector ≠ tech (not banned but tech-penalised).
- **Selection tiers (in order until ≥ 5 candidates):**
  1. Initial SC 13D filings, last 5 trading days.
  2. Substantive SC 13D/A amendments, last 10 trading days (stake ↑, Item 4 changed).
  3. Still-active 13D events from last 20 trading days where price has not exhausted move and option liquidity holds.
- **Hard exclusions:** SC 13G (passive), filings with no active Item 4 language, illiquid options, bid/ask > tolerance.
- **Composite event score:**
  ```
  event_score =
        stake_size_score
      + active_intent_score
      + filer_quality_score
      + recency_score
      + relative_volume_score
      + price_confirmation_score
      + option_liquidity_score
      − gap_exhaustion_penalty
      − earnings_collision_penalty
      − tech_concentration_penalty
  ```
  Sub-score formulas live in `app/services/sec/scoring.py` — keep them simple (linear, capped, Decimal-typed). Do **not** tune to a small fixture sample.
- **Direction / contract:** long call, delta 0.35–0.55, 14–28 DTE.
- **Persistence:** store SEC accession number + filing URL in candidate `validation_notes` (no schema change in v1; structured metadata column deferred per [§6 unresolved decisions](strategy3_Codex.md)).

## 5. Schema and model changes

### 5.1 Migration `0013_strategy_source_widen.py`

Latest revision is `0012_position_validation`. The fork at `0004_*` is preserved.

`strategy_source` is stored as `String(32)` on `candidates`, `recommendations`, and `position_thesis` (verified via `grep` — no Postgres `ENUM` type involved). All three new slugs fit:

- `pead_continuation` (16)
- `sector_relative_strength` (24)
- `activist_13d_followthrough` (26)

Therefore the migration is **data-only / no-op DDL** — it simply documents the widening for future readers and is reversible:

```python
"""strategy_source widen for pead, sector_rs, activist_13d"""
revision = "0013_strategy_source_widen"
down_revision = "0012_position_validation"

def upgrade() -> None:
    # No DDL: strategy_source is String(32); slugs fit. Migration documents the
    # widening so the SQLAlchemy `Literal` and the runtime values stay in sync.
    pass

def downgrade() -> None:
    pass
```

If a follow-up audit finds a Postgres ENUM in any environment, the migration becomes:

```python
op.execute(
    "ALTER TYPE strategy_source ADD VALUE IF NOT EXISTS 'pead_continuation';"
    "ALTER TYPE strategy_source ADD VALUE IF NOT EXISTS 'sector_relative_strength';"
    "ALTER TYPE strategy_source ADD VALUE IF NOT EXISTS 'activist_13d_followthrough';"
)
```

### 5.2 `app/services/candidate_models.py`

```python
ScreenerStatus = Literal["success", "partial", "failed", "empty"]
StrategySource = Literal[
    "catalyst_confluence",
    "coiled_setup",
    "pead_continuation",
    "sector_relative_strength",
    "activist_13d_followthrough",
]
```

`"empty"` is new — Strategy D's regime gate explicitly returns it. Update [app/services/multi_strategy_service.py](../app/services/multi_strategy_service.py) and any consumers of the enum (the warning-text resolver, Telegram renderer).

### 5.3 `app/scoring/types.py`

Mirror the `StrategySource` widening (currently a separate `Literal` at [app/scoring/types.py:21](../app/scoring/types.py#L21)). Default stays `"catalyst_confluence"` for backwards compatibility.

### 5.4 Missing-earnings exemption set

Replace the hard-coded check `candidate.strategy_source == "coiled_setup"` in [app/scoring/vetoes.py:24](../app/scoring/vetoes.py#L24) and [app/scoring/confidence.py:100](../app/scoring/confidence.py#L100) with:

```python
NO_EARNINGS_REQUIRED_STRATEGIES: frozenset[StrategySource] = frozenset({
    "coiled_setup",
    "sector_relative_strength",
    "activist_13d_followthrough",
})
```

`pead_continuation` keeps the earnings-required behaviour because the post-filter already verifies a recent earnings event exists.

Also update [app/services/alternative_recommendation_service.py:402](../app/services/alternative_recommendation_service.py#L402) which uses the same hard-coded check.

## 6. Scoring fairness — make all 5 strategies competitive

**Why this is required.** The scoring engine that ships today was designed when only A and B existed. A is an earnings-event screen; B is exempted from earnings via a `coiled_setup`-only special case. As a result, the engine has at least **five structural biases that would systematically push C, D, and E to the bottom of the 25-candidate pool unless we rebalance.**

### 6.0 Codebase audit — what production actually does today

Before designing the fix, the agents implementing this plan must understand four non-obvious facts uncovered by reading the code:

1. **`previous_earnings_move_percent` is never populated by the production pipeline.** [orchestrator.py:313-330](../app/pipeline/orchestrator.py#L313) constructs `CandidateContext` and never passes that field — it stays at its `None` default. Tests populate it; production doesn't. So `_earnings_signal()` already returns `ZERO` for every A candidate today, and the `inconsistent_history` soft penalty never fires in production. **Implication:** the legacy A/B regression bound (Phase 1.5) is easy to satisfy because A's earnings-signal contribution is already zero — the rebalance does not destabilise A's actual scores in production. The engine's 15-point earnings weight is currently dead weight, not an active bias.
2. **The active bias in production today is on the confidence side.** `_W_EARNINGS = 0.25` ([confidence.py:23](../app/scoring/confidence.py#L23)) and the `coiled_setup`-only exemption ([confidence.py:100](../app/scoring/confidence.py#L100)) drop ~25 confidence points off any non-A / non-B candidate. **This is the bias the rebalance has to fix first.**
3. **`StrategySource` is duplicated** in [candidate_models.py:9](../app/services/candidate_models.py#L9) and [scoring/types.py:21](../app/scoring/types.py#L21). Both must be widened in lock-step.
4. **The arm interface is asymmetric.** `CandidateService.get_top_five()` returns `CandidateBatch`; `CoiledSetupCandidateService.get_top_five()` returns `tuple[CandidateRecord, ...]` ([coiled_setup_service.py:25](../app/services/coiled_setup_service.py#L25)). Phase 1's "ArmRunner" abstraction must accept both shapes (or normalise B to also return `CandidateBatch`). The plan picks **normalise to `CandidateBatch`** — see Phase 1.

### 6.1 Inventory of current biases

The following are concrete code sites — each one is a place where a non-A / non-B candidate is mathematically punished today.

| # | Site | Bias | Effect on C / D / E |
|---|---|---|---|
| 1 | [app/scoring/direction.py:35-43](../app/scoring/direction.py#L35) — `_DIRECTION_WEIGHTS["earnings expectation context"] = 15` (out of 85 total) | Earnings signal is ~18% of direction score | D (no earnings) and E (no earnings) lose 15 points; C gets 0–full depending on whether `previous_earnings_move_percent` is populated post-event |
| 2 | [app/scoring/direction.py:190-202](../app/scoring/direction.py#L190) — `_earnings_signal()` returns `ZERO` if `previous_earnings_move_percent is None` | Default-zero is a bias, not a neutral | A wins by default; C/D/E sit at zero on this 15-point factor |
| 3 | [app/scoring/confidence.py:23](../app/scoring/confidence.py#L23) — `_W_EARNINGS = 0.25` (the single largest weight) and [confidence.py:98-107](../app/scoring/confidence.py#L98) — missing earnings → 0 unless `strategy_source == "coiled_setup"` | A non-earnings strategy without the exemption set drops 25% of confidence to 0 | D and E confidence ≈ −25 points unless exempted |
| 4 | [app/scoring/vetoes.py:24](../app/scoring/vetoes.py#L24) — `earnings_missing` veto exempts only `coiled_setup` | Hard veto, not a soft penalty | D and E never reach the contract scorer at all |
| 5 | [app/scoring/penalties.py:133-145](../app/scoring/penalties.py#L133) — `inconsistent_history` penalty compares `previous_earnings_move_percent` to `expected_move_percent` | Never fires for A (always has data) and never fires for D/E (always lacks data) — but C is asymmetrically exposed | Asymmetric: penalises C for having "weak" earnings history that A and B never test |

The cumulative effect is that an average D candidate with strong sector momentum still loses ~18 direction points + ~25 confidence points to an average A candidate with average earnings history. That is not a fair pool.

### 6.2 Design principle

Each strategy should be **scored against the criteria that justify its own thesis**, then candidates from all 5 strategies are compared on a **single normalised 0–100 scale**. The outer `0.45 × direction + 0.55 × contract` blend is unchanged. The fix is **inside** `direction_score` and `compute_data_confidence`:

- Replace **fixed** direction weights with a **strategy-aware** weight map that always sums to the same total (so a perfect candidate from any strategy can score the same theoretical maximum).
- Replace the single `coiled_setup`-only confidence/veto exemption with a **set** that covers all non-earnings strategies (already in §5.4 — repeated here for completeness).
- Add a new **`event_signal`** factor inside `score_direction` that is populated from the strategy's own ranking (PEAD's surprise/day-1, Sector RS's dispersion, 13D's `event_score`). The factor takes the place of the earnings factor for non-earnings strategies, so **the total weight available is identical**.
- Make the strategy-conditional pieces of `confidence.py`, `vetoes.py`, and `penalties.py` consult the same exemption set, not a hard-coded slug.

This is **not** a redesign of the scoring engine. The blend, the components, the normalisation, and the veto framework all stay. The only change is that the **earnings-shaped slots** become **event-shaped slots** that any strategy can populate with its own evidence.

### 6.3 Concrete changes

#### 6.3.1 New `event_signal` factor in `score_direction`

Add a new optional field to **both** `CandidateRecord` (so per-strategy services can attach it at scan time) **and** `CandidateContext` (so the scoring engine can read it):

```python
# in app/services/candidate_models.py (lives next to CandidateRecord)
@dataclass(slots=True, frozen=True)
class StrategyEventSignal:
    score: int            # 0..100  (strategy-internal score, already normalised by the service)
    is_supportive: bool   # True if signal supports the trade direction
    detail: str           # one-line human-readable reason

# CandidateRecord gains:
event_signal: StrategyEventSignal | None = None

# CandidateContext gains:
event_signal: StrategyEventSignal | None = None
```

`StrategyEventSignal` lives in `app/services/candidate_models.py` and is **re-exported** from `app/scoring/types.py` so neither layer imports across boundaries (matches existing pattern where `MarketSnapshot` lives in `services/` and is imported by `scoring/`).

The plumbing in [orchestrator.py:313](../app/pipeline/orchestrator.py#L313) gains one extra line:

```python
context = CandidateContext(
    ...,
    event_signal=record.event_signal,  # NEW — pass through from the per-strategy service
    ...,
)
```

Each new candidate service (PEAD, Sector RS, 13D) computes this and attaches it on the `CandidateRecord` before returning. A and B continue to pass `None` until B's backfill in Phase 1.5 (see §6.3.4).

In [app/scoring/direction.py](../app/scoring/direction.py), make `_DIRECTION_WEIGHTS` a function that returns a strategy-aware mapping with **constant total weight** (85, matching today):

| Factor | A `catalyst_confluence` | B `coiled_setup` | C `pead_continuation` | D `sector_relative_strength` | E `activist_13d_followthrough` |
|---|---:|---:|---:|---:|---:|
| trend alignment | 20 | 20 | 18 | 15 | 15 |
| relative strength | 15 | 18 | 15 | 18 | 15 |
| volume confirmation | 10 | 10 | 12 | 10 | 12 |
| **earnings expectation context** | **15** | **0** | **8** | **0** | **0** |
| **event signal (new)** | **0** | **7** | **7** | **15** | **15** |
| market/sector environment | 10 | 10 | 10 | 12 | 10 |
| price structure | 10 | 15 | 10 | 10 | 13 |
| data confidence | 5 | 5 | 5 | 5 | 5 |
| **Total** | **85** | **85** | **85** | **85** | **85** |

Numbers above are starting values, **calibrated against the regression suite in §6.4** (golden-fixture tests that check no strategy dominates by more than 5 points on a balanced day). Tunable via constants in [app/core/config.py](../app/core/config.py); committed values must show their derivation in the test fixtures, not be hand-tuned to a small sample.

The `_earnings_signal()` and (new) `_event_signal()` helpers each return a `Decimal` in `[-1, +1]`. When a strategy's weight for one of them is 0, the helper isn't called (or its return is multiplied by 0) — so a non-earnings strategy is no longer penalised for "missing earnings".

#### 6.3.2 Strategy-aware confidence weights

Convert the module-level constants in [app/scoring/confidence.py:23-28](../app/scoring/confidence.py#L23) into a strategy-aware lookup with the **same total weight (0.97)**:

| Component | A | B | C | D | E |
|---|---:|---:|---:|---:|---:|
| `W_IDENTITY` | 0.13 | 0.13 | 0.13 | 0.13 | 0.13 |
| `W_EARNINGS` | 0.25 | 0.00 | 0.20 | 0.00 | 0.00 |
| `W_EVENT` (new) | 0.00 | 0.20 | 0.05 | 0.20 | 0.20 |
| `W_MARKET` | 0.20 | 0.25 | 0.22 | 0.25 | 0.22 |
| `W_OPTIONS` | 0.22 | 0.22 | 0.22 | 0.22 | 0.22 |
| `W_CROSS_SOURCE` | 0.10 | 0.10 | 0.10 | 0.10 | 0.10 |
| `W_CALCULATION` | 0.07 | 0.07 | 0.05 | 0.07 | 0.10 |
| **Total** | **0.97** | **0.97** | **0.97** | **0.97** | **0.97** |

`W_EVENT` is sourced from the same `event_signal.score` field. For B (coiled_setup), `event_signal` is "structural setup quality" (e.g. distance from 52-week high × RS percentile) — provided by `CoiledSetupCandidateService`. This collapses the existing `coiled_setup`-only special case into the same generic plumbing.

#### 6.3.3 Vetoes and penalties become strategy-aware

- [app/scoring/vetoes.py:24](../app/scoring/vetoes.py#L24): replace `strategy_source != "coiled_setup"` with `strategy_source not in NO_EARNINGS_REQUIRED_STRATEGIES`.
- [app/scoring/confidence.py:100](../app/scoring/confidence.py#L100): same replacement.
- [app/scoring/penalties.py:133-145](../app/scoring/penalties.py#L133): the `inconsistent_history` penalty must be skipped for any strategy in `NO_EARNINGS_REQUIRED_STRATEGIES` **and** for `pead_continuation` (PEAD's premise is that the surprise is the new information; old expected_move comparisons are noise). Net: the penalty only fires for A.
- [app/services/alternative_recommendation_service.py:402](../app/services/alternative_recommendation_service.py#L402): same replacement.

```python
NO_EARNINGS_REQUIRED_STRATEGIES: frozenset[StrategySource] = frozenset({
    "coiled_setup",
    "sector_relative_strength",
    "activist_13d_followthrough",
})
```

#### 6.3.4 Where each strategy populates `event_signal`

| Strategy | `event_signal.score` formula | `is_supportive` |
|---|---|---|
| A | `None` (uses earnings factor instead) | n/a |
| B | `min(100, distance_from_52w_high_percentile * 50 + relative_volume_percentile * 50)` | always `True` (B is bullish-only) |
| C | `min(100, (eps_surprise_pct / 0.05) * 50 + (day1_change_pct / 0.03) * 50)` | `True` (positive surprise → bullish; bearish branch deferred to v2) |
| D | `min(100, sector_perf_4w_percentile * 60 + stock_perf_4w_percentile * 40)` | `True` (always bullish in v1) |
| E | `min(100, event_score_normalised)` (event_score from §4.3 normalised to 0–100) | `True` (long-only v1) |

Each per-strategy service is responsible for computing this **before** returning its `CandidateRecord`. The scoring engine treats it as opaque input.

### 6.4 Calibration and regression tests for fairness

Mathematical equality (every strategy can theoretically reach 85) is necessary but not sufficient. Empirical balance must be tested against golden fixtures.

| Test | What it proves |
|---|---|
| `tests/test_scoring_fairness.py::test_max_direction_score_equal_across_strategies` | A perfect-data candidate from each of A/B/C/D/E reaches the same direction-score ceiling (within ±2 points of rounding) |
| `tests/test_scoring_fairness.py::test_max_confidence_score_equal_across_strategies` | A perfect-data candidate from each strategy reaches the same confidence-score ceiling (within ±2) |
| `tests/test_scoring_fairness.py::test_balanced_pool_no_strategy_monopoly` | Given a 25-candidate fixture with one strong candidate per strategy, the top-4 finalists include candidates from at least 3 distinct strategies |
| `tests/test_scoring_fairness.py::test_weak_event_signal_does_not_make_C_uncompetitive` | A C candidate with a 5% surprise + 3% day-1 reaction (the threshold) reaches at least 60 final_score on otherwise-neutral data |
| `tests/test_scoring_fairness.py::test_D_with_strong_sector_signal_beats_A_with_average_earnings` | A D candidate with sector_perf_4w in top decile beats an A candidate with median EPS surprise on `final_score` |
| `tests/test_scoring_fairness.py::test_E_with_fresh_active_13d_beats_A_with_no_surprise` | A fresh E filing with high stake + active intent beats an A candidate with zero surprise |
| `tests/test_scoring_fairness.py::test_no_strategy_gets_double_credit` | Sum of weights stays constant per strategy; no strategy's perfect score exceeds 85 direction or 0.97 confidence |
| `tests/test_scoring_fairness.py::test_inconsistent_history_penalty_only_fires_for_strategy_A` | The inconsistent_history soft penalty doesn't punish C/D/E |

If the calibrated weights in §6.3.1 / §6.3.2 fail the balance test, retune **inside the test fixtures** (commit the chosen values with the regression suite that justifies them). Do not hand-tune in production code without a test that proves the new weights survive the balance suite.

### 6.5 What the LLM sees

`DECISION_FINALIST_LIMIT = 4` is unchanged. `_select_decision_finalists()` ([orchestrator.py:836-849](../app/pipeline/orchestrator.py#L836)) continues to sort by `(final_score, confidence.score, direction.score)`. Because the inputs are now strategy-neutral, the LLM should naturally see a more diverse finalist set.

Two **additive** fields on `CandidateBundle` ([app/llm/schemas.py:49](../app/llm/schemas.py#L49)) so the LLM can reason about why each finalist was surfaced:

```python
class CandidateBundle(_Frozen):
    ...
    # Use a plain str (not the StrategySource Literal) to avoid coupling
    # app/llm/schemas.py to the scoring/services layer. The value originates
    # from a Literal-validated source upstream so the runtime contract holds.
    strategy_source: str = "catalyst_confluence"   # NEW
    event_signal_detail: str | None = None         # NEW (sourced from candidate.context.event_signal.detail)
```

`build_decision_input()` and `_candidate_bundle()` ([decide.py:191, 420](../app/pipeline/steps/decide.py#L191)) populate the new fields. **No change to the validation gate** ([decide.py:203 `validate_llm_decision`](../app/pipeline/steps/decide.py#L203)) — it still rejects tickers/contracts outside the deterministic finalist set, and `validate_llm_decision()` still recomputes the deterministic `combine_scores()` so the user-visible final score remains bit-deterministic across runs.

LLM prompt update (in [app/llm/prompts/](../app/llm/prompts/)): add one line to the system prompt explaining `strategy_source` and the meaning of `event_signal_detail`. Do not change the decision schema — the heavy model still returns `StructuredDecision` ([schemas.py:91](../app/llm/schemas.py#L91)) unchanged.

### 6.6 Rollout safety

The rebalanced scoring is shipped behind a single config flag `SCORING_FAIRNESS_V2: bool = True`. If a regression slips through, flipping the flag to `False` restores the legacy A/B-only weights. The flag is removed after one month of clean weekly runs.

---

## 7. New / changed files (per layer)

### 7.1 Finviz query layer

```text
app/services/finviz/strategies.py
  + STRATEGY_C_BASE                       (PEAD: earningsdate_prevweek + sh_opt_option + ta_change_u)
  + STRATEGY_C_EARNINGS_PREFIX / VALUES   (mirrors STRATEGY_A_EARNINGS_PREFIX pattern)
  + build_strategy_d_query(sector_filter) -> FinvizQuery   # dynamic, runtime sector slug
```

### 7.2 SEC filings layer (new)

```text
app/services/sec/__init__.py
app/services/sec/filings_client.py        # async httpx client over EDGAR JSON endpoints
app/services/sec/activist_13d_parser.py   # SC 13D / 13D/A → ActivistFiling dataclass
app/services/sec/scoring.py               # event_score sub-scorers (Decimal, linear, capped)
```

`filings_client.py` reuses the SEC user-agent / throttling pattern already proven in [app/services/news/sources.py](../app/services/news/sources.py)'s `SecEdgarNewsSource` — extract a thin shared HTTP helper if duplication arises (do **not** refactor speculatively).

### 7.3 Per-strategy candidate services (new)

```text
app/services/pead_service.py
  PEADCandidateService
    - get_top_five() -> CandidateBatch
    - _compute_surprise(ticker)        # yfinance → Finnhub → Alpha Vantage
    - _post_filter(rows)               # surprise, day1, sector, market cap, T+1
    - _rank(rows) -> top 5 by score_C

app/services/sector_relative_strength_service.py
  SectorRelativeStrengthService
    - get_top_five() -> CandidateBatch
    - _rank_sectors()                  # yfinance batch download for 9 SPDRs
    - _regime_gate(top_etf) -> bool
    - _screen_top_sector(sector_filter)  # FinvizQueryRunner with dynamic query
    - _fallback_to_second_sector()     # only if second sector also passes gate

app/services/activist_13d_service.py
  Activist13DCandidateService
    - get_top_five() -> CandidateBatch
    - _fetch_recent_filings()          # via SECFilingsClient
    - _enrich_with_market(filings)     # market data + option liquidity for tier passers
    - _rank(filings) -> top 5 by event_score
```

All three follow the same async/`Decimal`/frozen-dataclass conventions as [app/services/coiled_setup_service.py](../app/services/coiled_setup_service.py) and [app/services/candidate_service.py](../app/services/candidate_service.py).

### 7.4 Multi-strategy aggregator (refactor)

```text
app/services/multi_strategy_service.py
  MultiStrategyCandidateService.__init__(arms: tuple[ArmRunner, ...])
    where ArmRunner = (slug, async callable -> CandidateBatch | tuple[CandidateRecord, ...])
  .get_candidates()
    asyncio.gather(*arms, return_exceptions=True)
    build StrategyRunReport per arm (success | empty | failed | partial)
    merge + dedupe in priority order:  A > C > B > D > E
    cap pool at 25 (5 arms × 5 each, post-dedupe upper bound)
```

**Tie-precedence rationale (from [strategy3_Claude.md §4](strategy3_Claude.md)):** A wins because earnings is the strongest single catalyst; C beats B because confirmed surprise + drift > pure structure; D below B because sector alignment is a broader signal; E last because event-scored 13D entries should defer to whichever earlier arm already surfaced them. **Open question for review:** B vs C precedence — Claude's spec says A > C > B > D, this plan keeps A > C > B > D > E. Confirm with user before implementation if behaviour changes will be visible in week-over-week regressions.

The catalyst-fallback warning string `FINVIZ_FALLBACK_WARNING` (`"⚠️ Finviz did not load correctly, so I used backup earnings data for this scan."`) and the existing `CATALYST_ONLY_WARNING` / `COILED_ONLY_WARNING` strings stay verbatim — they are part of the user-visible contract.

### 7.5 Strategy catalog

```text
app/services/strategy_catalog.py
  + _PEAD_DEFINITION                  (StrategyDefinition for C)
  + _SECTOR_RS_DEFINITION             (D — query_urls computed at scan time, see note)
  + _ACTIVIST_13D_DEFINITION          (E)
  extend _DEFINITIONS dict
```

For D, `query_urls` is dynamic. The `StrategyDefinition` should expose a `query_urls=()` default and the live URL gets attached at runtime to the `StrategyRunReport.query_urls` field (already a tuple) so the Telegram message can show the active sector.

### 7.6 Pipeline orchestrator

```text
app/pipeline/orchestrator.py
  PipelineOrchestrator.__init__
    + injection seams for pead, sector_rs, activist_13d (default to None → factory wires defaults)
  get_pipeline_orchestrator()
    instantiate the three new services and pass them through
```

`MultiStrategyCandidateService` is the sole touchpoint — orchestrator changes are pure DI plumbing. `DECISION_FINALIST_LIMIT = 4` is unchanged.

### 7.7 Scoring (rebalanced — see §6 for rationale)

```text
app/scoring/types.py
  + StrategyEventSignal frozen dataclass (score: int, is_supportive: bool, detail: str)
  + CandidateContext.event_signal: StrategyEventSignal | None = None
  Widen StrategySource Literal (mirror of candidate_models.py)

app/scoring/direction.py
  Replace _DIRECTION_WEIGHTS module-level dict with _direction_weights(strategy_source) -> dict
  Add _event_signal(candidate) helper that returns Decimal in [-1, +1] from candidate.event_signal
  Add reasons threading so the LLM payload sees why each strategy's event was scored

app/scoring/confidence.py
  Replace W_* module constants with _confidence_weights(strategy_source) -> Weights frozen dataclass
  Add _event_score(candidate, strategy_source) component (replaces hard-coded coiled_setup branch)
  Replace strategy_source == "coiled_setup" check with NO_EARNINGS_REQUIRED_STRATEGIES set

app/scoring/vetoes.py
  Replace strategy_source != "coiled_setup" check with strategy_source not in NO_EARNINGS_REQUIRED_STRATEGIES

app/scoring/penalties.py
  Skip inconsistent_history penalty for strategy_source not in EARNINGS_HISTORY_RELEVANT_STRATEGIES
  EARNINGS_HISTORY_RELEVANT_STRATEGIES = frozenset({"catalyst_confluence"})

app/scoring/__init__.py
  Export NO_EARNINGS_REQUIRED_STRATEGIES so services and alternative_recommendation_service consume the same set
```

### 7.8 Config (`app/core/config.py`)

```python
SCORING_FAIRNESS_V2: bool = True

PEAD_MIN_SURPRISE_PCT: Decimal = Decimal("0.05")
PEAD_MIN_DAY1_REACTION: Decimal = Decimal("0.03")
PEAD_MIN_MARKET_CAP_USD: Decimal = Decimal("300000000")
PEAD_MAX_MARKET_CAP_USD: Decimal = Decimal("10000000000")

SECTOR_RS_MIN_4W_RETURN: Decimal = Decimal("0.02")
SECTOR_RS_SMA_WINDOW: int = 50

ACTIVIST_13D_MIN_PRICE_USD: Decimal = Decimal("15")
ACTIVIST_13D_MIN_AVG_VOL: int = 750_000
ACTIVIST_13D_MIN_MARKET_CAP_USD: Decimal = Decimal("500000000")
ACTIVIST_13D_LOOKBACK_TIER1_DAYS: int = 5
ACTIVIST_13D_LOOKBACK_TIER2_DAYS: int = 10
ACTIVIST_13D_LOOKBACK_TIER3_DAYS: int = 20
ACTIVIST_13D_USER_AGENT: str = "EarningEdge research@earningedge.local"
```

All settings flow through `get_settings()` (cached). No direct `os.environ` reads.

### 7.9 Telegram

```text
app/telegram/templates/  (whichever module renders the run-summary card)
  extend the per-strategy status table renderer:

  | Strategy | Status   | Candidates |
  |----------|----------|------------|
  | A        | success  | 5          |
  | B        | success  | 5          |
  | C        | partial  | 2          |
  | D        | empty    | 0          |
  | E        | success  | 5          |
```

The renderer reads from `PipelineOutcome.strategy_reports` — already a tuple, so no schema change.

### 7.10 Run-scan-now compatibility

The "Run scan now" button in [app/telegram/handlers/menu.py:51](../app/telegram/handlers/menu.py#L51) calls `WorkflowRunner.run_workflow(user.id, trigger_type="manual")`. That entry point is unchanged. The dashboard does not yet have its own trigger endpoint (`app/api/` is empty); when added, it must route through the same `WorkflowRunner` to inherit the per-user Redis lock, the orchestrator, and all five strategies automatically. No new config gates.

## 8. Phased build plan

Phases are independently shippable. The order minimises pipeline risk: schema → plumbing → fairness rebalance → strategies one at a time → e2e dogfood.

Each phase below is structured as: **goal → preconditions → step-by-step file edits → tests → exit criteria → gotchas**.

---

### Phase 0 — Schema, types, exemption set (1 small PR)

**Goal.** Widen the type system to accept the three new strategy slugs without changing any user-visible behaviour. After this PR, `mypy app` is clean and the existing test suite still passes.

**Preconditions.** None — this is the first PR.

**Step-by-step:**

1. **Widen `StrategySource` in two places (must stay in lock-step):**
   - [app/services/candidate_models.py:9](../app/services/candidate_models.py#L9) — add the three slugs to the `Literal`.
   - [app/scoring/types.py:21](../app/scoring/types.py#L21) — same widening. Default for `CandidateContext.strategy_source` stays `"catalyst_confluence"`.
2. **Widen `ScreenerStatus` to `Literal["success", "partial", "failed", "empty"]`** at [candidate_models.py:8](../app/services/candidate_models.py#L8). Audit all `match`/`if` branches on `screener_status` and confirm `"empty"` is handled wherever the value is consumed (currently only in `MultiStrategyCandidateService.get_candidates`).
3. **Add `StrategyEventSignal`** as a frozen dataclass in `app/services/candidate_models.py` (placed next to `CandidateRecord`).
4. **Add `event_signal: StrategyEventSignal | None = None`** to **both** `CandidateRecord` and `CandidateContext` (in `scoring/types.py`). Re-export `StrategyEventSignal` from `app/scoring/types.py` to avoid cross-layer imports.
5. **Define `NO_EARNINGS_REQUIRED_STRATEGIES`** in a new module `app/scoring/strategy_policy.py` (so both `scoring/` and `services/` can import without a circular dep):
   ```python
   from app.scoring.types import StrategySource

   NO_EARNINGS_REQUIRED_STRATEGIES: frozenset[StrategySource] = frozenset({
       "coiled_setup",
       "sector_relative_strength",
       "activist_13d_followthrough",
   })
   EARNINGS_HISTORY_RELEVANT_STRATEGIES: frozenset[StrategySource] = frozenset({
       "catalyst_confluence",
   })
   ```
6. **Replace the three hard-coded `coiled_setup`-only checks** with `strategy_source not in NO_EARNINGS_REQUIRED_STRATEGIES`:
   - [app/scoring/vetoes.py:24](../app/scoring/vetoes.py#L24)
   - [app/scoring/confidence.py:100](../app/scoring/confidence.py#L100) — note the inverted polarity here (returns 20 when in the set, blocks otherwise).
   - [app/services/alternative_recommendation_service.py:402](../app/services/alternative_recommendation_service.py#L402)
7. **Plumb `event_signal` through the orchestrator.** Edit [app/pipeline/orchestrator.py:313-330](../app/pipeline/orchestrator.py#L313) to pass `event_signal=record.event_signal` into the `CandidateContext` constructor.
8. **Write Alembic revision `0013_strategy_source_widen.py`** with `down_revision = "0012_position_validation"`, `upgrade()` and `downgrade()` both no-op (per §5.1). Add a comment explaining why no DDL is required.
9. **Update LLM `CandidateBundle` schema** ([app/llm/schemas.py:49](../app/llm/schemas.py#L49)) to add `strategy_source: str = "catalyst_confluence"` (plain `str` to avoid coupling `app/llm/` to `app/scoring/`) and `event_signal_detail: str | None = None`. Update `_candidate_bundle()` ([decide.py:420](../app/pipeline/steps/decide.py#L420)) to populate them. Both default to safe values so existing fixtures don't break.
10. **Run the full quality suite locally:** `uv run ruff check . && uv run ruff format --check . && uv run black --check . && uv run mypy app && uv run pytest -q`.

**Tests (Phase 0):**
- `tests/test_migrations.py::test_0013_upgrade_downgrade_idempotent` — verifies the revision applies and reverses on `earning_edge_test` without DDL drift.
- `tests/test_scoring_engine.py::test_no_earnings_exemption_set_covers_new_strategies` — synthetic candidates with each new slug do not trigger `earnings_missing` veto when `earnings_date is None`.
- `tests/test_candidate_models.py::test_strategy_source_literal_widened` — `typing.get_args(StrategySource)` returns 5 values in both `candidate_models.py` and `scoring/types.py`.
- `tests/test_candidate_models.py::test_screener_status_includes_empty` — `typing.get_args(ScreenerStatus)` includes `"empty"`.
- `tests/test_candidate_models.py::test_event_signal_default_none` — a `CandidateRecord` constructed without `event_signal` has `event_signal is None` and is still hashable / frozen.

**Exit criteria:**
- Full pre-commit suite passes (`uv run pre-commit run --all-files`).
- `alembic upgrade head` and `alembic downgrade -1` round-trip on `earning_edge_test`.
- All existing tests in `tests/` pass unmodified.
- The Telegram run-summary still renders 2 rows (no behaviour change yet).

**Gotchas:**
- **Don't refactor the existing `_W_*` constants in this phase** — that is Phase 1.5. Phase 0 is type widening only.
- The `CandidateContext` default for `strategy_source` must remain `"catalyst_confluence"` — many tests construct it without that field.
- `StrategyEventSignal` defined in `services/candidate_models.py` must be importable from `app/scoring/types.py` without creating a cycle. The current import direction (`scoring` → `services.market_data`, `services.news`) confirms this works.

### Phase 1 — Multi-arm merge plumbing without new screens (1 PR)

**Goal.** Replace the hard-coded 2-arm gather in `MultiStrategyCandidateService` with an N-arm runner. Inject 3 stub arms returning `CandidateBatch(candidates=(), screener_status="empty")` so production output is identical to today, but the plumbing now supports the real strategies in Phases 2-4.

**Preconditions.** Phase 0 merged.

**Step-by-step:**

1. **Normalise the arm interface to `CandidateBatch`.** [app/services/coiled_setup_service.py:25](../app/services/coiled_setup_service.py#L25) currently returns `tuple[CandidateRecord, ...]`. Change its signature to return `CandidateBatch` (with `screener_status="success"|"empty"|"failed"` and `strategy_reports=()` filled by `build_strategy_report`). Update `MultiStrategyCandidateService` callers accordingly.
2. **Define `ArmRunner` protocol** in [app/services/multi_strategy_service.py](../app/services/multi_strategy_service.py):
   ```python
   class ArmRunner(Protocol):
       slug: StrategySource
       async def get_top_five(self, *, limit: int = 5) -> CandidateBatch: ...
   ```
3. **Refactor `MultiStrategyCandidateService.__init__`** to accept `arms: tuple[ArmRunner, ...]` instead of two named services. Provide a backward-compat factory:
   ```python
   def __init__(self, arms: tuple[ArmRunner, ...], *, logger=None) -> None:
       self.arms = arms
       self.logger = logger or get_logger(__name__)
   ```
4. **Refactor `get_candidates()`** to:
   - Run `asyncio.gather(*(arm.get_top_five() for arm in self.arms), return_exceptions=True)`.
   - For each result: if exception, build a `failed` report; if `CandidateBatch`, extract its rows + report.
   - Merge in priority order **A > C > B > D > E** by iterating `self.arms` in that order. Keep the existing `_merge_dedupe` helper but generalise it to take a list of `(slug, rows)` pairs.
   - Build the consolidated `screener_status`:
     - all arms `success` or `partial` → `success`.
     - all arms `failed` or `empty` with no rows → `failed`.
     - any rows present but ≥1 arm failed/empty → `partial`.
   - Preserve **all three legacy warning strings verbatim** (`FINVIZ_FALLBACK_WARNING`, `CATALYST_ONLY_WARNING`, `COILED_ONLY_WARNING`, `BOTH_FAILED_WARNING`, `CATALYST_FAILED_WARNING`, `COILED_FAILED_WARNING`). Add new strings only if needed for the new arms.
5. **Inject 3 stub arms** in `get_multi_strategy_service()`:
   ```python
   class _EmptyArm:
       def __init__(self, slug: StrategySource) -> None: self.slug = slug
       async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
           return CandidateBatch(
               candidates=(), screener_status="empty", fallback_used=False,
               strategy_reports=(build_strategy_report(self.slug, status="empty",
                                                      raw_row_count=0, candidate_count=0),),
           )
   ```
   Wire as `arms=(catalyst, _EmptyArm("pead_continuation"), coiled, _EmptyArm("sector_relative_strength"), _EmptyArm("activist_13d_followthrough"))`.
6. **Add stub `StrategyDefinition` entries** to [app/services/strategy_catalog.py](../app/services/strategy_catalog.py) for the three new slugs (so `build_strategy_report` doesn't `KeyError` on the empty-arm reports). `query_urls=()` is fine for stubs.
7. **Extend `PipelineOrchestrator.__init__`** to accept the new `multi_strategy_service` shape unchanged (the orchestrator already takes the service via DI; nothing else changes).
8. **Update the Telegram run-summary renderer** (find via `grep -rn "strategy_reports" app/telegram/`) to render 5 rows instead of 2. Use the slug → display label mapping from `strategy_catalog.py`.
9. **Run** `uv run pytest -q` — all existing tests must pass; the new tests below must pass.

**Tests (Phase 1):**
- `tests/test_multi_strategy_service.py::test_five_arm_merge_with_empty_stubs_matches_legacy_output` — given today's A and B fixtures and 3 empty-arm stubs, the returned `CandidateBatch.candidates` is identical to the 2-arm baseline.
- `tests/test_multi_strategy_service.py::test_tie_precedence_a_over_c_over_b_over_d_over_e` — same ticker present in 5 batches resolves to A's record (verifies dedupe order).
- `tests/test_multi_strategy_service.py::test_one_arm_raises_others_succeed_partial_status` — one arm raises, the other four succeed, batch reports `partial` and lists the failed arm in `strategy_reports` with `status="failed"`.
- `tests/test_multi_strategy_service.py::test_screener_status_empty_propagates` — an `"empty"` arm appears in `strategy_reports` with `candidate_count=0` and does not fabricate rows.
- `tests/test_multi_strategy_service.py::test_legacy_warning_strings_unchanged` — `FINVIZ_FALLBACK_WARNING` and the catalyst/coiled warning strings still match byte-for-byte.
- `tests/test_coiled_setup_service.py::test_returns_candidate_batch_not_tuple` — interface normalisation regression.

**Exit criteria:**
- All Phase-0 tests still pass.
- Telegram dogfood (manual): trigger a scan, confirm the run-summary card shows 5 rows (3 of them `empty`).
- Diff `final_score` for the existing fixtures: identical to pre-Phase-1 (no scoring change yet).

**Gotchas:**
- The 5-arm gather uses 5 concurrent network paths now (Finviz × 2 + 3 stubs + downstream fan-out is unchanged). Phase 1 uses stubs so no real load increase, but Phase 4 lights up SEC EDGAR; the run-lock TTL (`WORKFLOW_RUN_LOCK_TTL_SECONDS=900s`) has headroom.
- Don't change the LLM payload yet — Phase 0 already added the optional `strategy_source` and `event_signal_detail` fields with safe defaults.
- The `_merge_dedupe` change must preserve the existing test in `test_multi_strategy_service.py::test_dedupe_preserves_catalyst_priority` if such a test exists — find via `grep -n "dedupe" tests/test_multi_strategy_service.py` and update it to the new precedence.

### Phase 1.5 — Scoring fairness rebalance (1 PR — must land before Phase 2)

**Goal.** Replace the static scoring weights with strategy-aware weights so all 5 strategies can theoretically reach the same score ceiling and an actual balanced 25-candidate pool produces a diverse top 4. **This is the load-bearing change** — without it, Phases 2–4 will produce candidates that the legacy scorer systematically demotes to the bottom of the pool.

**Preconditions.** Phases 0 and 1 merged.

**Step-by-step:**

0. **Commit the fairness suite skeleton as `xfail` first.** Create `tests/test_scoring_fairness.py` with all 11 §6.4 tests written but marked `@pytest.mark.xfail(reason="Phase 1.5 rebalance pending")`. This commit is a separate small PR right before the main rebalance PR. It gives the rebalance work a concrete target and prevents the rebalance PR from ballooning.
1. **Introduce `SCORING_FAIRNESS_V2` config flag.** Add to [app/core/config.py](../app/core/config.py):
   ```python
   SCORING_FAIRNESS_V2: bool = True
   ```
   Every weight-change site below reads `get_settings().scoring_fairness_v2` and falls back to legacy constants when `False`. This is the **rollback lever** — flipping to `False` must restore byte-identical pre-rebalance scores.
2. **Convert `_DIRECTION_WEIGHTS` to a function** in [app/scoring/direction.py:35-43](../app/scoring/direction.py#L35):
   ```python
   _LEGACY_WEIGHTS: dict[str, int] = {  # keep for v2=False rollback path
       "trend alignment": 20, "relative strength": 15, "volume confirmation": 10,
       "earnings expectation context": 15, "market/sector environment": 10,
       "price structure": 10, "data confidence": 5,
   }

   _V2_WEIGHTS_BY_STRATEGY: dict[StrategySource, dict[str, int]] = {
       "catalyst_confluence":         {"trend alignment": 20, "relative strength": 15, "volume confirmation": 10, "earnings expectation context": 15, "event signal": 0,  "market/sector environment": 10, "price structure": 10, "data confidence": 5},
       "coiled_setup":                {"trend alignment": 20, "relative strength": 18, "volume confirmation": 10, "earnings expectation context": 0,  "event signal": 7,  "market/sector environment": 10, "price structure": 15, "data confidence": 5},
       "pead_continuation":           {"trend alignment": 18, "relative strength": 15, "volume confirmation": 12, "earnings expectation context": 8,  "event signal": 7,  "market/sector environment": 10, "price structure": 10, "data confidence": 5},
       "sector_relative_strength":    {"trend alignment": 15, "relative strength": 18, "volume confirmation": 10, "earnings expectation context": 0,  "event signal": 15, "market/sector environment": 12, "price structure": 10, "data confidence": 5},
       "activist_13d_followthrough":  {"trend alignment": 15, "relative strength": 15, "volume confirmation": 12, "earnings expectation context": 0,  "event signal": 15, "market/sector environment": 10, "price structure": 13, "data confidence": 5},
   }

   def _direction_weights(strategy_source: StrategySource) -> dict[str, int]:
       if not get_settings().scoring_fairness_v2:
           return _LEGACY_WEIGHTS
       return _V2_WEIGHTS_BY_STRATEGY[strategy_source]
   ```
   Each row sums to **85** — verify with a unit test (`test_no_strategy_gets_double_credit`).
3. **Add `_event_signal(candidate) -> Decimal | None`** helper in `direction.py`. Returns:
   - `None` if `candidate.event_signal is None` (skips the factor).
   - `Decimal(event_signal.score) / Decimal("100") * (1 if event_signal.is_supportive else -1)`.
4. **Wire `_event_signal()` into `score_direction()`.** Add `"event signal"` to the `signals` dict, mirroring the existing pattern at [direction.py:49-56](../app/scoring/direction.py#L49). Update `_DIRECTION_WEIGHTS` references inside `score_direction()` to call `_direction_weights(candidate.strategy_source)`. The `total_weight` calculation must subtract `"data confidence"` exactly once (preserve the existing semantics).
5. **Convert confidence weights** in [app/scoring/confidence.py:23-28](../app/scoring/confidence.py#L23) to a function:
   ```python
   @dataclass(frozen=True, slots=True)
   class ConfidenceWeights:
       identity: float; earnings: float; event: float; market: float
       options: float; cross_source: float; calculation: float

   _LEGACY_CONFIDENCE = ConfidenceWeights(0.13, 0.25, 0.0, 0.20, 0.22, 0.10, 0.07)
   _V2_CONFIDENCE: dict[StrategySource, ConfidenceWeights] = {
       "catalyst_confluence":        ConfidenceWeights(0.13, 0.25, 0.00, 0.20, 0.22, 0.10, 0.07),
       "coiled_setup":               ConfidenceWeights(0.13, 0.00, 0.20, 0.25, 0.22, 0.10, 0.07),
       "pead_continuation":          ConfidenceWeights(0.13, 0.20, 0.05, 0.22, 0.22, 0.10, 0.05),
       "sector_relative_strength":   ConfidenceWeights(0.13, 0.00, 0.20, 0.25, 0.22, 0.10, 0.07),
       "activist_13d_followthrough": ConfidenceWeights(0.13, 0.00, 0.20, 0.22, 0.22, 0.10, 0.10),
   }

   def _confidence_weights(strategy_source: StrategySource) -> ConfidenceWeights:
       return (_LEGACY_CONFIDENCE if not get_settings().scoring_fairness_v2
               else _V2_CONFIDENCE[strategy_source])
   ```
   Each row sums to **0.97**. Audit-tested by `test_no_strategy_gets_double_credit`.
6. **Add `_event_score()` component** to `confidence.py`, mirroring `_earnings_score()`. Returns `0..MAX_EVENT` based on `candidate.event_signal.score`. `MAX_EVENT = 20`. When the strategy's `W_EVENT == 0`, `_event_score()` is still computed (cheap) but its weight is zero so it contributes nothing.
7. **Replace the `coiled_setup`-only check inside `_earnings_score()`** ([confidence.py:100](../app/scoring/confidence.py#L100)) with `strategy_source in NO_EARNINGS_REQUIRED_STRATEGIES`. This was already done in Phase 0 — verify it's still in place.
8. **Refactor the `inconsistent_history` penalty** at [penalties.py:133-145](../app/scoring/penalties.py#L133):
   ```python
   if candidate.strategy_source not in EARNINGS_HISTORY_RELEVANT_STRATEGIES:
       return tuple(penalties)  # skip the entire history-comparison block
   ```
   `EARNINGS_HISTORY_RELEVANT_STRATEGIES = frozenset({"catalyst_confluence"})` — defined in `app/scoring/strategy_policy.py` from Phase 0. Note that today the penalty already never fires (because `previous_earnings_move_percent is None` in production) — this is defence in depth for the day someone wires up earnings history.
9. **Backfill `event_signal` for B** in [app/services/coiled_setup_service.py](../app/services/coiled_setup_service.py). Compute:
   ```python
   event_signal = StrategyEventSignal(
       score=int(min(Decimal("100"),
                     dist_from_52w_high_percentile * Decimal("50") +
                     relative_volume_percentile * Decimal("50"))),
       is_supportive=True,
       detail=f"Coiled setup: {dist_from_52w_high_pct:.1%} from 52w high, "
              f"{relative_volume_x:.1f}x avg volume",
   )
   ```
   Attach to each `CandidateRecord` before returning. Source the percentiles from the existing Finviz row data — no new network calls.
10. **Wire the LLM payload.** [app/pipeline/steps/decide.py `_candidate_bundle()`](../app/pipeline/steps/decide.py#L420) was extended in Phase 0 with placeholder fields; now populate them:
    ```python
    strategy_source=candidate.context.strategy_source,
    event_signal_detail=(candidate.context.event_signal.detail
                         if candidate.context.event_signal else None),
    ```
11. **Calibrate against the fairness suite.** Run `pytest tests/test_scoring_fairness.py -q` after each weight change. If a test fails, retune the weights **inside `_V2_WEIGHTS_BY_STRATEGY` / `_V2_CONFIDENCE`** until the suite passes. The starting numbers in §6.3.1 / §6.3.2 are the author's first calibration; treat them as a starting point, not gospel.
12. **Run regression on legacy fixtures.** A and B candidate scores from existing fixtures must stay within ±3 points (see §6.4 regression tests). If they don't, the rollback flag is the safety net.

**Tests (Phase 1.5) — the §6.4 fairness suite:**
- `tests/test_scoring_fairness.py::test_max_direction_score_equal_across_strategies`
- `tests/test_scoring_fairness.py::test_max_confidence_score_equal_across_strategies`
- `tests/test_scoring_fairness.py::test_balanced_pool_no_strategy_monopoly`
- `tests/test_scoring_fairness.py::test_weak_event_signal_does_not_make_C_uncompetitive`
- `tests/test_scoring_fairness.py::test_D_with_strong_sector_signal_beats_A_with_average_earnings`
- `tests/test_scoring_fairness.py::test_E_with_fresh_active_13d_beats_A_with_no_surprise`
- `tests/test_scoring_fairness.py::test_no_strategy_gets_double_credit`
- `tests/test_scoring_fairness.py::test_inconsistent_history_penalty_only_fires_for_strategy_A`
- `tests/test_scoring_engine.py::test_legacy_A_candidate_score_within_3_points_of_pre_v2`
- `tests/test_scoring_engine.py::test_legacy_B_candidate_score_within_3_points_of_pre_v2`
- `tests/test_scoring_engine.py::test_v2_off_restores_byte_identical_legacy_scores` — flag-off rollback path produces identical scores to today's `main`.

**Existing tests that may need updates (audit before changing):**
- `tests/test_scoring_engine.py::test_direction_score_golden_table` — locks A's direction score at `(84, 76, 49)` for three fixtures. Because A's V2 weight row is identical to legacy weights (event signal weight 0), these values **should** stay unchanged. Confirm with a diff after Phase 1.5 lands; if they shift even by 1 point, the test must be updated with a comment pointing to this plan.
- `tests/test_scoring_engine.py::test_coiled_setup_without_earnings_date_uses_dte_expiry_window` — now also exercises the V2 confidence weights for B. Likely passes unchanged but verify.
- `tests/test_scoring_engine.py::test_confidence_override_blocks_recommendation_despite_high_score` — verify the threshold semantics (`< 40 → blockers`) still hold.

**Exit criteria (HARD):**
- All 11 fairness tests above pass.
- The 2 legacy-A-and-B regression tests pass.
- Existing `test_scoring_engine.py` golden tables either pass unchanged **or** are updated with a one-line comment explaining the change and a `pytest -q` confirmation that the change is intended.
- `SCORING_FAIRNESS_V2 = False` produces byte-identical scores to pre-rebalance `main` (regression-tested).
- `mypy app` strict, ruff, black all clean.

**Gotchas:**
- **Do not** ship Phase 2 if the fairness suite fails. The whole multi-strategy story collapses if C/D/E candidates can't compete.
- The fairness tests use **synthetic candidates** with controlled `event_signal` and `market_snapshot` values — they do not depend on real Finviz / yfinance / EDGAR data. Build a `_make_synthetic_candidate(strategy: StrategySource, **overrides)` helper in `tests/conftest.py` or a per-suite `_helpers.py`.
- `_select_decision_finalists()` ([orchestrator.py:836](../app/pipeline/orchestrator.py#L836)) sorts by `(final_score, confidence, direction)` — already strategy-neutral. **No changes needed** here.
- The `combine_scores()` blend at [final.py:22-26](../app/scoring/final.py#L22) (`0.45 × direction + 0.55 × contract`) **stays untouched**. Contract-side scoring is strategy-agnostic and does not require rebalancing.
- The `direction_score < 40` → `classification = "avoid"` rule at [direction.py:68-69](../app/scoring/direction.py#L68) interacts with the rebalance: a low confidence will still flip the candidate to `avoid`. The fairness tests must use confidence ≥ 70 fixtures to isolate the weight-change effect.
- **Don't refactor `score_contract()` or `evaluate_hard_vetoes()` payload signatures.** Phase 1.5 only changes weights and the `inconsistent_history` skip — those signatures stay intact.

### Phase 2 — Strategy C (PEAD) (1 PR)

**Goal.** Implement `PEADCandidateService` end-to-end and replace the empty-arm stub from Phase 1. After this PR, real PEAD candidates flow into the 25-pool and compete fairly.

**Preconditions.** Phases 0, 1, 1.5 merged. The fairness suite is green.

**Step-by-step:**

1. **Extend Finviz strategies** ([app/services/finviz/strategies.py](../app/services/finviz/strategies.py)):
   ```python
   STRATEGY_C_BASE = FinvizQuery(
       filters=("earningsdate_prevweek", "geo_usa", "sh_opt_option",
                "sh_price_o10", "sh_avgvol_o500", "ta_change_u"),
       sort="-change",
   )
   STRATEGY_C_EARNINGS_PREFIX = "earningsdate_"
   STRATEGY_C_EARNINGS_VALUES: tuple[str, ...] = ("earningsdate_prevweek", "earningsdate_yesterday")
   ```
2. **Add config keys** to [app/core/config.py](../app/core/config.py): `PEAD_MIN_SURPRISE_PCT`, `PEAD_MIN_DAY1_REACTION`, `PEAD_MIN_MARKET_CAP_USD`, `PEAD_MAX_MARKET_CAP_USD` (values from §7.8).
3. **Create `app/services/pead_service.py`:**
   ```python
   class PEADCandidateService:
       slug: StrategySource = "pead_continuation"

       def __init__(self, runner: FinvizQueryRunner, *, market_data, finnhub_client,
                    alpha_vantage_client, settings: Settings | None = None,
                    logger=None) -> None: ...

       async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
           rows = await self.runner.run_with_swap(STRATEGY_C_BASE, ...,
                                                  strategy_source=self.slug, limit=20)
           enriched = await asyncio.gather(*[self._enrich(row) for row in rows])
           filtered = [r for r in enriched if r is not None]
           ranked = sorted(filtered, key=lambda r: r.score_c, reverse=True)[:limit]
           return self._build_batch(ranked, raw_count=len(rows))

       async def _enrich(self, row) -> EnrichedRow | None: ...
       async def _compute_surprise(self, ticker: str) -> Decimal | None: ...
       def _post_filter(self, row, surprise, day1, sector, market_cap, ann_date): ...
       def _score_c(self, surprise, day1, sector) -> Decimal: ...
   ```
4. **Implement `_compute_surprise()`** with the fallback chain:
   - Try `await asyncio.to_thread(yfinance_ticker.get_earnings_history, ticker)` — wrap in `try/except`.
   - On failure, call existing Finnhub client (already wired via `FinnhubEarningsSource`).
   - On failure, call Alpha Vantage `EARNINGS` endpoint.
   - On final failure, return `None` and log a structured warning. **Fallback beats abort** — matches CLAUDE.md convention.
5. **Implement post-filter** — drop the row if any of:
   - `surprise < PEAD_MIN_SURPRISE_PCT` (Decimal `0.05`).
   - `day1_change_pct < PEAD_MIN_DAY1_REACTION` (Decimal `0.03`).
   - `sector in {"Technology", "Communication Services"}`.
   - `market_cap < 300M` or `> 10B`.
   - `announcement_date == today` (T+1 minimum — verify via the row's earnings_date).
6. **Implement `score_c`** per §4.1 formula. Return as Decimal so ranking is deterministic.
7. **Populate `CandidateRecord.event_signal`** for each surviving row:
   ```python
   event_signal = StrategyEventSignal(
       score=int(min(Decimal("100"),
                     (surprise / Decimal("0.05")) * Decimal("50") +
                     (day1 / Decimal("0.03")) * Decimal("50"))),
       is_supportive=True,  # bullish-only in v1
       detail=f"Earnings surprise {surprise:.1%}, day-1 reaction {day1:+.1%}",
   )
   ```
8. **Cross-arm dedupe rule.** Before returning, check `open_positions` (via the existing repo) and drop any ticker that already has an A-strategy position open within the past 7 days. This implements the cross-arm rule in §4.1. Keep this conservative: drop, don't penalise.
9. **Wire into `MultiStrategyCandidateService`.** Replace the `_EmptyArm("pead_continuation")` stub from Phase 1 with the real service. Update `get_multi_strategy_service()` to instantiate the dependencies (it already has `finnhub_api_key` from settings).
10. **Add `_PEAD_DEFINITION`** to [app/services/strategy_catalog.py](../app/services/strategy_catalog.py) with concrete `criteria_summary`, `sort_summary`, and `query_urls` (computed from `STRATEGY_C_BASE.with_filter_replaced(STRATEGY_C_EARNINGS_PREFIX, value).to_url()` for each earnings variant).
11. **Run** the Phase 2 test suite + the full regression suite + the fairness suite from Phase 1.5. All must pass.

**Tests (Phase 2):**
- `tests/test_pead_service.py::test_post_filter_drops_below_surprise_threshold`
- `tests/test_pead_service.py::test_post_filter_drops_tech_and_communication_services`
- `tests/test_pead_service.py::test_post_filter_drops_outside_market_cap_band`
- `tests/test_pead_service.py::test_post_filter_drops_same_day_announcement`
- `tests/test_pead_service.py::test_yfinance_failure_falls_back_to_finnhub`
- `tests/test_pead_service.py::test_finnhub_failure_falls_back_to_alpha_vantage`
- `tests/test_pead_service.py::test_all_three_data_sources_fail_returns_empty_batch`
- `tests/test_pead_service.py::test_top_5_ranking_by_composite_score`
- `tests/test_pead_service.py::test_partial_batch_when_fewer_than_5_pass`
- `tests/test_pead_service.py::test_does_not_pad_with_unconfirmed_names`
- `tests/test_pead_service.py::test_event_signal_populated_with_surprise_and_day1` — new
- `tests/test_pead_service.py::test_cross_arm_dedupe_skips_open_strategy_a_positions` — new
- Integration: `tests/test_pipeline_orchestrator.py::test_pead_arm_contributes_to_finalists`

**Exit criteria:**
- 13 Phase-2 tests pass.
- Phase 1.5 fairness suite still passes (no weight regression).
- Manual dogfood: a real scan returns at least one PEAD candidate during a US earnings season week, visible in the Telegram run-summary card.

**Gotchas:**
- yfinance's `get_earnings_history()` is **synchronous** — wrap with `asyncio.to_thread()` (CLAUDE.md convention; see [app/services/market_data/yf_client.py](../app/services/market_data/yf_client.py) for the existing pattern).
- The Finviz `earningsdate_prevweek` filter is the only confirmed-working "recently reported" filter — `earningsdate_prev5days` silently drops. Verified by the upstream agent panel in [strategy3_Claude.md §2.2](strategy3_Claude.md).
- Alpha Vantage free tier is **25 calls/day**. Use it as tertiary fallback only — most weeks it should never fire.
- The `score_c` formula uses Decimal — do not introduce floats (CLAUDE.md `Decimal for money` rule).
- The cross-arm dedupe must use the existing `OpenPositionsRepository`, not raw SQL.

### Phase 3 — Strategy D (Sector Relative Strength) (1 PR)

**Goal.** Implement `SectorRelativeStrengthService` end-to-end and replace the Phase-1 stub. Includes the two-step regime gate that returns an empty batch when the market lacks dispersion.

**Preconditions.** Phases 0, 1, 1.5 merged. Phase 2 may be parallel — D has no dependency on PEAD.

**Step-by-step:**

1. **Extend Finviz strategies** ([app/services/finviz/strategies.py](../app/services/finviz/strategies.py)):
   ```python
   _STRATEGY_D_BASE_FILTERS = ("geo_usa", "sh_opt_option", "sh_price_o10",
                               "sh_avgvol_o500", "ta_sma50_pa")

   def build_strategy_d_query(sector_filter: str) -> FinvizQuery:
       if not sector_filter.startswith("sec_"):
           raise ValueError(f"Expected sec_* filter, got {sector_filter!r}")
       return FinvizQuery(
           filters=(sector_filter, *_STRATEGY_D_BASE_FILTERS),
           sort="-perf4w",
       )
   ```
2. **Define sector mapping** in [app/services/sector_relative_strength_service.py](../app/services/sector_relative_strength_service.py):
   ```python
   _NON_TECH_SECTORS: tuple[tuple[str, str], ...] = (
       ("XLE", "sec_energy"), ("XLF", "sec_financial"),
       ("XLI", "sec_industrials"), ("XLV", "sec_healthcare"),
       ("XLU", "sec_utilities"), ("XLP", "sec_consumerdefensive"),
       ("XLY", "sec_consumercyclical"), ("XLB", "sec_basicmaterials"),
       ("XLRE", "sec_realestate"),
   )
   _EXCLUDED_ETFS = frozenset({"XLK", "XLC"})  # explicit guardrail
   ```
3. **Implement `SectorRelativeStrengthService`:**
   ```python
   class SectorRelativeStrengthService:
       slug: StrategySource = "sector_relative_strength"

       def __init__(self, runner: FinvizQueryRunner, *, market_data,
                    settings: Settings | None = None, logger=None) -> None: ...

       async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
           ranked_sectors = await self._rank_sectors()
           if not ranked_sectors:
               return self._empty_batch("yfinance unavailable")
           top_etf, top_filter, top_perf, top_above_sma = ranked_sectors[0]
           if not self._regime_gate(top_above_sma, top_perf):
               return self._empty_batch("regime gate blocked")
           rows = await self._screen_sector(top_filter, limit)
           if len(rows) < limit:
               second = next((s for s in ranked_sectors[1:]
                              if self._regime_gate(s.above_sma, s.perf_4w)), None)
               if second is not None:
                   rows.extend(await self._screen_sector(second.filter,
                                                        limit - len(rows)))
           ranked = self._rank_rows(rows, top_perf)[:limit]
           return self._build_batch(ranked, top_etf, top_perf)
   ```
4. **Implement `_rank_sectors()`** with a single yfinance batch call:
   ```python
   data = await asyncio.to_thread(
       yf.download, [etf for etf, _ in _NON_TECH_SECTORS],
       period="2mo", interval="1d", progress=False, auto_adjust=False,
   )
   ```
   For each ETF: compute `perf_4w = (close[-1] / close[-21] - 1)` and `above_sma = close[-1] >= sma50`. Sort by `perf_4w` descending. Return as a frozen `RankedSector` dataclass.
5. **Implement `_regime_gate()`** per §4.2:
   ```python
   def _regime_gate(self, above_sma: bool, perf_4w: Decimal) -> bool:
       return above_sma and perf_4w >= get_settings().sector_rs_min_4w_return
   ```
6. **Implement `_screen_sector()`** — call `self.runner.run_with_swap(build_strategy_d_query(filter), ..., strategy_source=self.slug, limit=limit)`.
7. **Compute `event_signal`** for each row per §6.3.4:
   ```python
   event_signal = StrategyEventSignal(
       score=int(min(Decimal("100"),
                     sector_perf_4w_percentile * Decimal("60") +
                     stock_perf_4w_percentile * Decimal("40"))),
       is_supportive=True,
       detail=f"{top_etf} sector +{top_perf:.1%} (4w), stock perf "
              f"{stock_perf:.1%}",
   )
   ```
   Percentiles can be computed inside the candidate set (rank within the 5 picked rows) — do not call additional sources.
8. **Wire into `MultiStrategyCandidateService`** — replace the `_EmptyArm("sector_relative_strength")` stub.
9. **Add `_SECTOR_RS_DEFINITION`** to `strategy_catalog.py` with `query_urls=()` (populated at runtime onto the `StrategyRunReport.query_urls` so the Telegram message shows the active sector).
10. **Add config keys** `SECTOR_RS_MIN_4W_RETURN`, `SECTOR_RS_SMA_WINDOW`.

**Tests (Phase 3):**
- `tests/test_sector_relative_strength_service.py::test_ranks_etfs_by_4w_return`
- `tests/test_sector_relative_strength_service.py::test_excludes_xlk_and_xlc_unconditionally`
- `tests/test_sector_relative_strength_service.py::test_regime_gate_blocks_when_top_below_sma50`
- `tests/test_sector_relative_strength_service.py::test_regime_gate_blocks_when_dispersion_below_2pct`
- `tests/test_sector_relative_strength_service.py::test_drops_to_second_sector_when_first_returns_fewer_than_5`
- `tests/test_sector_relative_strength_service.py::test_does_not_drop_to_second_sector_when_second_fails_regime_gate`
- `tests/test_sector_relative_strength_service.py::test_dynamic_finviz_url_built_correctly`
- `tests/test_sector_relative_strength_service.py::test_returns_empty_batch_when_yfinance_fails`
- `tests/test_sector_relative_strength_service.py::test_event_signal_populated_with_sector_and_stock_percentiles` — new
- `tests/test_sector_relative_strength_service.py::test_strategy_run_report_query_urls_show_active_sector` — new
- Integration: `tests/test_pipeline_orchestrator.py::test_sector_rs_arm_contributes_to_finalists`

**Exit criteria:**
- 11 Phase-3 tests pass.
- Manual dogfood: under a regime where at least one non-tech sector has +2% 4w dispersion and is above its SMA-50, D contributes 5 candidates. Under a flat regime, D contributes 0 with `screener_status="empty"` and a friendly Telegram line.

**Gotchas:**
- `build_strategy_d_query` must validate the input prefix to prevent injection of arbitrary Finviz filter strings.
- `XLK` and `XLC` are not in `_NON_TECH_SECTORS`, but the `_EXCLUDED_ETFS` set is a defensive guardrail. The test `test_excludes_xlk_and_xlc_unconditionally` codifies this.
- yfinance `download()` returns a multi-index DataFrame for multiple tickers — handle the `('Close', etf)` indexing carefully, and skip ETFs with NaN closing prices on the lookback boundary.
- The 4-week-return calculation uses **trading days** (≈21 sessions), not calendar days. Use the index length — do not assume calendar arithmetic.
- The "second sector fallback" must re-check the regime gate on the second sector — never drop into a sector that fails the gate just because the first sector ran short.

### Phase 4 — Strategy E (Activist 13D) (1 PR)

**Goal.** Implement the SEC filings client, the SC 13D parser, the deterministic `event_score`, and `Activist13DCandidateService`. Replace the Phase-1 stub.

**Preconditions.** Phases 0, 1, 1.5 merged. Phases 2 and 3 may be parallel.

**Step-by-step:**

1. **Create `app/services/sec/__init__.py`** (empty).
2. **Implement `app/services/sec/filings_client.py`** — async httpx client over EDGAR JSON:
   ```python
   class SECFilingsClient:
       def __init__(self, *, user_agent: str, throttle_rps: int = 8,
                    timeout: float = 10.0, logger=None) -> None:
           if not user_agent or "@" not in user_agent:
               raise ValueError("SEC requires a User-Agent with a contact email.")
           self.user_agent = user_agent
           self._semaphore = asyncio.Semaphore(throttle_rps)
           self._client = httpx.AsyncClient(
               timeout=timeout,
               headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
           )

       async def fetch_recent_filings(self, *, form_type: Literal["SC 13D", "SC 13D/A"],
                                      lookback_days: int) -> tuple[FilingHeader, ...]: ...
       async def fetch_filing_document(self, accession: str, primary_doc: str) -> str: ...
       async def close(self) -> None: await self._client.aclose()
   ```
   - **SEC fair-access:** max 10 requests/second per User-Agent. The semaphore + 100 ms cool-down inside `_request()` keeps us at ~8 rps with safety margin.
   - **429 handling:** exponential backoff with jitter (1s, 2s, 4s, then give up). Log structured warnings.
   - **Caching:** cache successful filing fetches by accession in Redis with a 24h TTL (use the same Redis client as `app/services/run_lock.py`).
3. **Implement `app/services/sec/activist_13d_parser.py`:**
   ```python
   @dataclass(slots=True, frozen=True)
   class ActivistFiling:
       cik: str
       ticker: str | None        # may need a CIK→ticker resolver
       filer_name: str
       accession: str
       form_type: Literal["SC 13D", "SC 13D/A"]
       filing_date: date
       stake_percent: Decimal | None
       item4_active_intent: bool
       primary_doc_url: str

   def parse_filing(header: FilingHeader, document_text: str) -> ActivistFiling | None: ...
   ```
   - `item4_active_intent`: a conservative classifier. Active language includes phrases like "proposals", "board representation", "engagement with management", "strategic alternatives", "operational changes", "shareholder rights". Passive includes "investment purposes only", "no plans or proposals". When unsure → **return `False` (drop)**, as documented in §10 risks.
   - `stake_percent`: parsed from the cover page percent field; tolerate variants like `5.2%`, `5.20`, `Five point two`. Return `None` on failure → drop.
   - CIK → ticker mapping: use EDGAR's `company_tickers.json` (cached daily) — reuse the same pattern as `SecEdgarNewsSource` in [app/services/news/sources.py](../app/services/news/sources.py).
4. **Implement `app/services/sec/scoring.py`** — deterministic sub-scorers (all Decimal, linear, capped):
   ```python
   def stake_size_score(stake: Decimal | None) -> Decimal:  # [0, 20]
       if stake is None: return ZERO
       return min(Decimal("20"), stake * Decimal("2"))   # 10% stake → 20 pts
   def active_intent_score(active: bool) -> Decimal: return Decimal("15") if active else ZERO
   def recency_score(filing_date: date, today: date) -> Decimal:  # [0, 15]
       days = (today - filing_date).days
       if days <= 5: return Decimal("15")
       if days <= 10: return Decimal("10")
       if days <= 20: return Decimal("5")
       return ZERO
   # similar capped/linear scorers for filer_quality, rel_vol, price_confirmation,
   # option_liquidity, gap_exhaustion_penalty, earnings_collision_penalty,
   # tech_concentration_penalty.

   def compose_event_score(...) -> Decimal:
       return sum(positive_scorers) - sum(penalties)
   ```
   Sub-scorers are testable in isolation. The composite is capped at `[0, 100]` for the `event_signal.score` field.
5. **Implement `Activist13DCandidateService`:**
   ```python
   class Activist13DCandidateService:
       slug: StrategySource = "activist_13d_followthrough"
       async def get_top_five(self, *, limit: int = 5) -> CandidateBatch:
           tier1 = await self.client.fetch_recent_filings(form_type="SC 13D", lookback_days=5)
           parsed = [f for f in (parse_filing(h, ...) for h in tier1) if f is not None]
           if len(parsed) < limit:
               tier2 = await self.client.fetch_recent_filings(form_type="SC 13D/A", lookback_days=10)
               parsed.extend([f for f in (...) if f is not None and f.is_substantive])
           if len(parsed) < limit:
               # Tier 3 — last 20 days, drop names whose price has exhausted the move
               ...
           enriched = await asyncio.gather(*[self._enrich(f) for f in parsed])
           # universe filters: price >= $15, ADV >= 750k, market cap >= $500M, options liquid
           filtered = [r for r in enriched if self._passes_universe(r)]
           ranked = sorted(filtered, key=lambda r: r.event_score, reverse=True)[:limit]
           return self._build_batch(ranked, raw_count=len(parsed))
   ```
6. **Populate `event_signal`** for each row using `compose_event_score()` normalised to `[0, 100]`. Set `is_supportive=True` (long-only v1). Detail string: `f"Fresh SC 13D from {filer_name}, {stake_percent:.1f}% stake, active intent"`.
7. **Persist audit data.** Pack the accession number and primary doc URL into `CandidateRecord.validation_notes` (existing tuple field):
   ```python
   validation_notes = (
       *existing_notes,
       f"SC_13D_ACCESSION={filing.accession}",
       f"SC_13D_URL={filing.primary_doc_url}",
   )
   ```
   No schema change in v1.
8. **Wire into `MultiStrategyCandidateService`** — replace the `_EmptyArm("activist_13d_followthrough")` stub.
9. **Add `_ACTIVIST_13D_DEFINITION`** to `strategy_catalog.py`. `query_urls` is the EDGAR search URL pattern.
10. **Add config keys** `ACTIVIST_13D_*` and `ACTIVIST_13D_USER_AGENT` (per §7.8).

**Tests (Phase 4):**
- `tests/test_sec_filings_client.py::test_user_agent_required_and_throttled`
- `tests/test_sec_filings_client.py::test_recovers_from_429_with_backoff`
- `tests/test_sec_filings_client.py::test_caches_filing_by_accession`
- `tests/test_activist_13d_parser.py::test_parses_initial_sc_13d_with_active_item4`
- `tests/test_activist_13d_parser.py::test_parses_sc_13d_a_amendment_with_stake_change`
- `tests/test_activist_13d_parser.py::test_excludes_sc_13g_passive_filings`
- `tests/test_activist_13d_parser.py::test_excludes_filings_with_no_active_intent_language`
- `tests/test_activist_13d_parser.py::test_unparseable_stake_returns_none_and_drops_filing`
- `tests/test_sec_scoring.py::test_event_score_ranks_fresh_active_above_stale_passive`
- `tests/test_sec_scoring.py::test_tech_concentration_penalty_pushes_tech_below_non_tech_ties`
- `tests/test_sec_scoring.py::test_earnings_collision_penalty_kicks_in_within_5_days`
- `tests/test_sec_scoring.py::test_each_sub_scorer_caps_at_documented_maximum`
- `tests/test_activist_13d_service.py::test_tier_progression_until_5_candidates`
- `tests/test_activist_13d_service.py::test_returns_partial_batch_when_universe_smaller_than_5`
- `tests/test_activist_13d_service.py::test_excludes_illiquid_options`
- `tests/test_activist_13d_service.py::test_persists_accession_and_filing_url_in_validation_notes`
- `tests/test_activist_13d_service.py::test_event_signal_populated_from_event_score`
- Integration: `tests/test_pipeline_orchestrator.py::test_activist_13d_arm_contributes_to_finalists`

**Exit criteria:**
- 17 Phase-4 tests pass.
- Manual dogfood: when at least one fresh active 13D exists in the past 5 days, E contributes ≥ 1 candidate. The Telegram run-summary card shows the EDGAR accession in the candidate detail.
- SEC rate-limit headers (`X-RateLimit-*` if present) show our usage well under the 10 rps cap.

**Gotchas:**
- SEC EDGAR requires a **valid User-Agent with a contact email** (e.g. `"EarningEdge research@earningedge.local"`). Requests without it return `403` after a few. Enforce in the client constructor.
- The CIK → ticker mapping is **stale until refreshed**. Cache for 24h, but fail closed (drop the filing) if a CIK can't be resolved.
- Some issuers file SC 13D under multiple CIKs or change tickers mid-campaign. Cross-check the ticker against `Finviz` row data when enriching — if the ticker isn't optionable / liquid, drop.
- The active-intent classifier is the **biggest false-positive risk**. Start conservative (only fire on phrases we are sure are active) and tune up over time once we have real-world false-negative rates. Better to ship 2 candidates than 5 wrong candidates.
- 13D filings can arrive **stale**: the filer might have established the position weeks before disclosure. The `gap_exhaustion_penalty` is the guard — apply it strictly.
- Reuse the `SecEdgarNewsSource` user-agent and throttle helpers — refactor into a shared `app/services/sec/http.py` only if the duplication is non-trivial; do **not** speculatively refactor (CLAUDE.md rule).

### Phase 5 — End-to-end and dogfooding (1 small PR)

**Goal.** Prove the 5-strategy pipeline works end-to-end against real services, that fairness holds in practice, and that the "Run scan now" UX (Telegram today, dashboard when wired) renders the new strategies cleanly.

**Preconditions.** Phases 0–4 merged.

**Step-by-step:**

1. **Build a 25-candidate happy-path fixture.** Synthesise one strong candidate per strategy with realistic `MarketSnapshot`, `event_signal`, and `option_chain`. Place under `tests/fixtures/balanced_25_pool.py` for reuse.
2. **Write the 5-strategy integration test** in `tests/test_pipeline_orchestrator.py`:
   - Mock the 5 candidate services to return the fixture's 5 batches.
   - Drive the orchestrator with `evaluate_batch()` against an in-memory user.
   - Assert `len(outcome.candidates) == 25`, `len(decision_finalists) == 4`, `outcome.decision.action in {"recommend", "watchlist", "no_trade"}`.
3. **Add the diversity assertion** (`test_finalists_include_at_least_three_distinct_strategies_on_balanced_day`):
   ```python
   strategies_in_finalists = {c.context.strategy_source for c in decision_finalists}
   assert len(strategies_in_finalists) >= 3
   ```
4. **Persistence smoke test.** Run the full orchestrator against a real test DB session; verify a `WorkflowRun` row is created with `strategy_reports` JSON containing 5 entries; verify each `Candidate` row has the correct `strategy_source`.
5. **Position monitor integration.** Insert a synthetic open position with `strategy_source="pead_continuation"`, `"sector_relative_strength"`, and `"activist_13d_followthrough"`. Confirm `app/services/positions/monitor.py` reads each one and emits alerts without special-casing.
6. **Telegram renderer e2e.** Trigger a real scan via `WorkflowRunner.run_workflow(user.id, trigger_type="manual")` against staging-style fixtures. Verify the run-summary card shows 5 rows.
7. **Manual dogfood.** Run `./dev.sh`, press the "Run scan now" button in the Telegram bot, observe:
   - Run-summary card shows all 5 strategy rows with their statuses.
   - A C/D/E recommendation (if surfaced) can be filled and tracked end-to-end.
   - The position monitor (every 2 min during US market hours) emits the right alerts.
8. **Dashboard forward-compat.** Confirm `app/api/` is still empty and that no part of the dashboard codebase calls `MultiStrategyCandidateService` directly. When the dashboard run-scan endpoint lands later, it must route through `WorkflowRunner.run_workflow()` to inherit the locks and the orchestrator unchanged. **No code change in this phase** — just a smoke check.
9. **Run the full pre-commit suite** and the entire test suite. Anything that broke since Phase 0 must be fixed before merging.

**Tests (Phase 5):**
- `tests/test_pipeline_orchestrator.py::test_all_five_strategies_concurrent_happy_path_25_pool`
- `tests/test_pipeline_orchestrator.py::test_three_succeed_two_empty_runs_to_completion`
- `tests/test_pipeline_orchestrator.py::test_top_4_finalists_selected_from_25_candidate_pool`
- `tests/test_pipeline_orchestrator.py::test_llm_only_sees_top_4_after_dedupe`
- `tests/test_pipeline_orchestrator.py::test_finalists_include_at_least_three_distinct_strategies_on_balanced_day`
- `tests/test_pipeline_orchestrator.py::test_pipeline_completes_within_run_lock_ttl` — measures the e2e wall-clock against `WORKFLOW_RUN_LOCK_TTL_SECONDS`.
- `tests/test_logging_service.py::test_strategy_reports_persists_all_five_rows`
- `tests/test_pipeline_determinism.py::test_five_strategy_run_is_deterministic_under_frozen_inputs`
- `tests/test_position_monitor.py::test_alerts_for_pead_sector_rs_and_activist_13d_positions` — verifies strategy-agnostic monitor.
- `tests/test_telegram_run_summary.py::test_renders_five_strategy_rows` — Telegram template snapshot test.

**Exit criteria:**
- 10 Phase-5 tests pass.
- All ≈57 cumulative tests pass.
- Manual dogfood produces a 5-row run-summary card and one persisted `Recommendation` (or `no_trade`) end-to-end.
- `WorkflowRun.strategy_reports` JSON reflects all 5 arms in production.

**Gotchas:**
- The orchestrator already supports up to 25 candidates concurrently (`asyncio.gather` over `_analyze_candidate`) — no per-candidate runtime ceiling needs to be raised, but **measure** the wall-clock on the dogfood run and bump `WORKFLOW_RUN_LOCK_TTL_SECONDS` if you cross 600s.
- Don't add a dashboard run-scan endpoint in Phase 5. That's a separate workstream and deserves its own design (auth, CSRF, multi-user concurrency vs the Redis lock). The plan only guarantees forward-compatibility.
- The Telegram template change is small but **must use `enforce_tone()`** if it adds any new free-text strings (CLAUDE.md tone-gate rule).
- If the determinism test fails, the most likely cause is a non-deterministic ordering inside `_merge_dedupe()` after the 5-arm change — assert sort key includes `strategy_source` as a tiebreaker.

## 9. Test plan summary

| Scope | New tests | What they prove |
|---|---:|---|
| Phase 0 — schema/types | 5 | Migration safe; exemption set covers new strategies; Literal widened in both modules; `screener_status="empty"` enum; `event_signal` default None |
| Phase 1 — merge plumbing | 6 | Tie-precedence works; partial / empty / failed degrade gracefully; legacy warning strings byte-identical; arm interface normalised |
| Phase 1.5 — scoring fairness | 11 | Equal score ceiling per strategy; balanced-pool monopoly check; per-strategy event-signal monotonicity; `inconsistent_history` only fires for A; legacy A/B regressions stay within ±3; `SCORING_FAIRNESS_V2=False` is byte-identical to today's main |
| Phase 2 — PEAD | 13 | Surprise filter, sector exclusions, market-cap band, T+1, fallback chain, ranking, partial/empty, event_signal, cross-arm dedupe, integration |
| Phase 3 — Sector RS | 11 | ETF ranking, regime gate, second-sector fallback, dynamic URL, yfinance failure, event_signal, run-report query_urls, integration |
| Phase 4 — Activist 13D | 17 | EDGAR client behaviour incl. caching, parser correctness, sub-scorer caps, tier progression, persistence, event_signal, integration |
| Phase 5 — e2e | 10 | 25-candidate pool, top-4 finalist gate, LLM payload bounded, ≥ 3 distinct strategies in finalists, run-lock TTL respected, determinism, logging, position monitor strategy-agnostic, Telegram render |
| **Total** | **≈ 73** | |

All tests use pytest async-mode auto and the existing `tests/conftest.py` skip-if-no-postgres pattern for DB-dependent suites.

## 10. Risks and mitigation

| Risk | Severity | Mitigation |
|---|---|---|
| Finviz filter drift (`earningsdate_prevweek`, `sec_consumerdefensive`) | Medium | Existing retry-once + clean-context + backup-source pattern in `app/services/finviz/` already handles 0-row responses |
| PEAD continued decay | Medium | The post-filter (≥5% surprise, ≥3% reaction, non-tech, $300M–$10B) is the published "edge survives" subset; further decay → empty batches, not noise |
| Sector RS momentum crash (2020-style) | High in tail regimes | Regime gate (top ETF above SMA-50 AND dispersion ≥ +2%) fails closed; position monitor surfaces a `regime_warning` flag |
| EDGAR rate limits / 429s | Low | Async client respects SEC fair-access rules; user-agent enforced; cache by accession; backoff on 429 |
| 13D parser misses Item 4 active intent | Medium | Conservative active-intent classifier; bias toward false negatives (drop ambiguous filings) over false positives |
| Pipeline runtime grows with 5 arms | Medium | Per-arm `asyncio.gather` is unchanged in shape; existing Redis run-lock TTL (`WORKFLOW_RUN_LOCK_TTL_SECONDS`, default 900s) has headroom; if measured runs cross 600s, raise the TTL or split into two phases |
| Alpha Vantage free-tier exhaustion (PEAD tertiary fallback) | Low | yfinance is primary; Alpha Vantage only fires on dual failure of yfinance + Finnhub |
| Tie-precedence reshuffles credit attribution | Cosmetic only | Underlying decision is identical; attribution goes to whichever arm sees the ticker first by precedence |
| Dashboard trigger not yet wired | Out of scope | When added, must route through `WorkflowRunner.run_workflow()` to inherit the lock and the orchestrator unchanged |
| **Scoring rebalance regresses A/B candidate quality** | High | Phase 1.5 ships behind `SCORING_FAIRNESS_V2` flag; legacy regression tests gate the merge (A and B scores must stay within ±3 points on the existing fixtures); flag is only removed after one month of clean weekly runs |
| **Calibrated weights still favour one strategy in practice** | Medium | The §6.4 balanced-pool test requires ≥ 3 distinct strategies in the top 4 on a balanced fixture; if it fails, retune weights inside the test fixture before any phase merges |
| Strategy services forget to populate `event_signal` | Medium | `event_signal=None` falls back to a neutral 0 — the candidate is not vetoed but loses the event-weighted points; Phase 2/3/4 acceptance criteria explicitly include populating `event_signal` |

## 11. Out of scope for this v1

- Multi-leg contracts (debit spreads, calendars, condors).
- Bearish PEAD variant (negative surprise → long puts).
- Form 4 insider cluster strategy (deferred per consensus).
- Macro-calendar gating (FOMC / CPI / NFP weeks).
- Structured event metadata column on `candidates` (using `validation_notes` for v1).
- Dashboard run-scan endpoint (not yet implemented; this plan is forward-compatible when it lands).

## 12. Definition of done

- All ≈73 tests in §9 pass under `uv run pytest -q` — including the 11-test fairness suite from §6.4.
- `uv run mypy app` strict, `uv run ruff check .`, `uv run ruff format .`, `uv run black .` all clean.
- `alembic upgrade head` completes from a fresh DB and `alembic downgrade -1` then `upgrade head` is idempotent.
- Manual run-scan-now from the Telegram menu (`Run scan now` button) renders a 5-row strategy status table on the run-summary card and produces either one recommendation or a no-trade verdict.
- `WorkflowRun.strategy_reports` persists 5 rows for the dogfood run.
- A position opened by Strategy C, D, or E flows through `app/services/positions/monitor.py` with no special-casing required.
- No regression in the existing Strategy A backup-source warning string (`FINVIZ_FALLBACK_WARNING`) or Strategy B empty-on-Finviz-error behaviour.
- **Fairness gate:** the §6.4 balanced-pool test passes — given a 25-candidate fixture with one strong candidate per strategy, the top-4 finalists include candidates from at least 3 distinct strategies. No single strategy can monopolise the LLM finalist set on a balanced day.
- **Legacy regression gate:** A and B candidate `final_score` values from the pre-rebalance fixture remain within ±3 points after Phase 1.5 lands.
- `SCORING_FAIRNESS_V2` flag is `True` in production for at least one full weekly cycle without rollback before the flag is removed.

---

## 13. Final reverification — internal consistency checklist

This section is a self-audit. Each item is a claim the plan makes, with the cross-reference and the sanity check used to verify it.

| # | Claim | Cross-ref | Verified by |
|---|---|---|---|
| 1 | Three winners are PEAD, Sector RS, Activist 13D | §1, §4 | `strategy3_combined.md §Winners` lists exactly these three with scores 26.7 / 24.1 / 23.8 |
| 2 | Latest Alembic head is `0012_position_validation` | §5.1 | `ls alembic/versions/` confirmed `0012_position_validation.py` is the most recent |
| 3 | All three new strategy slugs fit in `String(32)` | §5.1 | Hand-counted: 16 / 24 / 26 chars |
| 4 | `StrategySource` is duplicated in two files | §6.0 #3 | `grep -rn "StrategySource = Literal" app/` returns `candidate_models.py:9` and `scoring/types.py:21` |
| 5 | `previous_earnings_move_percent` is never set in production | §6.0 #1 | `grep -rn "previous_earnings_move_percent" app/` shows only **reads** (penalties, contract, direction, decide); `orchestrator.py:313-330` does not set it |
| 6 | `coiled_setup`-only earnings exemption lives in 3 sites | §5.4, §6.3.3 | `grep -rn "strategy_source.*coiled_setup\|coiled_setup.*strategy_source" app/` returns vetoes.py:24, confidence.py:100, alternative_recommendation_service.py:402 |
| 7 | `_DIRECTION_WEIGHTS` total is 85 today | §6.3.1 | `direction.py:35-43`: 20+15+10+15+10+10+5 = 85 ✓ |
| 8 | All five V2 weight rows total 85 | §6.3.1 | A: 20+15+10+15+0+10+10+5=85; B: 20+18+10+0+7+10+15+5=85; C: 18+15+12+8+7+10+10+5=85; D: 15+18+10+0+15+12+10+5=85; E: 15+15+12+0+15+10+13+5=85 ✓ |
| 9 | Confidence weights total 0.97 today | §6.3.2 | `confidence.py:23-28`: 0.13+0.25+0.20+0.22+0.10+0.07 = 0.97 ✓ |
| 10 | All five V2 confidence rows total 0.97 | §6.3.2 | A: 0.13+0.25+0.00+0.20+0.22+0.10+0.07=0.97; B: 0.13+0.00+0.20+0.25+0.22+0.10+0.07=0.97; C: 0.13+0.20+0.05+0.22+0.22+0.10+0.05=0.97; D: 0.13+0.00+0.20+0.25+0.22+0.10+0.07=0.97; E: 0.13+0.00+0.20+0.22+0.22+0.10+0.10=0.97 ✓ |
| 11 | A's V2 weight row matches legacy weights | §6.3.1 | A row of `_V2_WEIGHTS_BY_STRATEGY` is identical to `_LEGACY_WEIGHTS` (event-signal weight 0). Therefore the legacy A regression test is satisfied by construction. |
| 12 | A's V2 confidence row matches legacy | §6.3.2 | A row equals `_LEGACY_CONFIDENCE`. Same conclusion. |
| 13 | Golden direction-score table at `test_scoring_engine.py:46-62` won't break | §6.3.1, Phase 1.5 gotchas | The fixture uses `strategy_source` defaulted to `"catalyst_confluence"`, A's V2 row equals legacy, so 84/76/49 hold. |
| 14 | `_select_decision_finalists()` is already strategy-neutral | §6.5 | `orchestrator.py:836-849` sorts by `(final_score, confidence.score, direction.score)` — no strategy_source field involved. |
| 15 | The `combine_scores()` blend (0.45 / 0.55) is unchanged | §2, §6.2 | `final.py:22-26` is not on the modification list. |
| 16 | `event_signal` is plumbed CandidateRecord → CandidateContext | §6.3.1, Phase 0 step 7 | Phase 0 adds the field to both, plus the orchestrator passes it through. |
| 17 | `event_signal=None` is a safe default for A | §6.3.1 | A's `_V2_WEIGHTS_BY_STRATEGY["catalyst_confluence"]["event signal"] == 0` so `_event_signal` returns 0×0 = 0 contribution. |
| 18 | LLM `CandidateBundle` adds `strategy_source` and `event_signal_detail` without breaking existing payloads | §6.5, Phase 0 step 9 | Both fields default to safe values; existing fixtures pass without re-declaring. `validate_llm_decision()` is unchanged. |
| 19 | Position monitor is strategy-agnostic | §11, Phase 5 step 5 | `grep -rn "strategy_source" app/services/positions/` returns no matches today; the monitor reads from `open_positions` schema-agnostically. |
| 20 | Run-scan-now triggers via `WorkflowRunner.run_workflow()` from Telegram | §1, §7.10 | `app/telegram/handlers/menu.py:51-63` calls `get_workflow_runner().run_workflow(user.id, trigger_type="manual")`. |
| 21 | `app/api/` is empty (no dashboard endpoint yet) | §7.10 | `ls app/api/` shows only `__pycache__/`. |
| 22 | The 5-arm gather respects the existing run-lock TTL | §10, Phase 5 gotchas | `WORKFLOW_RUN_LOCK_TTL_SECONDS` defaults to 900s; per-candidate fan-out is unchanged in shape; concurrency budget is the same. |
| 23 | No new external paid sources are introduced | §2 | All four data sources (Finviz, yfinance, Finnhub, Alpha Vantage, EDGAR) are already in the stack. SEC EDGAR is the only "new" entry point but the user-agent / throttling pattern is reused from `news/sources.py`. |
| 24 | Tie-precedence A > C > B > D > E preserves catalyst priority | §7.4, §10 | Existing code already prefers catalyst over coiled. New precedence places C between B's predecessor (A) and B itself — the user-flagged open question is documented for confirmation in §7.4. |
| 25 | `SCORING_FAIRNESS_V2=False` is a complete rollback path | §6.6, Phase 1.5 step 1, Exit criteria | Each weight site reads the flag and falls back to `_LEGACY_*`. `test_v2_off_restores_byte_identical_legacy_scores` enforces this. |
| 26 | All migrations idempotent | §5.1, Phase 0 exit criteria | `0013` is no-op DDL; upgrade/downgrade roundtrip tested in `test_migrations.py::test_0013_upgrade_downgrade_idempotent`. |
| 27 | No CLAUDE.md conventions violated | All phases | All async (no `requests`, no sync DB sessions); Decimal for money; frozen dataclasses; fallbacks beat aborts; `get_settings()` for config; ruff/black/mypy strict enforced in every phase exit criterion. |

If any row in this table fails verification at implementation time, **stop and update the plan** before continuing. The scoring system is the one place where a silent regression can cascade across the whole pipeline.
