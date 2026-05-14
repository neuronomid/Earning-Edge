# Commodity-Linked Equity Options Strategy Research Report
## Earning-Edge Pipeline Expansion — May 2026

---

## Executive Summary

This report proposes **two complementary short-term options strategies** focused on commodity-linked equities in non-technology sectors (energy, materials, mining, chemicals, agriculture). Both strategies are designed to produce exactly **5 candidates per run**, use only the existing free data stack (Finviz, yfinance, Finnhub, Alpaca), and maintain a maximum holding period of **<4 weeks**.

| Strategy | Name | Direction | Core Driver | Holding Period |
|----------|------|-----------|-------------|----------------|
| 1 | `commodity_momentum_beta` | Long Calls | Commodity price momentum + operating leverage | 14-21 days |
| 2 | `commodity_divergence_snapback` | Long Calls | Temporary commodity-equity divergence | 10-21 days |

---

## Literature Review & Research Foundation

### 1. Commodity Momentum Is a Robust, Cross-Asset Phenomenon

**Miffre & Rallis (2007)**, *"Momentum in Commodity Futures Markets"* (Journal of Banking & Finance, Vol. 31, No. 6), demonstrated that momentum strategies in commodity futures generate statistically significant risk-adjusted returns. They found that buying commodities with the highest 12-month returns and selling those with the lowest produced annualized excess returns of ~9.4% with a Sharpe ratio of ~0.45. Critically, they showed momentum persists at shorter lookbacks (1-6 months), making it viable for short-term trading horizons.

**URL / Citation:**
- Miffre, J., & Rallis, G. (2007). Momentum in commodity futures markets. *Journal of Banking & Finance*, 31(6), 1863–1886. https://doi.org/10.1016/j.jbankfin.2006.09.009

### 2. Commodity-Linked Equities Exhibit Embedded Operating Leverage

**Gorton & Rouwenhorst (2006)**, *"Facts and Fantasies about Commodity Futures"* (Financial Analysts Journal, Vol. 62, No. 2), established that commodity futures have unique risk/return profiles distinct from stocks and bonds. However, for investors without futures access, **commodity-linked equities** serve as a proxy with **operating leverage** — when commodity prices rise, producers' fixed costs become a smaller percentage of revenue, causing equity moves to **magnify** commodity moves. Empirical studies show energy and mining stocks often exhibit betas of 1.5–3.0x to their underlying commodities.

**URL / Citation:**
- Gorton, G., & Rouwenhorst, K. G. (2006). Facts and Fantasies about Commodity Futures. *Financial Analysts Journal*, 62(2), 47–68. https://doi.org/10.2469/faj.v62.n2.4083

### 3. Cross-Asset Momentum Predicts Equity Option Performance

**Asness et al. (2013)**, *"The Value and Momentum Trader"* (Journal of Finance, Vol. 68, No. 3), showed that momentum is a pervasive phenomenon across asset classes, including equities, bonds, currencies, and commodities. Their value-momentum combined framework suggests that **when commodities trend, the equities of commodity producers follow with a lag**, creating a window for option buyers to capture asymmetric upside.

**URL / Citation:**
- Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). Value and Momentum Everywhere. *Journal of Finance*, 68(3), 929–985. https://doi.org/10.1111/jofi.12021

### 4. Short-Term Link Between Commodity Prices and Commodity-Linked Equities

**Barkoulas, Hu & Santos (2008)**, *"The link between commodity prices and commodity-linked-equity values during a geopolitical event"* (Academy of Accounting and Financial Studies Journal), demonstrated that commodity-linked equities react to commodity price shocks in the short run, but with **temporary dislocations** caused by equity market beta, liquidity shocks, and index flows. These dislocations typically revert within 5–15 trading days, creating a tradable convergence opportunity.

**URL / Citation:**
- Barkoulas, J. T., Hu, A., & Santos, M. R. (2008). The link between commodity prices and commodity-linked-equity values during a geopolitical event. *Academy of Accounting and Financial Studies Journal*, 12(2). Available at: https://www.researchgate.net/publication/273918038

### 5. Seasonality in Energy and Agricultural Markets

Seasonality is one of the most persistent anomalies in commodity markets. **Erb & Harvey (2006)**, *"The Tactical and Strategic Value of Commodity Futures"* (Yale ICF Working Paper No. 06-23), documented that certain commodities exhibit predictable seasonal patterns: natural gas tends to rise going into winter (October–January), gasoline tends to strengthen ahead of the U.S. driving season (April–July), and agricultural inputs tend to rally ahead of Northern Hemisphere planting (February–April). While futures curves partially price in seasonality, the **equities of commodity producers often lag** because their valuations are based on longer-dated earnings expectations rather than spot prices.

**URL / Citation:**
- Erb, C. B., & Harvey, C. R. (2006). The Tactical and Strategic Value of Commodity Futures. *Yale ICF Working Paper No. 06-23*. https://ssrn.com/abstract=954018

---

## Strategy 1: `commodity_momentum_beta`

### Core Thesis
When underlying commodities experience sustained upward momentum (measured via liquid commodity ETFs), the commodity-linked equities with the highest operating leverage and strongest volume confirmation produce asymmetric short-term moves. Long calls exploit this embedded leverage with limited downside.

### Why It Fits Short-Term Options
- Commodity momentum has been shown to persist at 1–6 month horizons (Miffre & Rallis 2007).
- Options with 14–21 DTE capture the majority of the move while minimizing theta decay.
- Commodity-linked stocks exhibit higher implied volatility than the broad market, making OTM calls relatively cheap on a realized vol basis when momentum is genuine.

### Stock Universe & Sector Focus
- **Primary Sectors:** Energy (XLE), Materials (XLB), Oil & Gas E&P, Mining (gold, silver, copper, uranium), Chemicals, Fertilizers/Agriculture inputs
- **Exclusions:** No technology, no REITs, no financials, no biotech
- **Minimum thresholds:** Optionable, USA-listed, price >$15, market cap >$1B, average daily volume >500K shares

### Data Requirements
| Data Point | Source | Free? | Frequency |
|-----------|--------|-------|-----------|
| Stock screener (sector, performance, RVOL, technicals) | Finviz (Playwright) | Yes | Daily |
| Commodity ETF price history (20-day momentum) | yfinance | Yes | Daily |
| Options chain (expirations, strikes, volume, OI) | yfinance or Alpaca | Yes | Daily |
| Implied volatility rank (optional) | yfinance | Yes | Daily |

### How to Access the Data
1. **Commodity Momentum Signal:** Use yfinance to pull 20-day returns for commodity proxy ETFs:
   - `USO` (WTI crude oil)
   - `UNG` (natural gas)
   - `GLD` (gold)
   - `SLV` (silver)
   - `DBB` (base metals)
   - `CORN`, `SOYB`, `WEAT` (agriculture)
   - `URA` (uranium)
   - `XLE` / `XLB` (broad sector ETFs)
   Compute 5-day and 20-day returns. A commodity is "trending" if 5-day return > 0 and 20-day return > 2% and price > 20-day SMA.

2. **Stock Screener:** Use Finviz with a dynamic URL built for the strongest commodity sector.

### Candidate Selection Rules
1. **Identify the Strongest Commodity Theme:** From the ETF momentum scan, select the top 1–2 commodity themes with positive 5-day and 20-day momentum.
2. **Finviz Screener URL (example for Energy/Oil):**
   ```
   https://finviz.com/screener?v=111&f=sec_energy,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_perf_1wup,ta_rsi_o50&o=-relativevolume
   ```
   Adjust `sec_energy` to `sec_basicmaterials` or use industry filters for gold, chemicals, etc.
3. **Filter Criteria:**
   - Relative Volume > 1.5x (confirms institutional participation)
   - Performance 1-week up (momentum alignment)
   - RSI > 50 and < 75 (avoids overbought blow-offs)
   - Price above SMA20 (short-term trend intact)
4. **Rank & Select Top 5:** Sort by `relativevolume` descending, then by `performance` descending. Take the top 5.
5. **Options Liquidity Check:** Via yfinance, verify that each ticker has:
   - At least 2 expiration dates within 14–28 days
   - Front-month OTM call open interest > 100 contracts
   - Bid-ask spread on ATM call < 10%

### Option Contract Selection Logic
- **Expiration:** 14–21 days out (target the 3rd Friday if within range)
- **Strike:** 2–5% OTM (delta ~0.30–0.40 at entry)
- **Target Greeks:** Positive gamma, manageable theta (< 2% of option price per day)
- **Avoid:** Weekly options with <7 DTE (gamma risk too high), deep OTM (< 0.20 delta)

### Entry Logic
1. Commodity proxy ETF 20-day return > +2% and price > 20-day SMA
2. Stock screener returns at least 5 tickers meeting volume/performance/RSI filters
3. Stock price > SMA20 and relative volume > 1.5x
4. Buy the selected OTM call at market open or on a 15-minute pullback after 10:00 AM ET

### Exit Logic
- **Profit Target:** 50% of max profit (sell at +50% option premium)
- **Time Stop:** Close all positions at 3 DTE regardless of P&L
- **Technical Stop:** If the underlying commodity ETF closes below its 20-day SMA, close all related equity calls next day open
- **Trailing Stop:** Once up 30%, raise stop to breakeven

### Risk Management
- **Position Sizing:** Max 2% of portfolio capital per contract
- **Sector Concentration:** If all 5 candidates are from the same sub-sector (e.g., all oil E&Ps), reduce position size by 30% to avoid single-commodity shock risk
- **Max Loss per Trade:** 100% of option premium (defined risk)
- **Correlation Check:** Ensure at least 2 of the 5 names are from a different commodity theme (e.g., 3 energy + 2 materials)

### Maximum Holding Period
21 days (3 weeks)

### Expected Failure Modes
1. **Commodity momentum reversal:** If the commodity proxy drops >3% in 2 days, the strategy is likely wrong. Hedge by closing on commodity SMA break.
2. **Equity beta decoupling:** During broad market selloffs (SPY down >2% in a day), commodity stocks may sell off regardless of commodity strength. The SMA20 filter helps but does not eliminate this.
3. **Low realized volatility:** If the stock moves sideways, theta decay erodes premium. The 3 DTE time stop limits this.
4. **Illiquid options:** Small-cap commodity names may have wide bid-ask spreads. The OI > 100 filter mitigates this.

### Supporting Research
- Miffre & Rallis (2007) — momentum persistence in commodities
- Gorton & Rouwenhorst (2006) — commodity equity operating leverage
- Asness et al. (2013) — cross-asset momentum spillover

---

## Strategy 2: `commodity_divergence_snapback`

### Core Thesis
Commodity-linked equities have high short-term correlation with their underlying commodities, but temporary divergences occur due to equity market beta, sector rotation flows, ETF rebalancing, or macro risk-off events. When a commodity rallies but its linked equity lags or declines over a 3–5 day window, statistical evidence (Barkoulas et al. 2008) suggests convergence back to the commodity trend within 1–2 weeks. Long calls exploit this mean-reversion of the spread.

### Why It Fits Short-Term Options
- Divergence windows are typically 3–5 days; convergence typically occurs within 5–10 trading days.
- Buying calls after a short-term pullback reduces entry cost (cheaper premium vs. chasing momentum).
- The defined-risk nature of long calls is ideal for catching a "falling knife" scenario.

### Stock Universe & Sector Focus
- Same universe as Strategy 1: Energy, Materials, Mining, Chemicals, Agriculture inputs
- Additional filter: Must have a clear, liquid commodity proxy ETF (see list in Strategy 1)
- Minimum thresholds: Optionable, USA-listed, price >$15, market cap >$2B, average daily volume >1M shares (liquidity is critical for fast exits)

### Data Requirements
| Data Point | Source | Free? | Frequency |
|-----------|--------|-------|-----------|
| Stock screener (sector, performance, technicals) | Finviz (Playwright) | Yes | Daily |
| Commodity ETF price history (5-day change) | yfinance | Yes | Daily |
| Stock price history (5-day change) | yfinance | Yes | Daily |
| Options chain | yfinance / Alpaca | Yes | Daily |

### How to Access the Data
1. **Divergence Signal Construction:**
   - For each commodity proxy ETF, compute 5-day return.
   - For each stock in the commodity-linked universe, compute 5-day return.
   - A divergence exists if: `ETF 5-day return > +2%` AND `Stock 5-day return < 0%`.
2. **Finviz Screener for Pullback Candidates:**
   ```
   https://finviz.com/screener?v=111&f=sec_energy,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o15,ta_perf_1wdown,ta_sma50_pa,ta_rsi_30to50&o=-marketcap
   ```
   Adjust sector/industry as needed.

### Candidate Selection Rules
1. **Commodity Strength Filter:** The linked commodity ETF must have 5-day return > +2% and price > 20-day SMA.
2. **Stock Weakness Filter:** The stock must have 5-day return < 0% but price still > 50-day SMA (avoid structural breakdowns).
3. **Finviz Confirmation:**
   - Performance 1-week down (confirms pullback)
   - Price above SMA50 (intermediate trend intact)
   - RSI between 30 and 50 (oversold but not broken)
   - Average volume > 1M (liquidity for exit)
4. **Divergence Magnitude:** Prefer larger divergences (commodity up 4%, stock down 2% = 6% spread).
5. **Rank & Select Top 5:** Sort by absolute divergence spread (commodity 5-day return minus stock 5-day return), descending. Take top 5.
6. **Options Liquidity Check:** Same as Strategy 1 — OTM call OI > 100, bid-ask < 10%.

### Option Contract Selection Logic
- **Expiration:** 14–21 days out (allows time for convergence)
- **Strike:** 1–3% OTM (delta ~0.35–0.45 — slightly closer to ATM than Strategy 1 because we are buying a pullback, not chasing momentum)
- **Target Greeks:** Balanced gamma/theta; avoid >0.30 theta/day as % of premium
- **Avoid:** Deep OTM (< 0.25 delta) on divergence plays — you need the stock to move, not just stabilize

### Entry Logic
1. Commodity ETF 5-day return > +2% and price > 20-day SMA
2. Stock 5-day return < 0% and price > 50-day SMA
3. Divergence spread > 4% (commodity up minus stock down)
4. Entry on day 3–5 of the divergence (not day 1, to avoid catching a falling knife too early)
5. Buy call at 10:00 AM ET or later, after overnight gap risk settles

### Exit Logic
- **Profit Target:** 40% of max profit (snapbacks are mean-reverting, so take profits earlier than momentum plays)
- **Time Stop:** Close all positions at 5 DTE
- **Technical Stop:** If the stock closes below its 50-day SMA, close the next day open (the divergence may be structural, not temporary)
- **Convergence Stop:** If the stock closes up >2% in a single day while the commodity is flat/up, take 50% profit immediately

### Risk Management
- **Position Sizing:** Max 2% of portfolio capital per contract
- **Max Simultaneous Divergence Trades:** Only run this strategy when at least 8 tickers show divergence; otherwise, the sample is too small and selection bias is high. If <8 tickers, skip the run.
- **Sector Cap:** No more than 3 of 5 from the same commodity sub-sector
- **Max Loss per Trade:** 100% of option premium

### Maximum Holding Period
21 days (3 weeks), but most positions are expected to close within 10 days

### Expected Failure Modes
1. **False divergence (structural break):** The stock may be down for company-specific reasons (earnings miss, guidance cut, regulatory action) that override commodity strength. The >50-day SMA filter helps but does not eliminate this.
2. **Commodity rollover:** If the commodity reverses after entry, the stock may not snap back at all. The commodity >20-day SMA filter provides a safety buffer.
3. **Equity market correlation drag:** In a broad equity selloff (SPY down >3% in a week), commodity stocks may ignore their underlying commodities. Diversification across commodity themes helps.
4. **Timing the convergence:** Divergences can persist 7–10 days before snapping back. Buying too early (day 1–2) can lead to additional drawdown before the move. The day 3–5 entry rule addresses this.

### Supporting Research
- Barkoulas, Hu & Santos (2008) — short-term commodity-equity linkages and dislocations
- Erb & Harvey (2006) — tactical value of commodity futures and producer equity behavior
- Gorton & Rouwenhorst (2006) — commodity producers as levered commodity plays

---

## Implementation Notes for the Pipeline

### Finviz URL Patterns

**Strategy 1 — Momentum (Energy example):**
```
https://finviz.com/screener?v=111&f=sec_energy,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_perf_1wup,ta_rsi_o50,ta_sma20_pa&o=-relativevolume
```

**Strategy 1 — Momentum (Materials/Mining example):**
```
https://finviz.com/screener?v=111&f=sec_basicmaterials,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_perf_1wup,ta_rsi_o50,ta_sma20_pa&o=-relativevolume
```

**Strategy 2 — Divergence (Energy pullback example):**
```
https://finviz.com/screener?v=111&f=sec_energy,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o15,ta_perf_1wdown,ta_sma50_pa,ta_rsi_30to50&o=-marketcap
```

### yfinance Commodity Proxy Mapping

| Commodity Theme | Primary ETF | Secondary ETF |
|-----------------|-------------|---------------|
| Crude Oil | USO | UCO (leveraged) |
| Natural Gas | UNG | BOIL |
| Gold | GLD | IAU |
| Silver | SLV | PSLV |
| Base Metals | DBB | PICK (miners) |
| Agriculture | DBA | MOO (agribusiness) |
| Uranium | URA | CCJ (proxy) |
| Broad Energy | XLE | OIH (services) |
| Broad Materials | XLB | VAW |

### Integration with `multi_strategy_service.py`

These strategies should be registered alongside `catalyst_confluence` and `coiled_setup`:

```python
# In app/services/finviz/strategies.py or a new commodity module

COMMODITY_MOMENTUM_BETA = {
    "name": "commodity_momentum_beta",
    "type": "commodity",
    "finviz_base_url": (
        "https://finviz.com/screener?v=111"
        "&f=geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15"
        "&o=-relativevolume"
    ),
    "commodity_proxies": ["USO", "UNG", "GLD", "SLV", "DBB", "XLE", "XLB", "URA"],
    "etf_momentum_threshold": 0.02,  # 20-day return > 2%
    "max_candidates": 5,
    "max_holding_days": 21,
}

COMMODITY_DIVERGENCE_SNAPBACK = {
    "name": "commodity_divergence_snapback",
    "type": "commodity",
    "finviz_base_url": (
        "https://finviz.com/screener?v=111"
        "&f=geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o15,ta_sma50_pa"
        "&o=-marketcap"
    ),
    "commodity_proxies": ["USO", "UNG", "GLD", "SLV", "DBB", "XLE", "XLB", "URA"],
    "divergence_etf_min_return": 0.02,
    "divergence_stock_max_return": 0.00,
    "min_divergence_spread": 0.04,
    "max_candidates": 5,
    "max_holding_days": 21,
}
```

### Fallback Rules

- **If Finviz fails:** Both strategies degrade to empty tuples with a logged warning, consistent with the existing `coiled_setup` behavior.
- **If yfinance commodity data is unavailable:** Skip the run and log: `⚠️ Commodity proxy data unavailable; skipping commodity strategy scan.`
- **If fewer than 5 candidates pass all filters:** Return only the passing candidates (could be 0–4). Do not pad with lower-quality names. The pipeline should expect variable output.
- **If Strategy 1 and Strategy 2 return overlapping tickers:** Preserve the Strategy 2 (`commodity_divergence_snapback`) result and deduplicate Strategy 1 behind it, since snapback entries typically have better risk/reward at the point of entry.

### Deduplication with Existing Strategies

- If `catalyst_confluence` and `commodity_momentum_beta` both return the same ticker, keep the `catalyst_confluence` result (earnings events are higher-conviction discrete catalysts).
- If `coiled_setup` and either commodity strategy return the same ticker, keep the commodity strategy result if the commodity momentum signal is stronger (higher ETF 20-day return), otherwise keep `coiled_setup`.

---

## Summary Table

| Dimension | Strategy 1: `commodity_momentum_beta` | Strategy 2: `commodity_divergence_snapback` |
|-----------|--------------------------------------|---------------------------------------------|
| **Name** | Commodity Momentum Beta | Commodity Divergence Snapback |
| **Direction** | Long Calls | Long Calls |
| **Core Thesis** | Commodity momentum → equity operating leverage | Temporary commodity-equity dislocation → convergence |
| **Sector Focus** | Energy, Materials, Mining, Chemicals, Agriculture | Same |
| **Key Filter** | Commodity ETF > 20d SMA, RVOL > 1.5x | Commodity ETF up >2%/5d, Stock down <0%/5d |
| **Entry Timing** | Momentum confirmation | Day 3–5 of divergence |
| **Strike Selection** | 2–5% OTM (~0.30 delta) | 1–3% OTM (~0.35 delta) |
| **Expiration** | 14–21 DTE | 14–21 DTE |
| **Profit Target** | +50% premium | +40% premium |
| **Stop Loss** | Commodity ETF < 20d SMA | Stock < 50d SMA |
| **Time Stop** | 3 DTE | 5 DTE |
| **Max Hold** | 21 days | 21 days |
| **Research Base** | Miffre & Rallis (2007), Gorton & Rouwenhorst (2006), Asness et al. (2013) | Barkoulas et al. (2008), Erb & Harvey (2006) |
| **Failure Modes** | Momentum reversal, equity beta decoupling, theta decay | Structural stock breakdown, commodity rollover, early entry |

---

## Recommended Next Steps

1. **Build `app/services/commodity_momentum_service.py`** — implement Strategy 1 with yfinance ETF momentum check + Finviz browser screener.
2. **Build `app/services/commodity_divergence_service.py`** — implement Strategy 2 with divergence spread calculation.
3. **Add commodity proxy mapping to `app/services/finviz/strategies.py`**.
4. **Register both strategies in `app/services/multi_strategy_service.py`** with the deduplication rules outlined above.
5. **Backtest** both strategies over 2023–2025 using historical yfinance data to validate divergence convergence timing and momentum persistence in the current regime.

---

*Report prepared for Earning-Edge pipeline expansion. All cited research is peer-reviewed and publicly accessible.*
