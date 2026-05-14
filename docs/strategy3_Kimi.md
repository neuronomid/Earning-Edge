# Strategy 5 Expansion Report
## Adding 3 New Strategies to the Earning-Edge Pipeline

**Author:** Kimi K2.6 (Lead Architect)  
**Date:** 2026-05-13  
**Status:** Research & Design Complete — Implementation Ready  

---

## 1. Executive Summary

The Earning-Edge pipeline currently operates with **2 strategies**:

1. **catalyst_confluence** (Strategy A) — Pre-earnings catalyst setups via Finviz screener
2. **coiled_setup** (Strategy B) — Trend/structure breakouts via Finviz screener

Each strategy produces **5 candidates**. These candidates are merged, deduplicated, scored deterministically, and the top **4 finalists** are sent to a heavy LLM (Claude Opus 4.7) for qualitative analysis before a final recommendation is generated.

**Goal:** Add **3 new strategies** to reach a total of **5 strategies**, producing **25 candidates** (5 strategies x 5 candidates) that feed into the existing scoring and LLM pipeline.

**The 3 Selected New Strategies:**

| # | Strategy Name | Core Edge | Sector Focus |
|---|--------------|-----------|--------------|
| 3 | **sector_momentum_ignition** | Dual sector + individual momentum in non-tech | Energy, Materials, Industrials, Financials, Real Estate, Healthcare, Staples, Utilities |
| 4 | **spring_loaded_reversion** | Oversold bounce after volatility contraction in uptrends | Same non-tech universe |
| 5 | **commodity_momentum_beta** | Commodity-linked equity momentum via operating leverage | Energy, Materials, Mining, Chemicals, Agriculture |

All three strategies:
- Focus on **non-technology stocks** (satisfying the "at least 2" requirement with all 3)
- Are designed for **short-term option contracts** (<4 weeks holding period)
- Use **only existing free data sources** (Finviz, yfinance, Finnhub, Alpaca)
- Can produce exactly **5 candidates per run**
- Are grounded in **peer-reviewed academic research**
- Fit the existing pipeline architecture with minimal structural changes

**Final Pipeline Flow:**
```
5 strategies x 5 candidates = 25 candidates
        |
        v
  Scoring System (deterministic)
        |
        v
   Top 4 finalists
        |
        v
   LLM Analysis (qualitative)
        |
        v
  Final Recommendation
```

---

## 2. Current System Summary

### 2.1 Existing Strategies

**Strategy 1: catalyst_confluence** (`app/services/candidate_service.py`)
- **Source:** Finviz screener + backup earnings data (YFinance, Finnhub)
- **URL:** `https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap`
- **Logic:** USA-listed companies reporting earnings next week, sorted by market cap descending
- **Validation:** Earnings date verified against YFinance/Finnhub backup sources
- **Fallback:** If Finviz fails, uses backup earnings sources with warning: `⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.`
- **Output:** `CandidateBatch` with up to 5 `CandidateRecord` objects

**Strategy 2: coiled_setup** (`app/services/coiled_setup_service.py`)
- **Source:** Finviz screener only
- **URL:** `https://finviz.com/screener?v=111&f=cap_midover,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,ta_sma50_pa,ta_sma200_pa,ta_highlow52w_b20h,ta_beta_o1,ta_rsi_40to70&o=-relativevolume`
- **Logic:** Optionable mid+ cap stocks above $20, above 50/200 SMAs, within 20% of 52-week high, beta >1, RSI 40-70, sorted by relative volume
- **Fallback:** If Finviz fails, degrades to empty tuple with logged warning
- **Output:** Tuple of up to 5 `CandidateRecord` objects

### 2.2 Current Candidate Pipeline

The pipeline is orchestrated by `PipelineOrchestrator` (`app/pipeline/orchestrator.py`):

1. **Candidate Selection** (`app/pipeline/steps/candidates.py`)
   - Calls `MultiStrategyCandidateService.get_candidates()`
   - Merges and deduplicates candidates from both strategies
   - Returns `CandidateBatch`

2. **Market Data Fetch** (`app/pipeline/steps/market_data.py`)
   - Fetches `MarketSnapshot` for each candidate
   - Sources: Alpha Vantage (primary), yfinance (fallback)

3. **News Brief** (`app/pipeline/steps/news.py`)
   - Fetches news via search + LLM summarization (Gemini 3.1 Pro)
   - Deferred for non-finalists, refreshed for finalists

4. **Options Chain Fetch** (`app/pipeline/steps/options.py`)
   - Fetches option chains via Alpaca (primary) or yfinance (fallback)
   - Source: `OptionsService` (`app/services/options/service.py`)

5. **Scoring** (`app/pipeline/steps/scoring.py`)
   - `score_candidate()` computes direction score + contract score
   - Direction: trend alignment, relative strength, volume, earnings expectation, market/sector, price structure
   - Contract: breakeven feasibility, liquidity, expiry fit, strike/moneyness, IV setup, premium/risk, direction compatibility
   - Combine: 45% direction + 55% contract

6. **Top-4 Selection** (`app/pipeline/orchestrator.py`, `DECISION_FINALIST_LIMIT = 4`)
   - Preliminary candidates scored with deferred news
   - Top 4 selected by `(final_score, confidence_score, direction_score)`
   - Finalists refreshed with live news

7. **LLM Decision** (`app/pipeline/steps/decide.py`)
   - Heavy model (Claude Opus 4.7) receives structured `DecisionInput`
   - Validates against candidates, normalizes bands, enforces consistency
   - Falls back to heuristic if LLM fails

8. **Sizing** (`app/pipeline/steps/sizing.py`)
   - Computes position size based on account, risk profile, contract premium

9. **Recommendation** (`app/pipeline/orchestrator.py`)
   - Persists to database, sends Telegram notification

### 2.3 Current Scoring System

**Direction Scoring** (`app/scoring/direction.py`):
- Weights: trend alignment (20), relative strength (15), volume confirmation (10), earnings expectation (15), market/sector (10), price structure (10), data confidence (5)
- Classification thresholds: bullish (bias >= 0.12), bearish (bias <= -0.12), neutral, avoid

**Contract Scoring** (`app/scoring/contract.py`):
- Factors: breakeven feasibility (20), option liquidity (15), expiry fit (15), strike/moneyness (15), IV setup (15), premium/risk (10), direction compatibility (10)
- Hard vetoes (`app/scoring/vetoes.py`): missing earnings date, missing price, missing option chain, invalid expiry, wide spread, stale contract, zero contracts, permission mismatch
- Soft penalties (`app/scoring/penalties.py`): weak sector trend, light volume, wide spread, elevated IV for longs, thin IV for shorts, expiry less ideal, inconsistent history

**Data Confidence** (`app/scoring/confidence.py`):
- Components: identity (15), earnings (20), market (15), options (20), cross-source (10), calculation (10)
- Blockers: missing critical data, invalid contract, low confidence score

**Final Action** (`app/scoring/final.py`):
- `final_score = 0.45 * direction_score + 0.55 * contract_score`
- Thresholds: recommend (>=68 with confidence >=55), watchlist (>=60 or confidence 40-55), no_trade (otherwise)

### 2.4 Current Data Sources

| Source | Used For | Access | Reliability |
|--------|----------|--------|-------------|
| **Finviz** | Stock screening (Playwright) | Free, no login | Medium — requires retry logic |
| **yfinance** | Earnings calendar, market data, options chain fallback | Free API | Medium — rate limits, occasional stale data |
| **Finnhub** | Earnings calendar backup, news | Free tier (API key) | Good — 60 calls/minute |
| **Alpaca** | Options chains (primary) | Free tier (API key) | Good — 200 req/minute |
| **Alpha Vantage** | Market data, technical indicators | Free tier (API key) | Low — 25 calls/day |
| **OpenRouter** | LLM decision (Claude Opus 4.7), news summarization (Gemini 3.1) | API key | Good — retry with tenacity |
| **SEC EDGAR** | Regulatory filings | Free, no login | Good — stable but slow |

### 2.5 Current LLM Analysis Flow

- **Input:** Top 4 `PipelineCandidate` objects with full context (market data, news, option chains, scoring)
- **Schema:** `DecisionInput` → `CandidateBundle` per candidate → `OptionChainCandidate` for viable contracts
- **Model:** Claude Opus 4.7 via OpenRouter (`market_analysis_model`)
- **Output:** `StructuredDecision` with action, chosen ticker/contract, direction tier, confidence band, rationale, evidence, concerns, watchlist
- **Validation:** Band/action consistency, ticker existence, contract existence, score normalization
- **Fallback:** Heuristic decision if LLM fails

### 2.6 Current Limitations

1. **Only 2 strategies:** Limited candidate diversity; both rely on Finviz primary screening
2. **No sector rotation:** Cannot capitalize on sector momentum or mean reversion
3. **No non-tech focus:** Tech stocks often dominate screens, creating concentration risk
4. **No commodity exposure:** Missing energy/materials macro themes
5. **Scoring is direction-agnostic on sector:** Sector momentum/mean reversion not explicitly rewarded
6. **All long-premium:** Current strategies are primarily long options; no short premium harvesting

---

## 3. Research Method

### 3.1 Agent Setup

**10 research agents** were spawned, each operating as an independent quantitative analyst with the mandate to research and propose 1-2 short-term options strategies for non-technology sectors.

Each agent received:
- Full context on the existing 2 strategies and data sources
- A specific research angle (momentum, mean reversion, event-driven, short premium, sector rotation, breakout, dividend/calendar, short squeeze, defensive, commodity-linked)
- Strict constraints: free data only, no login/CAPTCHA, <4 week holds, exactly 5 candidates, automatable

### 3.2 Sources Reviewed

Agents were instructed to search the internet and review:
- Academic papers (Journal of Finance, Review of Financial Studies, Journal of Financial Economics)
- Quantitative trading research (AQR, Cboe, OptionMetrics)
- Options trading research (tastylive, CBOE Options Institute)
- Volatility research (VIX, IV/HV dynamics)
- Market microstructure (gamma, squeeze mechanics)
- Practitioner guides (ClinicalInvestor, Biocatalysts)

### 3.3 Evaluation Criteria

Strategies were judged on:
1. **Research quality** — Is the strategy grounded in peer-reviewed or reputable practitioner research?
2. **Data fit** — Can the strategy use existing data sources without new fragile scrapers?
3. **Pipeline fit** — Does it slot into the existing `CandidateBatch` → scoring → LLM flow?
4. **Diversification** — Does it add a new signal type (momentum, mean reversion, macro) or just duplicate existing logic?
5. **Practicality** — Can it produce exactly 5 candidates reliably? Is the holding period <4 weeks?
6. **Risk profile** — Is tail risk manageable? Is assignment risk avoided or well-defined?
7. **Automation complexity** — Can it be implemented in <1 week of engineering?

### 3.4 Consensus Process

After all agents returned, a scholastic consensus was conducted:
- **Grouped** similar strategies (momentum/breakout, mean reversion, short premium, event-driven, squeeze/gamma)
- **Identified agreement** — Sector momentum and mean reversion had the broadest support across multiple agents
- **Challenged assumptions** — FDA calendar scraping is fragile; gamma trap requires unreliable OI data; short interest is bi-monthly and stale
- **Rejected outliers** — Strategies requiring new fragile data sources, complex options chain parsing, or high assignment risk
- **Preserved** the 3 strategies with strongest research + best system fit + highest diversification

---

## 4. Strategies Proposed by Agents

### 4.1 Agent 1 — Momentum & Trend Continuation

**Proposed:**
- **Sector Momentum Ignition (SMI):** Dual sector + individual momentum in non-tech. Rank sector ETFs by 1-month return, screen top stocks with accelerating RSI and volume. Long calls 14-21 DTE.
- **Cyclical Breakout Continuation (CBC):** Breakout patterns in cyclicals (energy, materials, industrials, financials). Finviz screen for stocks near 52-week highs with volume confirmation. Long calls 10-21 DTE.

**Verdict:** SMI **ACCEPTED** (strongest research support, most distinct from existing strategies). CBC **MERGED** into SMI as a secondary filter (SMI already captures breakout candidates via momentum acceleration).

### 4.2 Agent 2 — Mean Reversion & Volatility Contraction

**Proposed:**
- **Spring-Loaded Reversion:** Oversold stocks (RSI <35, above SMA200) with Bollinger Band width contraction, declining ATR, and shrinking volume. Long calls 14-21 DTE.
- **IV Compression Bounce:** Same oversold screen plus IV/HV < 0.90 filter. Long calls 21-28 DTE.

**Verdict:** Spring-Loaded Reversion **ACCEPTED** (strong research, practical, distinct signal). IV Compression Bounce **REJECTED** — too similar to Spring-Loaded; the IV/HV filter requires options chain data that is often stale for mid-cap names, and the edge is marginal vs. the price-mean-reversion edge alone.

### 4.3 Agent 3 — Event-Driven Beyond Earnings

**Proposed:**
- **Regulatory Run-Up:** Pre-FDA PDUFA run-up in biotech/pharma. Exit 1-3 days before decision. Long calls.
- **Commodity Macro Inflection:** OPEC/EIA events in energy/materials. Position 2-4 days before macro events. Long calls/puts.

**Verdict:** Regulatory Run-Up **REJECTED** — requires scraping FDA calendars (new fragile data source), evaluating drug approval probabilities (domain expertise), and biotech is inherently binary/high-risk. Commodity Macro Inflection **REJECTED** — OPEC calendar is irregular and hard to automate; EIA weekly reports create too much noise. The core idea (commodity momentum) is preserved in Strategy 5.

### 4.4 Agent 4 — Short Premium / Short Volatility

**Proposed:**
- **Cyclical Compression:** Short strangles on non-tech cyclicals with IV/HV > 1.20. 14-28 DTE.
- **Defensive Yield Capture:** Cash-secured short puts on defensive names with IV/HV > 1.15. 14-28 DTE.

**Verdict:** Both **REJECTED** — While academically sound (VRP harvesting), short premium strategies introduce assignment risk, tail risk, and different capital requirements. The current pipeline is optimized for directional long-option trades. Adding short premium would require significant scoring, sizing, and exit-target changes. Recommended for Phase 2 after the 3 long strategies are stable.

### 4.5 Agent 5 — Sector Rotation & Macro

**Proposed:**
- **Macro Momentum Sector:** Top 1-2 performing non-tech sectors, buy leaders. Long calls.
- **Rate-Sensitive Rotation:** Financials (rising rates) / Utilities & REITs (falling rates). Long calls.

**Verdict:** Macro Momentum Sector **MERGED** into SMI (same core idea). Rate-Sensitive Rotation **REJECTED** — Treasury yield regime detection is too slow and macro for <4 week options; adds complexity without clear edge.

### 4.6 Agent 6 — Breakout & Range Expansion

**Proposed:**
- **Compression Burst:** Volatility squeeze releases in trending non-tech stocks (ascending triangles, low ATR percentile). Long calls.
- **Sector Expansion:** 52-week high breakouts validated by sector momentum. Long calls.

**Verdict:** Compression Burst **REJECTED** — Finviz pattern detection (`ta_p_wedgeresistance`) is heuristic and unreliable; ATR percentile requires 6 months of history per candidate, heavy for the pipeline. Sector Expansion **MERGED** into SMI (SMI's sector filter already validates breakouts).

### 4.7 Agent 7 — Dividend & Calendar

**Proposed:**
- **Ex-Dividend Call Write:** Dividend capture with covered calls. 2-7 day hold.
- **Pre-Earnings Calendar Spread:** Sell front-month / buy back-month ATM calls before earnings in defensive sectors. 7-21 day hold.

**Verdict:** Both **REJECTED** — Ex-dividend requires stock ownership (not supported by current options-only pipeline). Calendar spreads are complex to manage, have small edge, and earnings are already covered by catalyst_confluence.

### 4.8 Agent 8 — Short Squeeze & Gamma

**Proposed:**
- **Short Squeeze Sentinel:** High short-interest stocks in cyclical sectors. Long call spreads.
- **Gamma Trap Hunter:** Stocks near critical gamma-neutral levels. Long OTM calls.

**Verdict:** Short Squeeze Sentinel **REJECTED** — Short interest data is bi-monthly (official) or estimated (Finviz); too stale for reliable squeeze timing. Gamma Trap Hunter **REJECTED** — Requires parsing full options chains for OI by strike; yfinance OI data is unreliable and Alpaca free tier may not provide sufficient granularity.

### 4.9 Agent 9 — Defensive Strategies

**Proposed:** Empty response.

### 4.10 Agent 10 — Commodity-Linked

**Proposed:**
- **Commodity Momentum Beta:** Long calls on commodity-linked equities when commodity ETFs trend up. 14-21 DTE.
- **Commodity Divergence Snapback:** Long calls on commodity-linked equities that have diverged from rising commodities. 10-21 DTE.

**Verdict:** Commodity Momentum Beta **ACCEPTED** (strong research, distinct macro signal, practical with yfinance ETF data). Divergence Snapback **REJECTED** — Too similar to Spring-Loaded Reversion (both are mean-reversion), and divergence timing is harder to automate reliably.

---

## 5. Scholastic Consensus

### 5.1 Ideas with Strongest Agreement

**Sector Momentum Ignition** was proposed in some form by Agents 1, 5, 6, and 10. The academic support (Moskowitz & Grinblatt 1999, Jegadeesh & Titman 1993) is uncontroversial and robust. All agents agreed that non-tech sectors exhibit slower information diffusion, making momentum more persistent.

**Mean Reversion / Oversold Bounce** was proposed by Agents 2 and 10. The academic support (De Bondt & Thaler 1985, Bollinger 2002) is strong. Agents agreed that buying calls on oversold stocks in uptrends is a high-probability short-term setup.

### 5.2 Outlier Ideas

**Regulatory Run-Up** (Agent 3) was the most interesting outlier but required the most new infrastructure (FDA calendar scraping, drug probability estimation). The consensus deemed the data source too fragile for an automated pipeline.

**Gamma Trap Hunter** (Agent 8) was the most technically sophisticated but relied on options chain data granularity that free tiers cannot reliably provide.

### 5.3 Assumptions Challenged

- **"Short premium is essential for diversification"** — Challenged and overruled. While VRP harvesting is real, the pipeline is not yet ready for the assignment risk and tail risk of short premium. Defer to Phase 2.
- **"Event-driven strategies need new data sources"** — Challenged. The consensus preserved the *commodity macro* idea but stripped out the OPEC/FDA calendar scraping, replacing it with simple yfinance ETF momentum checks.
- **"More strategies = better"** — Challenged. The consensus prioritized **3 strong, distinct strategies** over 5 weak or overlapping ones.

### 5.4 Discarded Ideas

| Strategy | Reason for Discard |
|----------|-------------------|
| Regulatory Run-Up | Fragile FDA calendar scraping; biotech binary risk |
| Commodity Macro Inflection | OPEC calendar irregular; EIA too noisy |
| Cyclical Compression | Short premium tail risk; pipeline not ready |
| Defensive Yield Capture | Assignment risk; cash-secured put capital requirements |
| Rate-Sensitive Rotation | Treasury regime too slow for <4 week options |
| Compression Burst | Finviz pattern detection unreliable; heavy ATR computation |
| Ex-Dividend Call Write | Requires stock ownership; not supported |
| Pre-Earnings Calendar Spread | Earnings already covered; small edge |
| Short Squeeze Sentinel | Short interest data too stale |
| Gamma Trap Hunter | Options OI data unreliable in free tier |
| IV Compression Bounce | Too similar to Spring-Loaded; IV/HV data unreliable |
| Commodity Divergence Snapback | Too similar to Spring-Loaded; timing hard to automate |
| Cyclical Breakout Continuation | Merged into SMI |
| Macro Momentum Sector | Merged into SMI |
| Sector Expansion | Merged into SMI |

### 5.5 Preserved Ideas

| Strategy | Why Preserved |
|----------|--------------|
| **Sector Momentum Ignition** | Strongest research, broadest agent agreement, most distinct from existing strategies, practical with Finviz+yfinance |
| **Spring-Loaded Reversion** | Strong research, distinct mean-reversion signal (complements momentum), practical with Finviz+yfinance |
| **Commodity Momentum Beta** | Strong research, distinct macro signal, practical with yfinance ETF momentum + Finviz sector screen |

### 5.6 Why These 3 Were Selected

1. **Diversification:** They cover three distinct market regimes — momentum (trend following), mean reversion (oversold bounce), and macro momentum (commodity cycle).
2. **Research quality:** Each has multiple peer-reviewed papers supporting the core thesis.
3. **System fit:** Each uses only existing data sources (Finviz, yfinance) for candidate generation. No new fragile scrapers.
4. **Non-tech focus:** All three explicitly exclude technology, addressing the concentration risk in the current pipeline.
5. **Implementation feasibility:** Each can be implemented in a single service file with a Finviz screener + yfinance validation pattern, mirroring the existing `coiled_setup_service.py` architecture.
6. **Long-option alignment:** All three are long-call strategies, fitting the existing scoring, sizing, and exit-target infrastructure without major rework.

---

## 6. New Strategy 3: Sector Momentum Ignition

### 6.1 Strategy Name
**sector_momentum_ignition**

### 6.2 Core Thesis
Momentum operates at both the sector and individual stock level (Moskowitz & Grinblatt, 1999). By ranking non-technology sectors by recent performance and then selecting the top-performing stocks within the winning sectors, we capture a **dual momentum premium**. Non-tech sectors exhibit slower information diffusion (Hou & Moskowitz, 2005), making trends more persistent and predictable over 2-4 week horizons.

### 6.3 Stock Universe
- **Geography:** USA-listed (NYSE, NASDAQ)
- **Minimum Criteria:** Price > $15, Market Cap > $2B, Average Volume > 500K, Optionable
- **Sectors:** Energy (XLE), Materials (XLB), Industrials (XLI), Financials (XLF), Real Estate (XLRE), Healthcare (XLV), Utilities (XLU), Consumer Staples (XLP)
- **Excluded:** Technology (XLK), Communication Services (XLC)

### 6.4 Sector Focus
Explicitly **non-technology**. The strategy targets cyclical and defensive sectors that exhibit institutional rotation flows. Energy and materials are prioritized when commodity prices trend; financials and real estate when rate expectations shift; utilities and staples during risk-off rotations.

### 6.5 Why It Fits Short-Term Options
- Sector momentum persists for 1-3 months (Moskowitz & Grinblatt), making 2-4 week option holds ideal
- Call options provide leverage on the momentum premium without full capital commitment
- Higher volatility in cyclical sectors makes ATM/OTM calls more responsive to continuation
- Time decay is manageable with 14-21 DTE if the momentum signal is strong

### 6.6 Data Requirements

| Data Point | Source | Access Method |
|------------|--------|---------------|
| Sector ETF 1-month returns | yfinance | `yfinance.download([XLE, XLB, ...], period='1mo')` |
| Stock price history (20-50 days) | yfinance | `yfinance.download(ticker, period='3mo')` |
| Stock fundamentals/screening | Finviz | Playwright scrape custom URL |
| Options chain data | Alpaca or yfinance | `get_option_chain()` |

### 6.7 Candidate Selection Rules (Exactly 5)

**Step 1: Rank Non-Tech Sectors**
1. Download 21 trading days of closing prices for sector ETFs: XLE, XLB, XLI, XLF, XLRE, XLV, XLU, XLP
2. Calculate 1-month (21-day) total return and 2-week (10-day) return for each ETF
3. Rank sectors by composite score: `0.6 * 1mo_return + 0.4 * 2wk_return`
4. Select the **top 3 sectors**

**Step 2: Finviz Screen Within Winning Sectors**
```
https://finviz.com/screener?v=111
&f=geo_usa,sh_avgvol_o500,sh_price_o15,sh_opt_option
&o=-marketcap
```
- Filter by each top sector (`sec_energy`, `sec_basicmaterials`, etc.)
- Sort by market cap descending (liquidity priority)
- Fetch top 10 per sector

**Step 3: Momentum Acceleration Filter (yfinance)**
For each stock:
1. Price > SMA20 AND SMA20 > SMA50 (trend alignment)
2. RSI(14) between 50 and 70 (momentum present, not overbought)
3. RSI(14) today > RSI(14) 5 days ago (accelerating)
4. Volume(5-day avg) > Volume(20-day avg) * 1.1 (volume confirming)
5. Beta > 0.8 (sufficient sensitivity to sector)

**Step 4: Score and Rank**
```
Momentum Score = 0.30 * 1mo_return + 0.25 * 2wk_return + 0.20 * RSI_slope(5d) + 0.15 * volume_ratio + 0.10 * proximity_to_52w_high
```
- Select the **top 5 stocks** by Momentum Score
- If fewer than 5, relax to top 4 sectors
- If still fewer than 5, return all valid candidates + warning

### 6.8 Option Contract Selection Logic
- **Structure:** Long Call
- **Expiration:** 14-21 DTE
- **Strike:** ATM to 2.5% OTM (delta ~0.40-0.50)
- **Liquidity:** Open interest > 100, bid-ask spread < 10% of mid
- **Avoid:** Deep OTM (<0.30 delta), weekly options <7 DTE

### 6.9 Entry Logic
- Execute at market open or within first 30 minutes after candidate identification
- Enter when all filters pass AND sector ranking is confirmed
- Maximum 1 position per stock

### 6.10 Exit Logic
- **Profit Target:** 50% gain on option premium
- **Stop Loss:** 50% loss on option premium
- **Time Stop:** 5 DTE (close regardless of P/L)
- **Momentum Reversal:** Underlying closes below SMA20 AND RSI drops below 45
- **Maximum Hold:** 21 calendar days

### 6.11 Risk Management
- **Position Sizing:** Equal dollar risk per position (max 2% portfolio per position)
- **Sector Concentration:** No more than 3 candidates from the same sector
- **Market Filter:** Do NOT enter if SPY is below its 50-day SMA (avoid momentum crashes per Daniel & Moskowitz 2016)
- **VIX Filter:** If VIX > 30, reduce size by 50% or skip
- **Earnings Exclusion:** Exclude stocks with earnings within 5 days

### 6.12 Maximum Holding Period
**21 calendar days**

### 6.13 Scoring Considerations
- The existing scoring system already rewards trend alignment, relative strength, and volume confirmation
- Sector momentum adds an implicit boost to `market/sector environment` and `relative strength` factors
- No scoring changes required; the strategy's edge comes from **candidate selection**, not scoring modification

### 6.14 Expected Failure Modes
1. **Momentum Reversal:** Sector reverses abruptly on macro news. Mitigated by SMA20/RSI exit rules.
2. **Sector Rotation:** Money rotates quickly out of cyclicals. Mitigated by 3-week max hold.
3. **Earnings Conflict:** Volatility crush or gap risk. Mitigated by earnings exclusion.
4. **Option Illiquidity:** Wide bid-ask on mid-cap names. Mitigated by market cap sort and OI filter.
5. **Momentum Crash:** Sharp rebound after decline crushes momentum. Mitigated by SPY > SMA50 filter.

### 6.15 Implementation Notes
- **New file:** `app/services/sector_momentum_service.py`
- **Pattern:** Similar to `CoiledSetupCandidateService` — Finviz screen + yfinance validation
- **New dependency:** yfinance sector ETF download (already available via `YFinanceOptionsClient` or direct yfinance usage)
- **Finviz integration:** Reuse `FinvizQueryRunner.run_with_swap()` or add a new static query
- **Sector ETF mapping:** Hardcode the 8 sector ETF tickers in the service

---

## 7. New Strategy 4: Spring-Loaded Reversion

### 7.1 Strategy Name
**spring_loaded_reversion**

### 7.2 Core Thesis
Stocks in established long-term uptrends (price above SMA200) that experience sharp short-term pullbacks tend to revert to their mean within 5-10 trading days. When the pullback is accompanied by **realized volatility contraction** — narrowing Bollinger Bands, declining ATR, and shrinking volume — the compression acts like a coiled spring. Buying calls after this pattern captures the asymmetric payoff of the mean-reversion bounce with leverage.

### 7.3 Stock Universe
- **Geography:** USA-listed
- **Minimum Criteria:** Price > $15, Market Cap > $2B, Average Volume > 500K, Optionable
- **Sectors:** Energy, Materials, Industrials, Utilities, Consumer Staples, Healthcare, Financials, Real Estate
- **Excluded:** Technology, Communication Services

### 7.4 Sector Focus
Explicitly **non-technology**. Mean reversion is particularly effective in non-tech sectors because:
1. Slower information diffusion creates larger, more tradable reversals (Hou & Moskowitz 2005)
2. Less retail noise means overreactions are more systematic and recoverable
3. Macro-driven volatility spikes (commodity prices, rate changes) are often temporary

### 7.5 Why It Fits Short-Term Options
- Mean-reversion bounces typically resolve within 5-10 trading days (Jegadeesh 1990)
- Volatility contraction precedes expansion by 2-5 days (Bollinger Band Squeeze)
- 14-21 DTE calls capture the bounce while minimizing theta decay
- Defined risk of long calls is ideal for "catching a falling knife" in an uptrend

### 7.6 Data Requirements

| Data Point | Source | Access Method |
|------------|--------|---------------|
| Stock screener (sector, RSI, SMA) | Finviz | Playwright scrape |
| Historical prices (BB, ATR, volume) | yfinance | `Ticker.history(period="3mo")` |
| Options chain | Alpaca or yfinance | `get_option_chain()` |
| Earnings calendar | yfinance / Finnhub | `Ticker.calendar` |

### 7.7 Candidate Selection Rules (Exactly 5)

**Step 1: Finviz Base Screen**
```
https://finviz.com/screener?v=111
&f=geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_rsi_u35,ta_sma200_pa
&o=-marketcap
```
- Sector = all non-tech (pipe-separated OR)
- RSI(14) < 35 (oversold)
- Price above SMA200 (long-term uptrend intact)
- Sort by market cap descending

**Step 2: Realized Volatility Contraction Filter (yfinance)**
For each of the top 15 Finviz results:
1. **Bollinger Band %B:** `(Close - Lower) / (Upper - Lower)`. Keep only `%B < 0.15`
2. **BB Width Contraction:** Current width < average width over prior 20 days
3. **ATR Contraction:** `ATR(14) today < ATR(14) 5 days ago`
4. **Volume Contraction:** `Volume(5-day avg) < Volume(20-day avg) * 0.90`
5. **No Earnings Overhang:** Next earnings > 10 calendar days away

**Step 3: Rank & Select**
```
Score = 0.30 * (1 - %B) + 0.25 * (1 - width_ratio) + 0.20 * volume_contraction + 0.15 * ATR_contraction + 0.10 * market_cap_rank
```
- Select the **top 5** by Score
- If fewer than 5, return all valid candidates + warning

### 7.8 Option Contract Selection Logic
- **Structure:** Long Call
- **Expiration:** 14-21 DTE
- **Strike:** 0.40-0.50 delta (ATM to slightly ITM)
- **Liquidity:** Open interest > 100, bid-ask spread < 10% of mid
- **Avoid:** Deep OTM (<0.30 delta) — mean reversion bounces are typically 3-8%, not 15%+

### 7.9 Entry Logic
- Enter within 1 trading day of identification
- Prefer entry on a green candle or inside day after the contraction
- If stock gaps down >2% on identification day, wait for the following day

### 7.10 Exit Logic
- **Profit Target:** 50% gain on option premium
- **Mean Reversion Exit:** RSI(14) crosses back above 50
- **Technical Exit:** Stock closes below lower Bollinger Band (breakdown, not bounce)
- **Time Stop:** 10 trading days (2 weeks)
- **Max Loss:** Option loses 50% of premium

### 7.11 Risk Management
- **Position Sizing:** Equal dollar risk per position (max 2% portfolio per position)
- **Sector Concentration:** No more than 2 candidates from the same sector
- **Market Filter:** Do NOT enter if SPY is below its 200-day SMA
- **VIX Filter:** If VIX > 30, skip the run
- **Max Account Risk:** 5% of total capital at risk per strategy run

### 7.12 Maximum Holding Period
**21 calendar days** — hard time stop at 10 trading days

### 7.13 Scoring Considerations
- The existing scoring system already rewards price structure and trend alignment
- Mean reversion candidates may score lower on `trend alignment` if the 1-day/5-day returns are negative — this is expected and correct
- The strategy's edge comes from **candidate selection** (identifying oversold bounces), not from modifying the scoring formula
- However, the scoring system may need a slight adjustment: for `spring_loaded_reversion` candidates, the `price structure` factor should not be penalized for negative short-term returns if the stock is above SMA200 and RSI < 35

### 7.14 Expected Failure Modes
1. **Trend Breakdown:** Stock violates SMA200 after entry. Mitigated by SMA200 filter and technical exit.
2. **Sector-Wide Selloff:** Macro shock drives entire sector lower. Mitigated by SPY filter and sector limits.
3. **Theta Decay Without Bounce:** Stock moves sideways. Mitigated by 10-trading-day time stop.
4. **Earnings Surprise:** Undetected earnings date causes a gap. Mitigated by earnings exclusion.
5. **Low Option Liquidity:** Wide bid-ask on mid-cap names. Mitigated by market cap sort.

### 7.15 Implementation Notes
- **New file:** `app/services/spring_loaded_service.py`
- **Pattern:** Finviz screen + yfinance BB/ATR/volume validation
- **yfinance calculations:** Use pandas for BB, ATR, RSI. Reuse existing calculation logic if available.
- **Note:** The `market_snapshot` in the pipeline already includes 20-day returns and volume. BB/ATR calculations are new and should be done in the service or a shared utility.

---

## 8. New Strategy 5: Commodity Momentum Beta

### 8.1 Strategy Name
**commodity_momentum_beta**

### 8.2 Core Thesis
When underlying commodities experience sustained upward momentum, commodity-linked equities magnify those moves through **embedded operating leverage** (Gorton & Rouwenhorst, 2006). Producers' fixed costs become a smaller percentage of revenue as commodity prices rise, causing equity moves to exceed commodity moves. Research by Miffre & Rallis (2007) confirms commodity momentum persists at 1-6 month horizons, and Asness et al. (2013) show cross-asset momentum spillover from commodities to equities.

### 8.3 Stock Universe
- **Geography:** USA-listed
- **Minimum Criteria:** Price > $15, Market Cap > $1B, Average Volume > 500K, Optionable
- **Sectors:** Energy (XLE), Materials (XLB), Oil & Gas E&P, Mining (gold, silver, copper, uranium), Chemicals, Fertilizers/Agriculture inputs
- **Excluded:** Technology, REITs, Financials, Biotech

### 8.4 Sector Focus
Explicitly **commodity-linked non-technology**. This strategy adds a macro overlay that the existing pipeline lacks. It captures energy, materials, mining, and agriculture — sectors that often move independently of the broad market and technology.

### 8.5 Why It Fits Short-Term Options
- Commodity momentum persists at 1-6 month horizons (Miffre & Rallis 2007)
- Options with 14-21 DTE capture the majority of the move while minimizing theta
- Commodity-linked stocks exhibit higher implied volatility than the broad market, making OTM calls relatively cheap on a realized vol basis when momentum is genuine
- Operating leverage creates asymmetric upside (beta 1.5-3.0x to commodities)

### 8.6 Data Requirements

| Data Point | Source | Access Method |
|------------|--------|---------------|
| Commodity ETF price history | yfinance | `yfinance.download([USO, UNG, GLD, SLV, DBB, XLE, XLB], period='1mo')` |
| Stock screener (sector, volume, performance) | Finviz | Playwright scrape |
| Options chain | yfinance or Alpaca | `get_option_chain()` |

### 8.7 Candidate Selection Rules (Exactly 5)

**Step 1: Identify the Strongest Commodity Theme**
1. Download 20-day closing prices for commodity proxy ETFs: USO (oil), UNG (gas), GLD (gold), SLV (silver), DBB (base metals), XLE (energy), XLB (materials)
2. Compute 5-day and 20-day returns for each ETF
3. A commodity is "trending" if: 5-day return > 0 AND 20-day return > +2% AND price > 20-day SMA
4. Select the **top 1-2 commodity themes** by 20-day return

**Step 2: Finviz Screener for the Winning Commodity Sector**
```
https://finviz.com/screener?v=111
&f=sec_energy,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_perf_1wup,ta_rsi_o50,ta_sma20_pa
&o=-relativevolume
```
- Adjust `sec_energy` to `sec_basicmaterials` or industry filters for mining/chemicals
- Relative Volume > 1.5x (institutional participation)
- Performance 1-week up
- RSI > 50 and < 75 (avoids overbought blow-offs)
- Price above SMA20

**Step 3: Options Liquidity Check**
- Verify at least 2 expiration dates within 14-28 days
- Front-month OTM call open interest > 100
- Bid-ask spread on ATM call < 10%

**Step 4: Rank & Select Top 5**
- Sort by `relativevolume` descending, then by `performance` descending
- Take the top 5
- If fewer than 5 pass liquidity checks, return valid candidates + warning

### 8.8 Option Contract Selection Logic
- **Structure:** Long Call
- **Expiration:** 14-21 DTE
- **Strike:** 2-5% OTM (delta ~0.30-0.40)
- **Target Greeks:** Positive gamma, manageable theta (<2% of option price per day)
- **Avoid:** Weekly options <7 DTE, deep OTM (<0.20 delta)

### 8.9 Entry Logic
1. Commodity proxy ETF 20-day return > +2% and price > 20-day SMA
2. Stock screener returns at least 5 tickers meeting filters
3. Stock price > SMA20 and relative volume > 1.5x
4. Buy at market open or on a 15-minute pullback after 10:00 AM ET

### 8.10 Exit Logic
- **Profit Target:** 50% gain on option premium
- **Time Stop:** Close all positions at 3 DTE
- **Technical Stop:** If the underlying commodity ETF closes below its 20-day SMA, close all related equity calls next day open
- **Trailing Stop:** Once up 30%, raise stop to breakeven

### 8.11 Risk Management
- **Position Sizing:** Max 2% of portfolio per contract
- **Sector Concentration:** If all 5 candidates are from the same sub-sector (e.g., all oil E&Ps), reduce position size by 30%
- **Correlation Check:** Ensure at least 2 of 5 names are from a different commodity theme (e.g., 3 energy + 2 materials)
- **Max Loss:** 100% of option premium (defined risk)

### 8.12 Maximum Holding Period
**21 calendar days**

### 8.13 Scoring Considerations
- The existing scoring system does not explicitly reward commodity momentum
- However, commodity-linked stocks in uptrends will naturally score well on `trend alignment`, `relative strength`, and `price structure`
- The commodity ETF momentum signal acts as a **pre-filter**, ensuring only high-conviction candidates reach the scoring stage
- No scoring changes required

### 8.14 Expected Failure Modes
1. **Commodity momentum reversal:** Commodity proxy drops >3% in 2 days. Mitigated by commodity SMA break rule.
2. **Equity beta decoupling:** Broad market selloff overrides commodity strength. SMA20 filter helps but does not eliminate.
3. **Low realized volatility:** Stock moves sideways, theta decay erodes premium. 3 DTE time stop limits this.
4. **Illiquid options:** Small-cap commodity names have wide spreads. OI > 100 filter mitigates.

### 8.15 Implementation Notes
- **New file:** `app/services/commodity_momentum_service.py`
- **Pattern:** yfinance ETF momentum check → Finviz sector screen → yfinance stock validation
- **Commodity ETF mapping:** Hardcode in service
  - Crude Oil: USO
  - Natural Gas: UNG
  - Gold: GLD
  - Silver: SLV
  - Base Metals: DBB
  - Broad Energy: XLE
  - Broad Materials: XLB
- **Sector filter logic:** Map winning commodity ETF to corresponding Finviz sector filter

---

## 9. Updated 5-Strategy Pipeline

### 9.1 Pipeline Flow

```
┌─────────────────────────────────────────────────────────────┐
│  STRATEGY 1: catalyst_confluence                             │
│  → Finviz earnings screen + backup earnings sources          │
│  → 5 candidates                                              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  STRATEGY 2: coiled_setup                                    │
│  → Finviz trend/structure screen                             │
│  → 5 candidates                                              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  STRATEGY 3: sector_momentum_ignition                        │
│  → yfinance sector ETF ranking + Finviz screen + validation  │
│  → 5 candidates                                              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  STRATEGY 4: spring_loaded_reversion                         │
│  → Finviz oversold screen + yfinance BB/ATR/volume filter    │
│  → 5 candidates                                              │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│  STRATEGY 5: commodity_momentum_beta                         │
│  → yfinance commodity ETF momentum + Finviz sector screen    │
│  → 5 candidates                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  MERGE & DEDUPLICATE                                         │
│  → Merge all 25 candidates                                   │
│  → Deduplicate by ticker (preserve first-seen strategy)      │
│  → Expected unique candidates: 15-25                         │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  SCORING PIPELINE (existing)                                 │
│  → Market data fetch                                         │
│  → Options chain fetch                                       │
│  → Direction scoring                                         │
│  → Contract scoring                                          │
│  → Final score = 0.45*direction + 0.55*contract              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  TOP 4 SELECTION (existing, DECISION_FINALIST_LIMIT = 4)     │
│  → Sort by (final_score, confidence_score, direction_score)  │
│  → Select top 4                                              │
│  → Refresh finalists with live news                          │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  LLM ANALYSIS (existing)                                     │
│  → Heavy model (Claude Opus 4.7) receives structured input   │
│  → Qualitative reasoning, risk review, final judgment        │
│  → Output: StructuredDecision                                │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────┐
│  FINAL RECOMMENDATION (existing)                             │
│  → Persist to database                                       │
│  → Send Telegram notification                                │
└─────────────────────────────────────────────────────────────┘
```

### 9.2 Candidate Count Math

| Strategy | Candidates | Deduplication Impact |
|----------|-----------|---------------------|
| catalyst_confluence | 5 | Baseline |
| coiled_setup | 5 | ~1-2 overlaps with catalyst |
| sector_momentum_ignition | 5 | ~1-2 overlaps with coiled_setup |
| spring_loaded_reversion | 5 | Low overlap (oversold vs. momentum) |
| commodity_momentum_beta | 5 | Low overlap (commodity-specific) |
| **Expected unique total** | **~20-23** | After deduplication |

### 9.3 Why the Pipeline Stays the Same

The existing pipeline is designed to handle an arbitrary number of candidates. Key properties:
- `CandidateBatch.candidates` is a tuple of `CandidateRecord` — no size limit
- `PipelineOrchestrator.evaluate_batch()` uses `asyncio.gather()` to score all candidates in parallel
- `_select_decision_finalists()` already selects top 4 from any number of candidates
- The LLM `DecisionInput` has `candidates: list[CandidateBundle] = Field(min_length=1)` — no max length

The only change needed is in the **candidate generation step** (`MultiStrategyCandidateService`) to merge 5 strategies instead of 2.

---

## 10. Scoring System Integration

### 10.1 Can the Existing Scoring System Support the New Strategies?

**Yes, with minimal adjustments.**

The existing scoring system is strategy-agnostic. It evaluates candidates based on:
- Market data (price, volume, returns, relative strength)
- Option chain data (liquidity, breakeven, strike fit, IV, premium)
- Direction (trend, volume, earnings, sector, price structure)
- Data confidence (identity, earnings, market, options, cross-source)

All three new strategies produce `CandidateRecord` and `CandidateContext` objects that the scoring system can evaluate without modification.

### 10.2 Scoring Features to Add

**1. Strategy Source Labeling**
- Add `strategy_source` values: `"sector_momentum_ignition"`, `"spring_loaded_reversion"`, `"commodity_momentum_beta"`
- Update `StrategySource` Literal in `app/services/candidate_models.py`
- Update `StrategySource` Literal in `app/scoring/types.py`

**2. Strategy-Specific Scoring Adjustments (Optional)**
- For `spring_loaded_reversion`: The `price_structure` signal may be negative due to recent pullback. Consider adding a small boost (+3-5 points) to the `price_structure` factor when `RSI < 35` and `price > SMA200`, to avoid penalizing mean-reversion candidates for their temporary weakness.
- For `sector_momentum_ignition`: The `market/sector environment` factor should already score well if the sector is trending. No change needed.
- For `commodity_momentum_beta`: No change needed; commodity momentum is captured in `trend alignment` and `relative strength`.

**3. Shared Scoring Reused**
- All existing scoring factors apply unchanged
- Liquidity scoring, expiry fit, strike/moneyness, IV setup, premium fit — all strategy-agnostic
- Hard vetoes and soft penalties apply unchanged

### 10.3 Penalties and Filters

**New Penalty: Sector Concentration**
- If >3 candidates from the same sector appear in the merged 25, apply a -2 point penalty to sector-concentrated candidates beyond the top 3
- Rationale: Prevents pipeline from becoming overly concentrated in one sector

**New Penalty: Strategy Concentration**
- If >8 candidates from the same strategy appear in the merged 25, apply a -1 point penalty to candidates beyond the top 8
- Rationale: Ensures diversification across strategy types

### 10.4 Keeping Scoring Deterministic

- All new scoring adjustments must be pure functions of candidate data
- No randomness, no LLM involvement in scoring
- The existing `score_candidate()` function remains the single source of truth for numeric rankings

### 10.5 Preventing LLM from Overriding Deterministic Ranking

The existing `validate_llm_decision()` function in `app/pipeline/steps/decide.py` already enforces this:
- It computes `structural_final_score` from deterministic scoring
- It computes `structural_band` from the structural action
- It sets `final_band = _min_band(nominated_band, structural_band)`
- This ensures the LLM can only **downgrade** a candidate, never upgrade it above its deterministic score

**No changes needed** to this logic. The LLM continues to provide qualitative analysis only for the top 4 candidates.

---

## 11. Data Source Plan

### 11.1 Strategy 3: Sector Momentum Ignition

| Data | Source | Backup | New Source? | Rate Limit | Reliability |
|------|--------|--------|-------------|------------|-------------|
| Sector ETF prices | yfinance | Alpha Vantage | No | ~2000/hr | Medium |
| Stock screen | Finviz | None | No | N/A (Playwright) | Medium |
| Stock prices/technicals | yfinance | Alpha Vantage | No | ~2000/hr | Medium |
| Options chain | Alpaca | yfinance | No | 200/min | Good |
| Earnings calendar | yfinance | Finnhub | No | 60/min | Good |

**If data is missing:**
- If yfinance sector ETF data fails, skip the run and log: `⚠️ Sector momentum scan skipped — ETF data unavailable.`
- If Finviz fails, retry once, then retry with clean context, then degrade to empty tuple

### 11.2 Strategy 4: Spring-Loaded Reversion

| Data | Source | Backup | New Source? | Rate Limit | Reliability |
|------|--------|--------|-------------|------------|-------------|
| Stock screen | Finviz | None | No | N/A (Playwright) | Medium |
| Historical prices | yfinance | Alpha Vantage | No | ~2000/hr | Medium |
| BB/ATR/RSI calc | yfinance (local) | None | No | N/A | High |
| Options chain | Alpaca | yfinance | No | 200/min | Good |
| Earnings calendar | yfinance | Finnhub | No | 60/min | Good |

**If data is missing:**
- If yfinance historical data is unavailable for a candidate, drop the candidate
- If fewer than 3 candidates pass all filters, surface warning: `⚠️ Only {N} spring-loaded candidates found; mean reversion setups are scarce this week.`

### 11.3 Strategy 5: Commodity Momentum Beta

| Data | Source | Backup | New Source? | Rate Limit | Reliability |
|------|--------|--------|-------------|------------|-------------|
| Commodity ETF prices | yfinance | Alpha Vantage | No | ~2000/hr | Medium |
| Stock screen | Finviz | None | No | N/A (Playwright) | Medium |
| Stock prices | yfinance | Alpha Vantage | No | ~2000/hr | Medium |
| Options chain | Alpaca | yfinance | No | 200/min | Good |

**If data is missing:**
- If commodity ETF data is unavailable, skip the run and log: `⚠️ Commodity momentum scan skipped — commodity proxy data unavailable.`
- If no commodity themes are trending (no ETF with 20-day return > +2%), skip the run and log: `⚠️ No commodity themes are trending this week; commodity momentum scan skipped.`

### 11.4 New Data Source Assessment

**No new data sources are required.** All three strategies use:
- Finviz (already used)
- yfinance (already used)
- Alpaca (already used)
- Finnhub (already used)

This was a key selection criterion. Strategies requiring FDA calendars, OPEC calendars, or full options flow data were rejected because they would introduce fragile new dependencies.

---

## 12. Implementation Plan

### 12.1 Phase 1: Inspect and Prepare Data/Schema/Config

**Duration:** 1 day  
**Files to modify:**

1. **`app/services/candidate_models.py`**
   - Update `StrategySource` Literal to include 3 new values
   ```python
   StrategySource = Literal[
       "catalyst_confluence",
       "coiled_setup",
       "sector_momentum_ignition",
       "spring_loaded_reversion",
       "commodity_momentum_beta",
   ]
   ```

2. **`app/scoring/types.py`**
   - Update `StrategySource` Literal to match

3. **`app/services/strategy_catalog.py`**
   - Add `StrategyDefinition` entries for the 3 new strategies
   - Add filter codes, criteria summaries, sort summaries, query URLs

4. **`app/core/config.py`**
   - Add optional config flags for new strategies (e.g., `sector_momentum_enabled: bool = True`)

**Tests to add:**
- Schema validation test for new `StrategySource` values
- Strategy catalog test for new definitions

### 12.2 Phase 2: Add Candidate Generation for Strategy 3 (Sector Momentum Ignition)

**Duration:** 2 days  
**New files:**
- `app/services/sector_momentum_service.py`
- `app/services/finviz/strategies.py` (add `STRATEGY_C` query definitions)

**Implementation:**
1. Create `SectorMomentumCandidateService` class with `async def get_top_five()`
2. Download sector ETF prices via yfinance
3. Rank sectors, build Finviz URLs for top sectors
4. Fetch Finviz results via `FinvizQueryRunner`
5. Validate candidates via yfinance (SMA, RSI, volume)
6. Score and rank top 5
7. Return `tuple[CandidateRecord, ...]`

**Tests to add:**
- Unit test for sector ranking logic
- Unit test for momentum acceleration filter
- Unit test for candidate count = 5
- Unit test for Finviz fallback behavior
- Integration test with `FinvizQueryRunner`

### 12.3 Phase 3: Add Candidate Generation for Strategy 4 (Spring-Loaded Reversion)

**Duration:** 2 days  
**New files:**
- `app/services/spring_loaded_service.py`
- `app/services/finviz/strategies.py` (add `STRATEGY_D` query definitions)

**Implementation:**
1. Create `SpringLoadedCandidateService` class
2. Build Finviz URL for RSI < 35, above SMA200, non-tech
3. Fetch top 15 results
4. For each result, download 3 months of yfinance data
5. Compute Bollinger Bands, ATR, volume averages
6. Apply contraction filters
7. Score and rank top 5
8. Return `tuple[CandidateRecord, ...]`

**Tests to add:**
- Unit test for BB width contraction detection
- Unit test for ATR decline detection
- Unit test for volume contraction filter
- Unit test for candidate count = 5
- Unit test for earnings exclusion
- Integration test with yfinance data

### 12.4 Phase 4: Add Candidate Generation for Strategy 5 (Commodity Momentum Beta)

**Duration:** 2 days  
**New files:**
- `app/services/commodity_momentum_service.py`
- `app/services/finviz/strategies.py` (add `STRATEGY_E` query definitions)

**Implementation:**
1. Create `CommodityMomentumCandidateService` class
2. Download commodity ETF prices via yfinance
3. Identify trending commodities (5-day > 0, 20-day > +2%, price > SMA20)
4. Map winning commodity to Finviz sector filter
5. Fetch Finviz results
6. Validate options liquidity via yfinance or Alpaca
7. Rank and select top 5
8. Return `tuple[CandidateRecord, ...]`

**Tests to add:**
- Unit test for commodity ETF momentum detection
- Unit test for sector mapping logic
- Unit test for options liquidity check
- Unit test for candidate count = 5
- Integration test with yfinance ETF data

### 12.5 Phase 5: Integrate All Candidates into the Scoring Pipeline

**Duration:** 2 days  
**Files to modify:**
- `app/services/multi_strategy_service.py`

**Implementation:**
1. Add 3 new service instances to `MultiStrategyCandidateService.__init__`
2. Update `get_candidates()` to gather results from all 5 strategies
3. Update `_merge_dedupe()` to handle 5 strategy lists
4. Add strategy-specific warning texts
5. Update `get_multi_strategy_service()` factory to instantiate all 5 services

**New deduplication rules:**
- Preserve the first-seen strategy's candidate when tickers overlap
- Priority order: catalyst_confluence > coiled_setup > sector_momentum_ignition > spring_loaded_reversion > commodity_momentum_beta
- Rationale: Earnings catalyst is the highest-conviction discrete event; commodity momentum is the most macro and may overlap with other trends

**Tests to add:**
- Unit test for 5-strategy merge and deduplication
- Unit test for priority order when tickers overlap
- Unit test for warning text generation when strategies fail

### 12.6 Phase 6: Send Only Top 4 Candidates to LLM

**Duration:** 0.5 days  
**Files to modify:** None (already implemented)

The existing `DECISION_FINALIST_LIMIT = 4` in `app/pipeline/orchestrator.py` already enforces this. No changes needed.

**Tests to add:**
- Unit test confirming only top 4 are sent to LLM even with 25 candidates
- Unit test confirming LLM payload contains correct candidate count

### 12.7 Phase 7: Add Logging and Auditability

**Duration:** 1 day  
**Files to modify:**
- `app/services/multi_strategy_service.py`
- `app/services/sector_momentum_service.py`
- `app/services/spring_loaded_service.py`
- `app/services/commodity_momentum_service.py`

**Implementation:**
1. Add structured logging for each strategy:
   - `strategy_name`, `raw_candidates`, `filtered_candidates`, `final_candidates`
   - `tickers`, `sectors`, `scores`
   - `warnings`, `errors`, `fallback_used`
2. Ensure all logs use the existing `get_logger()` pattern
3. Add `strategy_reports` to `CandidateBatch` for each new strategy

**Tests to add:**
- Unit test for log output validation
- Unit test for strategy report generation

### 12.8 Phase 8: Add Tests and Backtesting

**Duration:** 3 days  
**See Section 13 for full test list.**

**Backtesting approach:**
1. Freeze historical data (Finviz + yfinance) for a 3-month period
2. Run each new strategy daily over the period
3. Record candidates, scores, and hypothetical P&L
4. Compare against buy-and-hold and against existing strategies
5. Identify any overfitting or data leakage

---

## 13. Required Tests

### 13.1 Unit Tests for Each New Candidate Generator

**`test_sector_momentum_service.py`**
- `test_sector_ranking_correctly_computes_returns()`
- `test_sector_ranking_selects_top_3()`
- `test_momentum_acceleration_filter_rejects_stocks_below_sma20()`
- `test_momentum_acceleration_filter_rejects_overbought_rsi()`
- `test_momentum_acceleration_filter_rejects_declining_volume()`
- `test_produces_exactly_5_candidates()`
- `test_produces_fewer_than_5_when_universe_is_small()`
- `test_finviz_fallback_returns_empty_tuple()`
- `test_etf_download_failure_returns_warning()`

**`test_spring_loaded_service.py`**
- `test_bb_percent_b_computed_correctly()`
- `test_bb_width_contraction_detected()`
- `test_atr_contraction_detected()`
- `test_volume_contraction_detected()`
- `test_earnings_exclusion_filters_correctly()`
- `test_produces_exactly_5_candidates()`
- `test_produces_fewer_than_5_when_universe_is_small()`
- `test_finviz_fallback_returns_empty_tuple()`

**`test_commodity_momentum_service.py`**
- `test_commodity_momentum_detects_trending_etfs()`
- `test_commodity_momentum_rejects_flat_etfs()`
- `test_sector_mapping_energy_to_finviz_filter()`
- `test_sector_mapping_materials_to_finviz_filter()`
- `test_options_liquidity_check_filters_correctly()`
- `test_produces_exactly_5_candidates()`
- `test_produces_fewer_than_5_when_universe_is_small()`
- `test_no_trending_commodities_returns_warning()`

### 13.2 Unit Tests for Strategy-Specific Scoring

- `test_spring_loaded_reversion_price_structure_not_penalized()`
- `test_sector_momentum_sector_environment_boosted()`
- `test_commodity_momentum_trend_alignment_boosted()`

### 13.3 Data Source Tests

- `test_yfinance_sector_etf_download_success()`
- `test_yfinance_sector_etf_download_failure_handled()`
- `test_yfinance_historical_prices_for_bb_atr_calc()`
- `test_yfinance_commodity_etf_download_success()`
- `test_alpaca_options_chain_for_liquidity_check()`
- `test_finviz_screener_url_construction_for_each_strategy()`

### 13.4 Missing Data Tests

- `test_strategy_skips_run_when_finviz_fails()`
- `test_strategy_skips_run_when_yfinance_fails()`
- `test_strategy_degrades_gracefully_with_partial_data()`
- `test_candidate_dropped_when_historical_data_unavailable()`

### 13.5 Candidate Count Tests

- `test_each_strategy_produces_at_most_5_candidates()`
- `test_each_strategy_produces_at_least_0_candidates()`
- `test_pipeline_handles_25_candidates()`

### 13.6 25-Candidate Pipeline Test

- `test_pipeline_merges_5_strategies_into_single_batch()`
- `test_pipeline_deduplicates_overlapping_tickers()`
- `test_pipeline_preserves_priority_order_on_dedupe()`
- `test_pipeline_generates_strategy_reports_for_all_5()`
- `test_pipeline_screener_status_success_when_all_5_succeed()`
- `test_pipeline_screener_status_partial_when_1_fails()`
- `test_pipeline_screener_status_failed_when_all_fail()`

### 13.7 Top-4 Selection Test

- `test_top_4_selected_from_25_candidates()`
- `test_top_4_sorted_by_final_score()`
- `test_top_4_tiebreak_by_confidence_score()`
- `test_top_4_tiebreak_by_direction_score()`
- `test_finalists_refreshed_with_live_news()`

### 13.8 LLM Payload Validation Test

- `test_llm_payload_contains_exactly_4_candidates()`
- `test_llm_payload_contains_correct_candidate_fields()`
- `test_llm_payload_contains_viable_contracts_only()`

### 13.9 Determinism Test

- `test_scoring_produces_identical_results_on_identical_inputs()`
- `test_pipeline_produces_identical_batch_on_identical_inputs()`
- `test_no_randomness_in_candidate_selection()`

### 13.10 Regression Tests with Frozen Data

- `test_frozen_finviz_data_produces_expected_candidates()`
- `test_frozen_yfinance_data_produces_expected_scores()`
- `test_frozen_pipeline_produces_expected_recommendation()`

### 13.11 Backtesting Tests

- `test_backtest_sector_momentum_over_3_months()`
- `test_backtest_spring_loaded_over_3_months()`
- `test_backtest_commodity_momentum_over_3_months()`
- `test_backtest_sharpe_ratio_positive()`
- `test_backtest_max_drawdown_acceptable()`

### 13.12 Failure Mode Tests

- `test_momentum_crash_scenario_handled_by_spy_filter()`
- `test_mean_reversion_in_bear_market_handled_by_sma200_filter()`
- `test_commodity_reversal_handled_by_etf_sma_filter()`
- `test_finviz_browser_error_triggers_retry()`
- `test_finviz_second_failure_triggers_clean_context_retry()`
- `test_finviz_third_failure_degrades_to_empty_tuple()`

---

## 14. Risk Analysis

### 14.1 Weak or Delayed Data

| Risk | Impact | Mitigation |
|------|--------|------------|
| Finviz screener fails | Strategy produces 0 candidates | Retry ladder (page → clean context → empty tuple) |
| yfinance data stale | Incorrect SMA/RSI/ATR calculations | Use 3-month lookback; cross-check with Alpha Vantage |
| Sector ETF data missing | Sector momentum cannot rank | Skip run with warning |
| Commodity ETF data missing | Commodity momentum cannot identify trend | Skip run with warning |

### 14.2 Poor Option Liquidity

| Risk | Impact | Mitigation |
|------|--------|------------|
| Wide bid/ask spreads on mid-cap names | High slippage on entry/exit | OI > 100 filter; market cap sort; bid-ask < 10% veto |
| Low open interest | Difficult to exit | OI > 100 filter; avoid micro-caps |
| No options on screened stock | Cannot trade | `sh_opt_option` Finviz filter; options chain validation |

### 14.3 Overfitting

| Risk | Impact | Mitigation |
|------|--------|------------|
| BB/ATR parameters overfit to historical data | Poor out-of-sample performance | Use standard parameters (20-day BB, 14-day ATR); do not optimize |
| Sector momentum lookback overfit | False trend detection | Use 1-month + 2-week composite; avoid shorter lookbacks |
| Commodity ETF threshold overfit | Misses valid trends or catches false ones | Use conservative thresholds (+2% 20-day return); backtest before tightening |

### 14.4 Sector Concentration

| Risk | Impact | Mitigation |
|------|--------|------------|
| All 5 candidates from same sector | Undiversified exposure | Sector concentration limit (max 3 per sector); scoring penalty for excess |
| Commodity momentum always picks energy | Energy sector overexposure | Require at least 2 commodity themes; diversify across energy + materials |

### 14.5 Catalyst Failure

| Risk | Impact | Mitigation |
|------|--------|------------|
| Sector momentum reverses abruptly | Loss on momentum trades | SMA20/RSI exit rules; SPY > SMA50 filter |
| Mean reversion fails (stock keeps falling) | Loss on reversion trades | SMA200 filter; lower BB exit; 50% stop loss |
| Commodity momentum reverses | Loss on commodity trades | Commodity ETF SMA break rule; 50% stop loss |

### 14.6 Free API Limitations

| Risk | Impact | Mitigation |
|------|--------|------------|
| yfinance rate limit (2000/hr) | Data fetch fails | Batch downloads; cache results; use Alpha Vantage fallback |
| Alpaca rate limit (200/min) | Options chain fetch fails | Batch requests; cache chains; use yfinance fallback |
| Finnhub rate limit (60/min) | Earnings calendar fails | Cache earnings dates; use yfinance fallback |
| Alpha Vantage rate limit (25/day) | Market data fails | Use only as last-resort fallback |

### 14.7 Fragile Web Scraping

| Risk | Impact | Mitigation |
|------|--------|------------|
| Finviz changes DOM structure | Scraper breaks | Use stable table selectors; monitor for failures; fallback to empty tuple |
| Finviz blocks Playwright | Browser automation fails | Rotate user agents; use headless mode; retry with clean context |

### 14.8 LLM Hallucination / Nondeterminism

| Risk | Impact | Mitigation |
|------|--------|------------|
| LLM selects candidate not in top 4 | Overrides deterministic ranking | `validate_llm_decision()` enforces structural band minimum; can only downgrade |
| LLM invents contract not in chain | Invalid recommendation | Contract existence validation; fallback to heuristic |
| LLM reasoning inconsistent across runs | User confusion | Seed=0 for deterministic sampling; reasoning excluded from response |

### 14.9 Short-Option Assignment Risk

**Not applicable.** All three new strategies are long-call strategies. The existing short_put and short_call handling in the scoring system is unchanged. Short premium strategies were deferred to Phase 2 to avoid introducing assignment risk before the long strategies are stable.

### 14.10 Macro Events Affecting All Strategies

| Event | Impact on SMI | Impact on Spring-Loaded | Impact on Commodity |
|-------|--------------|------------------------|---------------------|
| Fed surprise | Sector rotation risk | Mean reversion may fail if selloff continues | Commodity-specific; may decouple |
| Geopolitical shock | Momentum crash risk | Oversold may become more oversold | Energy/materials may spike or crash |
| Broad market selloff (SPY <-5% in week) | SPY < SMA50 filter skips run | SPY < 200 SMA filter skips run | Commodity ETF SMA break may close positions |
| VIX spike >30 | Reduced size or skip | Skip run | Reduced size |

---

## 15. Final Recommendation

### 15.1 The 3 Strategies to Add

1. **sector_momentum_ignition** — Dual sector + individual momentum in non-tech sectors
2. **spring_loaded_reversion** — Oversold bounce after volatility contraction in non-tech uptrends
3. **commodity_momentum_beta** — Commodity-linked equity momentum via operating leverage

### 15.2 Why These 3 Were Selected

- **Diversification:** They cover momentum, mean reversion, and macro momentum — three distinct market regimes
- **Research quality:** Each is backed by multiple peer-reviewed papers (Moskowitz & Grinblatt, De Bondt & Thaler, Miffre & Rallis)
- **System fit:** Each uses only existing data sources (Finviz, yfinance, Alpaca, Finnhub)
- **Non-tech focus:** All three exclude technology, addressing the current pipeline's concentration risk
- **Implementation feasibility:** Each can be built in 2 days following the existing `CoiledSetupCandidateService` pattern
- **Pipeline alignment:** All three are long-call strategies, fitting the existing scoring, sizing, and exit-target infrastructure

### 15.3 Why Rejected Strategies Were Weaker

| Rejected Strategy | Primary Weakness |
|-------------------|------------------|
| Regulatory Run-Up | Fragile FDA calendar scraping; biotech binary risk |
| Commodity Macro Inflection | OPEC calendar irregular; EIA too noisy |
| Short Premium (VRP) | Assignment risk; pipeline not ready for short strategies |
| Gamma Trap Hunter | Unreliable options OI data in free tier |
| Short Squeeze Sentinel | Short interest data too stale (bi-monthly) |
| Rate-Sensitive Rotation | Treasury regime too slow for short-term options |
| IV Compression Bounce | Too similar to Spring-Loaded; IV/HV data unreliable |

### 15.4 Which Strategy Should Be Implemented First

**Phase 1: sector_momentum_ignition**
- It has the strongest academic support (Moskowitz & Grinblatt is one of the most cited papers in finance)
- It is the most distinct from existing strategies (adds sector rotation layer)
- It has the highest automation feasibility (yfinance ETF download + Finviz screen)
- It will immediately improve sector diversification

**Phase 2: spring_loaded_reversion**
- Complements momentum with mean reversion
- Adds value in choppy/range-bound markets where momentum fails
- Requires BB/ATR calculations but these are standard

**Phase 3: commodity_momentum_beta**
- Adds macro/commodity exposure
- Depends on yfinance commodity ETF data which is reliable
- Best implemented after the first two are stable

### 15.5 What Must Be Tested Before Live or Paper Use

**Before paper trading:**
1. All unit tests for candidate generation (Section 13.1)
2. All data source tests (Section 13.3)
3. 25-candidate pipeline test (Section 13.6)
4. Top-4 selection test (Section 13.7)
5. Determinism test (Section 13.9)

**Before live trading:**
1. Backtesting over 3 months of frozen data (Section 13.11)
2. Failure mode tests (Section 13.12)
3. Regression tests with frozen data (Section 13.10)
4. Manual inspection of 20+ generated candidate lists for quality
5. Paper trade for 4 weeks to validate execution feasibility

### 15.6 Unresolved Questions or Assumptions

1. **yfinance reliability for sector ETF data:** yfinance is free but occasionally returns stale or missing data. We assume a 3-month lookback is sufficient for SMA/RSI/ATR calculations. If yfinance becomes unreliable, we may need to add Alpha Vantage as a primary fallback.

2. **Finviz sector filter syntax:** The pipe-separated sector filters (`sec_energy|sec_materials|...`) need to be tested for exact Finviz URL compatibility. If Finviz does not support OR filters in a single URL, we may need to run multiple queries and merge results.

3. **Scoring bias against mean reversion:** The existing scoring system may penalize `spring_loaded_reversion` candidates for negative short-term returns. We assume a small adjustment (+3-5 points to `price_structure` when RSI < 35 and above SMA200) will suffice, but this needs A/B testing.

4. **Commodity ETF to sector mapping:** The mapping from commodity ETFs (USO, GLD, etc.) to Finviz sector filters is straightforward but may miss niche commodities (e.g., uranium, lithium). We assume the broad Energy and Materials sectors capture enough liquid optionable names.

5. **Options liquidity on mid-cap commodity names:** Some commodity-linked stocks (especially miners and small E&Ps) may have thin options markets. We assume the OI > 100 filter and market cap sort will eliminate most illiquid names, but this needs validation in paper trading.

6. **Deduplication priority order:** The proposed priority (catalyst > coiled > sector momentum > spring-loaded > commodity) is a reasonable heuristic but may need adjustment based on observed overlap rates.

---

## Appendices

### A. Key Academic Citations

1. **Moskowitz, T. J., & Grinblatt, M. (1999).** "Do Industries Explain Momentum?" *Journal of Finance*, 54(4), 1249-1290. https://www.jstor.org/stable/2697714

2. **Jegadeesh, N., & Titman, S. (1993).** "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65-91. https://www.jstor.org/stable/2328882

3. **Hou, K., & Moskowitz, T. J. (2005).** "Market Frictions, Price Delay, and the Cross-Section of Expected Returns." *Review of Financial Studies*, 18(3), 981-1020. https://academic.oup.com/rfs/article-abstract/18/3/981/1566509

4. **Daniel, K., & Moskowitz, T. J. (2016).** "Momentum Crashes." *Journal of Financial Economics*, 122(2), 221-247. https://www.sciencedirect.com/science/article/abs/pii/S0304405X1630132X

5. **De Bondt, R., & Thaler, R. (1985).** "Does the Stock Market Overreact?" *Journal of Finance*, 40(3), 793-805. https://www.jstor.org/stable/2327804

6. **Bollinger, J. (2002).** *Bollinger on Bollinger Bands*. McGraw-Hill.

7. **Natenberg, S. (1994).** *Option Volatility and Pricing* (2nd ed.). McGraw-Hill.

8. **Miffre, J., & Rallis, G. (2007).** "Momentum in Commodity Futures Markets." *Journal of Banking & Finance*, 31(6), 1863-1886. https://doi.org/10.1016/j.jbankfin.2006.09.009

9. **Gorton, G., & Rouwenhorst, K. G. (2006).** "Facts and Fantasies about Commodity Futures." *Financial Analysts Journal*, 62(2), 47-68. https://doi.org/10.2469/faj.v62.n2.4083

10. **Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013).** "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929-985. https://doi.org/10.1111/jofi.12021

### B. Existing File Inventory

| File | Purpose | Reuse? |
|------|---------|--------|
| `app/services/candidate_models.py` | CandidateRecord, CandidateBatch, StrategyRunReport | Modify (add StrategySource) |
| `app/services/candidate_service.py` | catalyst_confluence implementation | Reference only |
| `app/services/coiled_setup_service.py` | coiled_setup implementation | Reference pattern |
| `app/services/multi_strategy_service.py` | Merges 2 strategies | Modify (merge 5) |
| `app/services/strategy_catalog.py` | StrategyDefinition registry | Modify (add 3 definitions) |
| `app/services/finviz/strategies.py` | Finviz query definitions | Modify (add 3 queries) |
| `app/services/finviz/runner.py` | FinvizQueryRunner | Reuse unchanged |
| `app/services/finviz/browser.py` | FinvizBrowserClient | Reuse unchanged |
| `app/scoring/types.py` | Scoring type definitions | Modify (add StrategySource) |
| `app/scoring/final.py` | score_candidate, combine_scores | Reuse unchanged |
| `app/scoring/direction.py` | Direction scoring | Reuse unchanged (may adjust price_structure) |
| `app/scoring/contract.py` | Contract scoring | Reuse unchanged |
| `app/scoring/confidence.py` | Data confidence | Reuse unchanged |
| `app/scoring/vetoes.py` | Hard vetoes | Reuse unchanged |
| `app/scoring/penalties.py` | Soft penalties | Reuse unchanged |
| `app/pipeline/orchestrator.py` | PipelineOrchestrator | Reuse unchanged |
| `app/pipeline/steps/candidates.py` | CandidateSelectionStep | Reuse unchanged |
| `app/pipeline/steps/scoring.py` | CandidateScoringStep | Reuse unchanged |
| `app/pipeline/steps/decide.py` | LLM decision step | Reuse unchanged |
| `app/llm/router.py` | LLMRouter | Reuse unchanged |
| `app/llm/schemas.py` | DecisionInput, StructuredDecision | Reuse unchanged |

### C. New Files Required

| File | Purpose |
|------|---------|
| `app/services/sector_momentum_service.py` | Strategy 3 implementation |
| `app/services/spring_loaded_service.py` | Strategy 4 implementation |
| `app/services/commodity_momentum_service.py` | Strategy 5 implementation |
| `tests/services/test_sector_momentum_service.py` | Strategy 3 tests |
| `tests/services/test_spring_loaded_service.py` | Strategy 4 tests |
| `tests/services/test_commodity_momentum_service.py` | Strategy 5 tests |
| `tests/pipeline/test_multi_strategy_merge.py` | 5-strategy merge tests |

---

*End of Report*
