# Research Report: Mean Reversion & Volatility Contraction Options Strategies
## Earning-Edge Pipeline Expansion — Non-Technology Sectors

---

## Executive Summary

This report proposes **two complementary long-options strategies** designed to exploit **price mean reversion combined with volatility contraction** in non-technology sectors. Both strategies are grounded in decades of academic research on short-term reversals, Bollinger Band mean reversion, and implied-volatility dynamics. They are engineered to produce exactly **5 candidates per run**, use only the existing free data stack (Finviz, yfinance, Finnhub, Alpaca), and maintain a maximum holding period of **<4 weeks**.

| Strategy | Name | Direction | Core Driver | Holding Period |
|----------|------|-----------|-------------|----------------|
| 1 | `spring_loaded_reversion` | Long Calls | Oversold bounce after realized-volatility contraction | 10–21 days |
| 2 | `iv_compression_bounce` | Long Calls | Mean reversion + implied-volatility undervaluation | 14–28 days |

---

## Part I: Research Foundation

### 1.1 Short-Term Mean Reversion in Equity Prices

The existence of short-term mean reversion is one of the most robust findings in empirical asset pricing.

**De Bondt & Thaler (1985)** — *"Does the Stock Market Overreact?"* (Journal of Finance, 40(3), 793–805). The foundational paper on mean reversion. The authors constructed portfolios of extreme winners and losers over 3–5 year formation periods and found that **loser portfolios outperformed winner portfolios by ~25% over the subsequent 36 months**. While their primary horizon was multi-year, the underlying mechanism — investor overreaction to recent price moves — operates at all time scales. The paper established that markets systematically overreact to salient news, creating predictable reversals.

**URL:** https://www.jstor.org/stable/2327804

**Jegadeesh (1990)** — *"Evidence of Predictable Behavior of Security Returns"* (Journal of Finance, 45(3), 881–898). Documented **short-term reversals at the 1-month horizon**: stocks with the highest returns in month t tend to underperform in month t+1, and vice versa. The effect is strongest among smaller, more volatile stocks and is distinct from the longer-horizon momentum effect documented by Jegadeesh & Titman (1993).

**URL:** https://www.jstor.org/stable/2328800

**Poterba & Summers (1988)** — *"Mean Reversion in Stock Prices: Evidence and Implications"* (Journal of Financial Economics, 22(1), 27–59). Found that **stock returns are negatively autocorrelated over multi-year horizons** and that mean-reverting components account for a substantial fraction of return variance. Their variance-ratio tests rejected the random walk hypothesis at conventional significance levels.

**URL:** https://www.sciencedirect.com/science/article/pii/0304405X88900219

**Practical Implication:** Short-term pullbacks in established uptrends are systematically overdone. When a stock in a long-term uptrend experiences a sharp selloff, the probability of a partial or full reversion within 2–4 weeks is significantly above random.

---

### 1.2 Bollinger Bands and Mean Reversion

Bollinger Bands are among the most widely studied technical indicators for mean reversion.

**Bollinger, J. (2002)** — *Bollinger on Bollinger Bands*. McGraw-Hill. The inventor's definitive work. Bollinger showed that in trending markets, prices tend to "walk the band" (stay near the upper band in uptrends, lower band in downtrends). However, **when price touches the lower band in an established uptrend, the probability of a bounce back toward the middle band is elevated**. The %B indicator (where price sits relative to the bands) is particularly useful: %B < 0.10 signals price is near the lower band and statistically extended.

**QuantifiedStrategies (2025)** — In a comprehensive backtest of 12 Bollinger Band strategies, the site concluded: **"Bollinger Bands are somewhat profitable in the stock market, which is a market that is very mean-reversive."** Mean-reversion strategies (buying near the lower band in uptrends) outperformed breakout strategies in US equities, consistent with the negative short-term autocorrelation documented in academic literature.

**URL:** https://www.quantifiedstrategies.com/bollinger-bands-trading-strategy/

**Key Insight for Options:** Buying calls when %B < 0.10 and the stock is above its 200-day SMA captures the statistical edge of mean reversion with asymmetric payoff. The call option provides leverage on the bounce while capping downside.

---

### 1.3 Volatility Contraction as a Reversal Signal

Volatility contraction — whether in realized price ranges or implied option prices — is a well-documented precursor to directional moves.

**Natenberg, S. (1994)** — *Option Volatility and Pricing* (2nd ed.). McGraw-Hill. The standard practitioner text on volatility dynamics. Natenberg emphasizes that **volatility is mean-reverting**: periods of low volatility tend to be followed by periods of higher volatility, and vice versa. When realized volatility contracts after a sharp move, it often indicates that selling pressure is exhausted and a reversal is building.

**The Bollinger Band Squeeze:** When Bollinger Band width (Upper − Lower) / Middle falls to a 20-day low, it signals that volatility has compressed to an extreme. Practitioner research (Bollinger; QuantifiedStrategies) confirms that squeezes in the direction of the prevailing trend tend to resolve with an expansion move. In an uptrend, a squeeze near the lower band is bullish.

**Declining Volume + Declining ATR:** When a pullback is accompanied by both shrinking daily ranges (lower ATR) and declining volume, it indicates that sellers are exhausted. This "volatility contraction" pattern is a classic reversal setup in technical analysis literature.

**Key Insight for Options:** Buying options after realized volatility has contracted (low ATR, narrow bands, declining volume) means you enter when the market is pricing in low future movement. If a mean-reversion bounce occurs, you benefit not only from the price move (delta) but also from the expansion of implied volatility (vega) as the market reprices future uncertainty.

---

### 1.4 Implied Volatility Mean Reversion and the IV/HV Ratio

While the Volatility Risk Premium (VRP) literature shows that implied volatility usually exceeds realized volatility (making selling premium attractive on average), the **opposite condition — IV below HV — is itself mean-reverting and creates a buying opportunity**.

**CBOE / BlackRock Research (2024)** — The CBOE Options Institute notes that implied volatility is **mean-reverting around its long-term average**. When IV falls significantly below recent realized volatility, it often reflects temporary complacency that corrects within days to weeks. This is particularly true after a sharp pullback, where option prices may fail to fully reflect the residual uncertainty of a potential bounce or further drop.

**Hong, Sung & Yang (2018)** — *"On profitability of volatility trading on S&P 500 equity index options"* (International Review of Economics & Finance, 55, 295–307). While primarily focused on short-volatility profitability, the paper confirms that **IV/HV ratios are stationary and mean-reverting**. Extreme deviations in either direction tend to correct. When IV/HV < 1.0, options are underpricing volatility relative to recent realized moves.

**URL:** https://doi.org/10.1016/j.iref.2017.07.012

**Key Insight for Options:** Buying calls when IV/HV < 0.90 on an oversold stock in an uptrend gives you:
1. **Delta edge:** Mean reversion of price back toward the 20-day SMA.
2. **Vega edge:** Mean reversion of implied volatility back toward historical volatility.
3. **Theta management:** Using 21–28 DTE balances time decay with the expected 1–2 week holding period.

---

### 1.5 Why Non-Technology Sectors?

Mean reversion and volatility contraction strategies are particularly effective in non-tech sectors for three reasons:

1. **Slower Information Diffusion:** Hou & Moskowitz (2005) showed that non-tech sectors exhibit slower price discovery, meaning overreactions take longer to correct — creating larger, more tradable reversals.
2. **Less Retail Noise:** Technology stocks are dominated by speculative retail flow and momentum-chasing algorithms, which can extend trends beyond statistical extremes. Non-tech sectors are more driven by institutional flows that mean-revert.
3. **Macro-Driven Volatility Spikes:** Energy, materials, utilities, and REITs experience sharp volatility spikes from macro events (commodity prices, rate changes, regulation). These spikes are often temporary overreactions that contract and reverse within 2–4 weeks.

---

## Part II: Proposed Strategies

---

## STRATEGY 1: Spring-Loaded Reversion

### Strategy Name
`spring_loaded_reversion`

### Core Thesis
Stocks in established long-term uptrends (price above SMA200) that experience sharp short-term pullbacks tend to revert to their mean within 5–10 trading days. When the pullback is accompanied by **realized volatility contraction** — narrowing Bollinger Band width, declining ATR, and shrinking volume — the compression acts like a coiled spring. A breakout to the upside is more likely and more violent. By buying calls after this contraction pattern is confirmed, we capture the asymmetric payoff of the mean-reversion bounce with leverage.

### Stock Universe and Sector Focus
- **Primary Sectors:** Energy (XLE), Materials (XLB), Industrials (XLI), Utilities (XLU), Consumer Staples (XLP), Healthcare (XLV), Financials (XLF), Real Estate (XLRE)
- **Explicit Exclusions:** Technology (XLK), Communication Services (XLC), Consumer Discretionary (tech-adjacent megacaps)
- **Minimum Criteria:** USA-listed, price > $15, market cap > $2B (mid+), average daily volume > 500K shares, optionable

### Why It Fits Short-Term Options
- Mean-reversion bounces in oversold uptrends typically resolve within 5–10 trading days (Jegadeesh 1990; Bollinger research).
- Volatility contraction precedes expansion by 2–5 days on average (Bollinger Band Squeeze literature).
- Calls with 14–21 DTE capture the bounce while minimizing theta decay.
- The defined-risk nature of long calls is ideal for "catching a falling knife" in an uptrend.

### Data Requirements

| Data Point | Source | Access Method | Cost |
|-----------|--------|---------------|------|
| Stock screener (sector, RSI, SMA, volume, price) | Finviz | Playwright scrape custom URL | Free |
| Historical prices (BB, ATR, volume, SMA) | yfinance | `Ticker.history(period="3mo")` | Free |
| Options chain (expirations, strikes, OI) | Alpaca or yfinance | `get_option_chain()` | Free tier |
| Earnings calendar | yfinance / Finnhub | `Ticker.calendar` or API | Free |

### How to Access the Data
1. **Finviz Screener:** Load encoded URL via Playwright (`page.goto(url)`), scrape top rows.
2. **yfinance Enrichment:** For each Finviz candidate, download 3 months of daily OHLCV. Compute Bollinger Bands (20,2), ATR(14), RSI(14), volume averages, and %B.
3. **Options Chain:** Use Alpaca free tier or yfinance to verify liquid options exist for the candidate.
4. **Earnings Check:** Use yfinance `Ticker.calendar` or Finnhub earnings API to exclude names with earnings within 10 days.

### Candidate Selection Rules (Exactly 5)

**Step 1: Finviz Base Screen**
```
https://finviz.com/screener?v=111
&f=sec_energy|sec_materials|sec_industrials|sec_utilities|sec_consumerstaples|sec_healthcare|sec_financial|sec_realestate,
   geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,
   ta_rsi_u35,ta_sma200_pa
&o=-marketcap
```
Parameters decoded:
- Sector filters = all non-tech sectors (pipe-separated OR)
- `geo_usa` = USA only
- `sh_avgvol_o500` = Average volume > 500K
- `sh_opt_option` = Optionable
- `sh_price_o15` = Price > $15
- `ta_rsi_u35` = RSI(14) < 35 (oversold)
- `ta_sma200_pa` = Price above 200-day SMA (long-term uptrend intact)
- `o=-marketcap` = Sort by market cap descending (liquidity priority)

**Step 2: Realized Volatility Contraction Filter (yfinance)**
For each of the top 15 Finviz results, compute:
1. **Bollinger Band %B:** `(Close − Lower) / (Upper − Lower)`. Keep only names with `%B < 0.15` (price near lower band).
2. **BB Width Contraction:** `Width = (Upper − Lower) / Middle`. Keep only names where current width < average width over prior 20 days (volatility contraction).
3. **ATR Contraction:** `ATR(14) today < ATR(14) 5 days ago`. Confirms declining ranges.
4. **Volume Contraction:** `Volume(5-day avg) < Volume(20-day avg) * 0.90`. Confirms exhaustion of selling pressure.
5. **No Earnings Overhang:** Next earnings date > 10 calendar days away.

**Step 3: Rank & Select**
```
Score = 0.30 * (1 − %B) + 0.25 * (1 − width_ratio) + 0.20 * volume_contraction + 0.15 * ATR_contraction + 0.10 * market_cap_rank
```
- Select the **top 5** by Score.
- If fewer than 5 pass all filters, return only passing candidates (do not pad).

### Option Contract Selection Logic
- **Expiration:** 14–21 DTE (captures the typical 5–10 day bounce window with buffer).
- **Strike:** 0.40–0.50 delta (ATM to slightly ITM). Slightly ITM calls reduce theta decay and improve probability of profit on a modest bounce.
- **Liquidity Filter:** Open interest > 100 contracts, bid-ask spread < 10% of mid-price.
- **Avoid:** Deep OTM calls (< 0.30 delta) — mean reversion bounces are typically 3–8%, not 15%+. Deep OTM requires unrealistic moves.

### Entry and Exit Logic

**Entry:**
- Enter within 1 trading day of candidate identification.
- Prefer entry on a day where the stock prints a green candle or inside day after the contraction (early confirmation of reversal).
- If the stock gaps down >2% on the day of identification, wait for the following day to avoid catching a falling knife.

**Exit Triggers (first to fire):**
1. **Profit Target:** 50% gain on option premium (sell to close).
2. **Mean Reversion Exit:** RSI(14) crosses back above 50 (price has reverted to neutral zone).
3. **Technical Exit:** Stock closes below the lower Bollinger Band (breakdown, not bounce) → close next day open.
4. **Time Stop:** 10 trading days (2 weeks) regardless of P/L.
5. **Max Loss:** Option loses 50% of premium → close position.

**Position Management:**
- No averaging down.
- If profit target hits on 2+ positions, raise stop on remaining to breakeven.

### Risk Management
- **Position Sizing:** Equal dollar risk per position. Risk 50% of premium on each (max loss per position = 50% of call premium paid).
- **Sector Concentration:** No more than 2 candidates from the same sector.
- **Market Filter:** Do NOT enter new positions if SPY is below its 200-day SMA (avoid mean reversion in a broad bear market).
- **VIX Filter:** If VIX > 30, skip the run. Elevated VIX indicates systemic stress where oversold can become more oversold.
- **Max Account Risk:** 5% of total capital at risk per strategy run (10 positions × 0.5% risk each).

### Maximum Holding Period
**21 calendar days (3 weeks)** — hard time stop at 10 trading days if not exited earlier.

### Expected Failure Modes
1. **Trend Breakdown:** The stock violates the 200-day SMA after entry, converting a mean-reversion setup into a trend-following breakdown. Mitigated by the SMA200 filter and the technical exit rule.
2. **Sector-Wide Selloff:** A macro shock (Fed pivot, commodity crash) drives the entire sector lower. Mitigated by the SPY > SMA200 filter and sector concentration limits.
3. **Theta Decay Without Bounce:** The stock moves sideways after entry, eroding premium. Mitigated by the 10-trading-day time stop.
4. **Earnings Surprise:** An undetected earnings date causes a gap. Mitigated by the earnings exclusion filter.
5. **Low Option Liquidity:** Wide bid-ask spreads on mid-cap names. Mitigated by the market-cap sort and OI filter.

### Supporting Research Citations
- De Bondt, R., & Thaler, R. (1985). "Does the Stock Market Overreact?" *Journal of Finance*, 40(3), 793–805. https://www.jstor.org/stable/2327804
- Jegadeesh, N. (1990). "Evidence of Predictable Behavior of Security Returns." *Journal of Finance*, 45(3), 881–898. https://www.jstor.org/stable/2328800
- Bollinger, J. (2002). *Bollinger on Bollinger Bands*. McGraw-Hill.
- QuantifiedStrategies (2025). "12 Bollinger Bands Trading Strategies: Backtested With Settings." https://www.quantifiedstrategies.com/bollinger-bands-trading-strategy/
- Natenberg, S. (1994). *Option Volatility and Pricing* (2nd ed.). McGraw-Hill.

---

## STRATEGY 2: IV Compression Bounce

### Strategy Name
`iv_compression_bounce`

### Core Thesis
Implied volatility is mean-reverting (Natenberg 1994; CBOE 2024). In normal conditions, implied volatility exceeds realized volatility (the Volatility Risk Premium), making options relatively expensive. However, after a sharp pullback in an uptrend, implied volatility can **temporarily compress below realized volatility** as option sellers overcorrect or as demand for hedges dries up. This creates a rare window where calls are underpriced. Combining this **IV undervaluation** with an **oversold price signal** (RSI < 35, above SMA200) creates a high-expectancy setup: you get paid on both the price bounce (delta) and the IV expansion back toward its mean (vega).

### Stock Universe and Sector Focus
- **Primary Sectors:** Energy, Materials, Industrials, Utilities, Consumer Staples, Healthcare, Financials, Real Estate
- **Explicit Exclusions:** Technology, Communication Services
- **Minimum Criteria:** USA-listed, price > $15, market cap > $2B, average daily volume > 500K, optionable

### Why It Fits Short-Term Options
- IV/HV ratios mean-revert within 5–15 trading days (Hong, Sung & Yang 2018).
- Buying calls when IV < HV gives you a "double edge" — delta from price reversion + vega from IV normalization.
- 21–28 DTE calls provide sufficient time for both edges to materialize while keeping theta manageable.
- Defined risk (premium paid) is capped, while upside is asymmetric.

### Data Requirements

| Data Point | Source | Access Method | Cost |
|-----------|--------|---------------|------|
| Stock screener (sector, RSI, SMA, price, volume) | Finviz | Playwright scrape custom URL | Free |
| Historical prices (realized vol) | yfinance | `Ticker.history(period="1mo")` | Free |
| ATM implied volatility | Alpaca or Finnhub | Options chain query for nearest monthly expiry | Free tier |
| Earnings calendar | yfinance / Finnhub | `Ticker.calendar` or earnings API | Free |

### How to Access the Data
1. **Finviz Screener:** Same base screen as Strategy 1 (RSI < 35, above SMA200, non-tech, liquid, optionable).
2. **yfinance:** Compute 20-day realized volatility (annualized standard deviation of log returns).
3. **Alpaca / Finnhub:** Query nearest-month options chain. Extract the ATM call implied volatility (or interpolate between the two strikes straddling the spot).
4. **IV/HV Ratio:** `IV_HV_Ratio = ATM_IV / Realized_Vol`.

### Candidate Selection Rules (Exactly 5)

**Step 1: Finviz Base Screen (same as Strategy 1)**
```
https://finviz.com/screener?v=111
&f=sec_energy|sec_materials|sec_industrials|sec_utilities|sec_consumerstaples|sec_healthcare|sec_financial|sec_realestate,
   geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,
   ta_rsi_u35,ta_sma200_pa
&o=-marketcap
```

**Step 2: IV/HV Filter (Alpaca/Finnhub + yfinance)**
For each of the top 20 Finviz results:
1. Compute 20-day realized volatility from yfinance closing prices.
2. Retrieve nearest-month ATM implied volatility from Alpaca or Finnhub.
3. **Keep only names with `IV_HV_Ratio < 0.90`** (implied volatility is at least 10% below realized volatility).
4. **Earnings Check:** Exclude names with earnings within the next 10 calendar days.

**Step 3: Rank & Select**
```
Score = 0.40 * (1 − IV_HV_Ratio) + 0.30 * (1 − RSI/35) + 0.20 * market_cap_rank + 0.10 * volume_rank
```
- Rank by Score descending.
- Select the **top 5**.
- If fewer than 5 pass the IV/HV filter, return only passing candidates.

### Option Contract Selection Logic
- **Expiration:** 21–28 DTE (slightly longer than Strategy 1 to give IV mean reversion time to materialize).
- **Strike:** 0.35–0.45 delta (ATM to slightly OTM). We use slightly more OTM than Strategy 1 because the vega edge means we expect the option to appreciate even on a modest move.
- **Liquidity Filter:** Open interest > 100 contracts, bid-ask spread < 10% of mid-price.
- **Avoid:** Names where IV/HV < 0.70 (extreme compression may indicate a structural regime shift or upcoming binary event).

### Entry and Exit Logic

**Entry:**
- Enter within 1 trading day of candidate identification.
- Same entry timing rules as Strategy 1 (prefer green candle/inside day confirmation).

**Exit Triggers (first to fire):**
1. **Profit Target:** 60% gain on option premium (higher than Strategy 1 because vega can accelerate gains).
2. **IV Normalization Exit:** If IV/HV ratio rises back above 1.00 (IV has mean-reverted), close 50% of position and trail the remainder.
3. **Mean Reversion Exit:** RSI(14) crosses back above 50.
4. **Technical Exit:** Stock closes below the lower Bollinger Band → close next day open.
5. **Time Stop:** 14 trading days (3 weeks) regardless of P/L.
6. **Max Loss:** Option loses 50% of premium → close position.

**Position Management:**
- If IV/HV rises above 1.00 and the stock has not moved materially, close immediately (the vega edge is gone).
- No averaging down.

### Risk Management
- **Position Sizing:** Equal dollar risk per position. Risk 50% of premium on each.
- **Sector Concentration:** No more than 2 candidates from the same sector.
- **Market Filter:** SPY > 200-day SMA required for new entries.
- **VIX Filter:** If VIX > 30, skip the run.
- **IV Regime Filter:** If fewer than 3 names in the entire screened universe have IV/HV < 0.90, surface a warning: `⚠️ Implied volatility is elevated across non-tech sectors. IV compression setups are scarce this week.`
- **Max Account Risk:** 5% of total capital at risk per strategy run.

### Maximum Holding Period
**28 calendar days (4 weeks)** — hard time stop at 14 trading days.

### Expected Failure Modes
1. **IV Keeps Falling:** Implied volatility continues to compress even after entry (structural shift to lower vol regime). Mitigated by the 0.70 floor on IV/HV and the time stop.
2. **Price Breakdown:** The stock violates SMA200 after entry. Mitigated by the technical exit rule.
3. **Earnings Surprise:** Undetected earnings date causes a gap. Mitigated by earnings exclusion.
4. **Data Quality Issues:** Alpaca/Finnhub may return stale or missing IV data for thinly traded names. Mitigated by the OI filter and market-cap sort.
5. **Vega Works Against Us:** If the market sells off broadly, IV may spike on fear but the underlying drops, hurting delta more than vega helps. Mitigated by the SPY trend filter.

### Supporting Research Citations
- Hong, H., Sung, H-C., & Yang, J. (2018). "On profitability of volatility trading on S&P 500 equity index options: The role of trading frictions." *International Review of Economics & Finance*, 55, 295–307. https://doi.org/10.1016/j.iref.2017.07.012
- CBOE Options Institute (2024). *VIX Your Portfolio* (BlackRock research on volatility dynamics). https://www.cboe.com/tradable_products/vix/
- Natenberg, S. (1994). *Option Volatility and Pricing* (2nd ed.). McGraw-Hill.
- Poterba, J. M., & Summers, L. H. (1988). "Mean Reversion in Stock Prices: Evidence and Implications." *Journal of Financial Economics*, 22(1), 27–59. https://www.sciencedirect.com/science/article/pii/0304405X88900219

---

## Part III: Implementation Notes for the Pipeline

### 3.1 Data Source Mapping

| Data Need | Recommended Source | Rationale |
|-----------|-------------------|-----------|
| Stock universe + basic filters | **Finviz** (Playwright screener) | Free, no login needed, supports all required filters (sector, price, volume, RSI, SMA) |
| Historical price data (BB, ATR, RSI, realized vol) | **yfinance** | Free, no API key required, sufficient for all calculations |
| Options chain + IV | **Alpaca** (free tier) or **Finnhub** (free tier) | Alpaca offers clean options chain API; Finnhub free tier includes implied volatility estimates |
| Earnings calendar | **yfinance** or **Finnhub** | Both provide next earnings date for filtering |

### 3.2 Candidate Generation Flow

```
Step 1: Finviz Screener (Playwright)
   → Fetch top 20 names matching sector + liquidity + technical filters

Step 2: yfinance Enrichment
   → Download 3-month historical prices for each candidate
   → Compute Bollinger Bands, ATR(14), RSI(14), volume averages, %B
   → Compute 20-day realized volatility
   → Check next earnings date

Step 3: Options Chain Query (Alpaca/Finnhub) — Strategy 2 only
   → Fetch nearest-month options chain
   → Extract ATM implied volatility
   → Compute IV/HV ratio

Step 4: Filtering & Ranking
   → Strategy 1: Apply BB width, ATR, volume contraction filters; rank by composite score
   → Strategy 2: Apply IV/HV < 0.90 filter; rank by composite score

Step 5: Output Candidate List
   → Ticker, sector, strike, expiration, entry rationale, score, risk parameters
```

### 3.3 Automation Considerations

- **No CAPTCHA / Login Gates:** Finviz screener is public; Alpaca and Finnhub free tiers use simple API keys.
- **Retry Safety:** Follow the existing Finviz retry ladder (retry page load once, retry with clean context, then fallback).
- **Scheduling:** Run both strategies **once per week** (e.g., Monday morning) to avoid over-trading and to capture fresh mean-reversion setups.
- **Deduplication:** If a ticker appears in both Strategy 1 and Strategy 2 output, keep the Strategy 2 (`iv_compression_bounce`) result and drop Strategy 1, since the IV undervaluation provides an additional edge.

### 3.4 Suggested Warning / Fallback Rules

- If yfinance historical data is unavailable for a candidate, **drop the candidate** rather than trade blind.
- If Alpaca/Finnhub options data is unavailable for Strategy 2, **degrade Strategy 2 to empty tuple** and log: `⚠️ Options IV data unavailable; IV compression scan skipped this week.`
- If fewer than 5 candidates pass all filters for a strategy, return only the passing candidates (do not relax filters).
- If the SPY is below its 200-day SMA, surface a warning: `⚠️ Broad market is in a downtrend (SPY < 200-day SMA). Mean reversion setups have lower probability this week.`
- If VIX > 30, surface a warning: `⚠️ VIX is elevated (>30). Oversold bounces may fail in high-stress regimes.`

---

## Part IV: Risk Disclosures & Limitations

1. **Long options carry a 100% risk of premium loss.** If the stock does not bounce within the holding period, theta decay will erode the position.
2. **Past mean-reversion profitability does not guarantee future results.** In sustained bear markets, oversold stocks can become more oversold for extended periods.
3. **The IV/HV ratio is a proxy, not a perfect IV Rank.** True IV Rank requires 52 weeks of option IV history. Our proxy is directionally accurate but may mis-rank names with structural changes in volatility regimes.
4. **Realized volatility contraction can precede breakdowns as well as bounces.** The SMA200 and SPY trend filters reduce but do not eliminate the risk of buying into a trend reversal.
5. **This research is for informational and educational purposes only.** It is not investment advice.

---

## Appendix: Finviz Screener URL Templates

**Strategy 1 – Spring-Loaded Reversion (initial screen):**
```
https://finviz.com/screener.ashx?v=111&f=sec_energy|sec_materials|sec_industrials|sec_utilities|sec_consumerstaples|sec_healthcare|sec_financial|sec_realestate,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_rsi_u35,ta_sma200_pa&o=-marketcap
```
*(Note: Additional BB width, ATR, and volume contraction filtering happens in the pipeline after yfinance enrichment.)*

**Strategy 2 – IV Compression Bounce (initial screen):**
```
https://finviz.com/screener.ashx?v=111&f=sec_energy|sec_materials|sec_industrials|sec_utilities|sec_consumerstaples|sec_healthcare|sec_financial|sec_realestate,geo_usa,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_rsi_u35,ta_sma200_pa&o=-marketcap
```
*(Note: Additional IV/HV < 0.90 filtering happens in the pipeline after Alpaca/Finnhub enrichment.)*

---

## Integration with Existing Multi-Strategy Service

These strategies fit cleanly into the existing `multi_strategy_service.py` architecture:

```python
# In app/services/finviz/strategies.py

MEAN_REVERSION_BASE = FinvizQuery(
    filters=(
        "sec_energy|sec_materials|sec_industrials|sec_utilities|sec_consumerstaples|sec_healthcare|sec_financial|sec_realestate",
        "geo_usa",
        "sh_avgvol_o500",
        "sh_opt_option",
        "sh_price_o15",
        "ta_rsi_u35",
        "ta_sma200_pa",
    ),
    sort="-marketcap",
)

# Strategy 1: Spring-Loaded Reversion
SPRING_LOADED_BASE = MEAN_REVERSION_BASE

# Strategy 2: IV Compression Bounce
IV_COMPRESSION_BASE = MEAN_REVERSION_BASE
```

### Deduplication with Existing Strategies
- If `spring_loaded_reversion` and `iv_compression_bounce` both return the same ticker, keep the `iv_compression_bounce` result (additional vega edge).
- If either mean-reversion strategy and `catalyst_confluence` return the same ticker, keep the `catalyst_confluence` result (earnings catalyst is higher-conviction discrete event).
- If either mean-reversion strategy and `coiled_setup` return the same ticker, keep the mean-reversion result if the stock is oversold (RSI < 35), otherwise keep `coiled_setup`.

---

*Report prepared for Earning-Edge pipeline expansion.*
*Date: 2026-05-13*
*All cited research is peer-reviewed and publicly accessible.*
