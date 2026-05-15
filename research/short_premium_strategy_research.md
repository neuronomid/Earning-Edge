# Short-Term Options Strategy Research Report
## Quantitative Research: Short Premium / Short Volatility Strategies in Non-Technology Sectors

**Date:** May 13, 2026  
**Analyst:** Quantitative Research Agent  
**Classification:** Strategy Research – Implementation Ready

---

## Executive Summary

This report proposes **two complementary short-premium strategies** designed for non-technology sectors, grounded in academic research on the volatility risk premium (VRP), implied-realized volatility spreads, and earnings-volatility dynamics. Both strategies target a **maximum 28-day holding period**, produce **exactly 5 candidates per run**, and rely exclusively on the free data sources already available in the Earning-Edge pipeline (Finviz, yfinance, Finnhub, Alpaca).

The core research insight driving these strategies is the well-documented **negative volatility risk premium**: options tend to price in more uncertainty than the market ultimately realizes, creating a systematic edge for short-volatility sellers—provided position sizing, liquidity, and tail-risk controls are rigorously enforced (Hong, Sung & Yang, 2018; CBOE, 2024).

---

## Part I: Research Foundation

### 1.1 The Volatility Risk Premium (VRP)

Academic literature consistently finds that **selling volatility generates positive risk-adjusted returns**, but real-world frictions materially reduce profitability.

**Key Finding:** Hong, Sung & Yang (2018) examined 18 volatility-trading strategies on S&P 500 index options and found that short-volatility strategies (short straddles, strangles, and OTM puts) exhibited Sharpe ratios significantly higher than buy-and-hold benchmarks *before* trading costs. However, **bid-ask spreads reduced profitability substantially**, and margin requirements made it difficult for capital-constrained investors to deploy these strategies at scale. The authors conclude that modest profits survive real-world settings only when investors can **capture the VRP and time entries wisely**.

**Practical Implication:** For an automated system, this means we must:
- Trade only liquid underlyings with tight options markets (tight bid-ask spreads).
- Keep position sizes small and defined-risk where possible.
- Avoid volatility-selling immediately after large VIX spikes (when realized volatility may still be catching up).

**Citation:**  
- Hong, H., Sung, H-C., & Yang, J. (2018). *On profitability of volatility trading on S&P 500 equity index options: The role of trading frictions*. International Review of Economics & Finance, 55, 295-307. https://doi.org/10.1016/j.iref.2017.07.012

### 1.2 IV Rank, IV Percentile, and Option Selling Profitability

While exact IV Rank requires long-term option IV history, the concept is straightforward: **options are relatively expensive when current implied volatility is high versus its own recent history**. The CBOE Options Institute notes that implied volatility is mean-reverting and tends to overstate realized volatility over most market regimes.

**Key Metric:** We proxy IV Rank using the **Implied Volatility / Historical Volatility (IV/HV) ratio**:
- When IV/HV > 1.20, options are pricing in at least 20% more volatility than the stock has recently realized.
- Academic and practitioner research (tastylive, CBOE) confirms that selling options when this spread is elevated improves win rates, provided the underlying is not in a strong directional breakout.

**Citation:**  
- CBOE Options Institute (2024). *VIX Your Portfolio* (BlackRock research on volatility selling). CBOE Research Library. https://www.cboe.com/tradable_products/vix/

### 1.3 Sector Considerations for Short Volatility

Non-technology sectors offer two advantages for short-volatility strategies:

1. **Lower Beta Tails:** Energy, materials, industrials, and utilities do experience volatility, but their option markets are less dominated by speculative retail flow (which tends to inflate put premiums asymmetrically in tech).
2. **Macro-Driven IV Spikes:** Defensive sectors (utilities, staples, healthcare, REITs) occasionally exhibit sharp IV increases due to interest-rate shocks, regulatory news, or geopolitical events. These spikes are often **temporary overreactions**, making them ideal for mean-reversion-based premium selling.

### 1.4 Earnings Volatility Crush

Existing literature and practitioner research (tastylive Market Measures) confirm that **implied volatility tends to collapse immediately after earnings announcements**. Because Strategy A (catalyst_confluence) already captures the *long-volatility* earnings setup, our short-volatility strategies **explicitly avoid pre-earnings entries** to prevent being on the wrong side of a volatility crush *or* an earnings gap.

We instead focus on:
- **Post-earnings compression** (selling after the crush, when elevated IV has not yet fully mean-reverted).
- **Non-earnings macro spikes** (selling elevated IV caused by sector-specific news, rate moves, or commodity shocks).

---

## Part II: Proposed Strategies

---

### Strategy 1: Cyclical Compression (Short Strangles)

**Strategy Name:** `cyclical_compression`  
**Core Thesis:** Non-tech cyclical sectors (energy, materials, industrials, financials) exhibit a positive volatility risk premium and mean-revert after volatility spikes. By selling OTM strangles on liquid names where implied volatility is elevated relative to realized volatility, we harvest premium as the IV/HV spread compresses and time decay accelerates.

**Stock Universe & Sector Focus:**
- Primary sectors: **Energy, Materials, Industrials, Financials**
- Secondary: **Real Estate, Healthcare**
- Exclude: Technology, Communication Services (high-beta tech), Consumer Discretionary (tech-adjacent megacaps)

**Why It Fits Short-Term Options:**
- Cyclical names mean-revert faster than tech; IV spikes from commodity or macro news typically resolve within 2-4 weeks.
- Short-dated options (21-35 DTE) experience rapid theta decay, improving the probability of capturing a significant portion of the premium quickly.

**Data Requirements:**
| Data Point | Source | Endpoint/Method |
|------------|--------|-----------------|
| Stock universe + filters | Finviz | Screener URL (Playwright) |
| Historical prices (20-day realized vol) | yfinance | `Ticker.history(period="1mo")` |
| ATM Implied Volatility | Alpaca or Finnhub | Options chain query for nearest monthly expiry |
| Earnings date | yfinance or Finnhub | `Ticker.calendar` or earnings API |

**Candidate Selection Rules (exactly 5):**
1. **Finviz Screen:**
   - Sector = Energy, Materials, Industrials, Financials, Real Estate, Healthcare
   - Optionable = Yes
   - Price > $15
   - Average Volume > 500,000
   - RSI = 30–70 (avoid parabolic moves or breakdowns)
   - Relative Volume > 1.2 (indicates elevated attention / IV expansion)
   - Distance from 52w High < 25% (not in freefall)
   - Distance from 52w Low > 20% (avoid distressed names)

2. **Volatility Filter:**
   - Retrieve 20-day realized volatility (annualized) from yfinance close-to-close returns.
   - Retrieve nearest-month ATM implied volatility from Alpaca/Finnhub.
   - Compute `IV_HV_Ratio = ATM_IV / Realized_Vol`.
   - **Keep only names with IV_HV_Ratio > 1.20** (options are pricing in at least 20% more vol than realized).

3. **Earnings Check:**
   - Exclude names with earnings within the next 10 calendar days (avoid earnings crush/gap risk).

4. **Rank & Select:**
   - Rank by `IV_HV_Ratio` descending.
   - Select **top 5**.

**Option Contract Selection Logic:**
- **Expiration:** 28-35 DTE (balances theta decay with gamma risk).
- **Strikes:** ~16 delta on both call and put sides (approximately 1 standard deviation OTM). If exact 16-delta strikes are unavailable, choose the closest listed strike.
- **Alternative for smaller accounts:** Convert to **Iron Condors** with $2.50 or $5 wide wings on each side to define risk.

**Entry & Exit Logic:**
- **Entry:** Open at market open the day after candidate selection (or same day if automated).
- **Profit Target:** Close at **50% of maximum profit** (e.g., if credit received = $1.00, buy back at $0.50).
- **Time Stop:** Close at **14 DTE** remaining (roll or exit to reduce gamma/assignment risk).
- **Loss Stop:** Close if the position reaches **200% of credit received** (i.e., the strangle has doubled in value against you).
- **Technical Stop:** If the underlying breaches either short strike, evaluate a roll to the next expiration or close for loss.

**Risk Management:**
- **Position Sizing:** Risk no more than **2% of portfolio notional** per strangle (or per iron condor).
- **Assignment Risk:** Only trade names you are willing to take assignment on (or use iron condors to avoid assignment).
- **Tail Risk:** If VIX spikes >30, pause new entries for 48 hours to avoid selling into a rapidly expanding volatility environment.
- **Sector Concentration:** No more than 2 of the 5 candidates from the same sector.

**Maximum Holding Period:** 28 days (enforced by time stop at 14 DTE if entered at 28-35 DTE).

**Expected Failure Modes:**
1. **Directional Breakout:** The underlying moves beyond the short strike before IV mean-reverts. Mitigated by RSI filter and 16-delta strike selection.
2. **Volatility Expansion:** A macro shock (OPEC surprise, Fed pivot) causes IV to keep rising. Mitigated by VIX spike pause rule.
3. **Low Liquidity:** Wide bid-ask spreads erode edge. Mitigated by average volume >500K filter.
4. **Earnings Surprise:** A name with an undetected earnings date gaps. Mitigated by earnings date check.

**Supporting Research:**
- Hong, H., Sung, H-C., & Yang, J. (2018). *On profitability of volatility trading on S&P 500 equity index options: The role of trading frictions*. https://doi.org/10.1016/j.iref.2017.07.012
- CBOE Options Institute. *VIX Your Portfolio* (BlackRock research). https://www.cboe.com/tradable_products/vix/
- Ge, W. (2016). *A survey of three derivative-based methods to harvest the volatility premium in equity markets*. The Journal of Investing. https://scholar.archive.org/work/767ecbgeobfxnicvln4yuuaaaa

---

### Strategy 2: Defensive Yield Capture (Cash-Secured Short Puts)

**Strategy Name:** `defensive_yield_capture`  
**Core Thesis:** Defensive sectors (utilities, consumer staples, healthcare, REITs) exhibit lower realized volatility but occasionally experience **temporary implied-volatility spikes** driven by macro fears (rate changes, recession scares, geopolitical events). These spikes overstate actual downside risk. By selling cash-secured puts on high-quality dividend payers with elevated IV/HV ratios, we capture an enhanced premium yield with lower tail risk than cyclical short strangles.

**Stock Universe & Sector Focus:**
- Primary sectors: **Utilities, Consumer Staples, Healthcare, Real Estate**
- Secondary: **Financials** (large-cap banks / insurers only)
- Exclude: Technology, Energy, Materials, Industrials (too cyclical for this thesis)

**Why It Fits Short-Term Options:**
- Defensive names have lower beta; even if assigned, the underlying is a lower-risk holding.
- Short-dated puts (21-30 DTE) on defensive stocks benefit from rapid theta decay while the probability of large downside moves is lower than in cyclicals.

**Data Requirements:**
| Data Point | Source | Endpoint/Method |
|------------|--------|-----------------|
| Stock universe + filters | Finviz | Screener URL (Playwright) |
| Historical prices (realized vol, SMA) | yfinance | `Ticker.history(period="3mo")` |
| Dividend yield | yfinance | `Ticker.info["dividendYield"]` |
| ATM Put IV / nearest strike IV | Alpaca or Finnhub | Options chain query |
| Earnings date | yfinance / Finnhub | Earnings calendar API |

**Candidate Selection Rules (exactly 5):**
1. **Finviz Screen:**
   - Sector = Utilities, Consumer Staples, Healthcare, Real Estate, Financials
   - Optionable = Yes
   - Price > $20
   - Average Volume > 300,000
   - Dividend Yield > 2.5% (indicates quality / defensive nature)
   - RSI = 35–65 (avoid downtrends and parabolic rallies)
   - Beta < 1.2 (lower systematic risk)
   - Price > 50-day SMA (technical support / uptrend bias)

2. **Volatility Filter:**
   - Compute 20-day realized volatility from yfinance.
   - Retrieve 25-30 delta put IV (or nearest ATM put IV) from Alpaca/Finnhub.
   - Compute `IV_HV_Ratio = Put_IV / Realized_Vol`.
   - **Keep only names with IV_HV_Ratio > 1.15**.

3. **Premium Yield Filter:**
   - Compute `Annualized_Premium_Yield = (Credit_Received / Strike_Price) * (365 / DTE)`.
   - **Keep only names with Annualized_Premium_Yield > 15%** (ensures sufficient compensation for the risk).

4. **Earnings Check:**
   - Exclude names with earnings within the next 10 calendar days.

5. **Rank & Select:**
   - Rank by `IV_HV_Ratio` descending, then by `Annualized_Premium_Yield` descending.
   - Select **top 5**.

**Option Contract Selection Logic:**
- **Expiration:** 21-30 DTE (shorter holding period to reduce assignment risk).
- **Strike:** ~20-25 delta put (OTM enough to provide a cushion, but close enough to collect meaningful premium).
- **Alternative:** If the account cannot take assignment, sell **put credit spreads** ($5 wide) instead.

**Entry & Exit Logic:**
- **Entry:** Open at market open the day after selection.
- **Profit Target:** Close at **50% of maximum profit**.
- **Time Stop:** Close at **14 DTE** remaining.
- **Loss Stop:** Close if the put reaches **200% of credit received**.
- **Assignment Management:** If the put goes ITM and assignment is imminent, either:
  - Roll down and out to the next expiration (if IV is still elevated and thesis intact), or
  - Accept assignment and sell a covered call (wheel strategy) if the name meets quality criteria.

**Risk Management:**
- **Position Sizing:** Each cash-secured put should require no more than **10% of portfolio cash** (i.e., if account is $50k, max strike exposure per put is ~$5,000). For put credit spreads, risk no more than **1.5% of portfolio** per spread.
- **Assignment Risk:** Only sell puts on names you are willing to own at the strike price.
- **Tail Risk:** If the underlying drops >8% in 2 days (flash crash in a defensive name), close immediately and re-evaluate.
- **Rate Risk:** Utilities and REITs are rate-sensitive. If 10Y Treasury yields spike >20 bps in a single day, pause new entries for 24 hours.

**Maximum Holding Period:** 28 days.

**Expected Failure Modes:**
1. **Sector Rotation:** A rapid shift out of defensives into growth causes broad defensive-sector decline. Mitigated by beta filter and diversification.
2. **Dividend Cut / Fundamental Deterioration:** A screened name cuts its dividend or has bad news. Mitigated by focusing on large-cap names with long dividend histories.
3. **Deep ITM Assignment:** The stock drops below the strike and you are assigned. Mitigated by 20-25 delta selection and willingness to own the stock (or use spreads).
4. **Low Liquidity in Put Market:** Wide bid-ask spreads in defensive names with lower options volume. Mitigated by average volume >300K and checking options open interest before entry.

**Supporting Research:**
- Coval, J. D., & Shumway, T. (2001). *Expected option returns*. Journal of Finance. (Foundational paper on positive expected returns to option writing.)
- Bondarenko, O. (2014). *Why are put options so expensive?* Quarterly Journal of Finance. (Documents the extreme risk premium in OTM puts, supporting selective put-selling in lower-risk names.)
- Friedentag, H. (1999). *Stocks for Options Trading: Low-Risk, Low-Stress Strategies for Selling Stock Options-Profitability*. Taylor & Francis. (Practitioner guide to covered-call and cash-secured-put strategies on quality names.)

---

## Part III: Implementation Notes for the Pipeline

### 3.1 Data Source Mapping

| Data Need | Recommended Source | Rationale |
|-----------|-------------------|-----------|
| Stock universe + basic filters | **Finviz** (Playwright screener) | Free, no login needed, supports all required filters (sector, price, volume, RSI, SMA, beta, dividend yield) |
| Historical price data | **yfinance** | Free, no API key required, sufficient for realized vol and SMA calculations |
| Options chain + IV | **Alpaca** (free tier) or **Finnhub** (free tier) | Alpaca offers clean options chain API; Finnhub free tier includes implied volatility estimates |
| Earnings calendar | **yfinance** or **Finnhub** | Both provide next earnings date for filtering |

### 3.2 Candidate Generation Flow

```
Step 1: Finviz Screener (Playwright)
   → Fetch top 50-100 names matching sector + liquidity + technical filters

Step 2: yfinance Enrichment
   → Download 1-month historical prices for each candidate
   → Compute 20-day realized volatility
   → Compute distance to 50-day SMA
   → Check next earnings date

Step 3: Options Chain Query (Alpaca/Finnhub)
   → Fetch nearest-month options chain
   → Extract ATM call/put IV (Strategy 1) or 20-25 delta put IV (Strategy 2)
   → Compute IV/HV ratio

Step 4: Ranking & Selection
   → Apply IV/HV threshold filter
   → Apply premium-yield filter (Strategy 2 only)
   → Rank and select top 5

Step 5: Output Candidate List
   → Ticker, sector, strike(s), expiration, credit estimate, IV/HV ratio, rationale
```

### 3.3 Automation Considerations

- **No CAPTCHA / Login Gates:** Finviz screener is public; Alpaca and Finnhub free tiers use simple API keys.
- **Retry Safety:** Follow the existing Finviz retry ladder (retry page load once, retry with clean context, then fallback).
- **Scheduling:** Run both strategies **once per week** (e.g., Monday morning) to avoid over-trading and to capture fresh volatility regimes.
- **Deduplication:** If a ticker appears in both Strategy 1 and Strategy 2 output, keep the Strategy 2 (defensive) result and drop the Strategy 1 result to avoid concentration.

### 3.4 Suggested Warning / Fallback Rules

- If Alpaca/Finnhub options data is unavailable for a candidate, **drop the candidate** rather than trade blind.
- If fewer than 5 candidates pass all filters, return only the passing candidates (do not relax filters).
- If IV/HV ratio falls below 1.10 across the entire screened universe for 2 consecutive weeks, surface a warning:
  > "⚠️ Implied volatility is compressed across non-tech sectors. Short-premium strategies may offer insufficient edge this week."

---

## Part IV: Risk Disclosures & Limitations

1. **Short options carry theoretically unlimited risk** (for naked calls) or large notional exposure (for naked puts). Defined-risk alternatives (iron condors, put spreads) should be used for smaller accounts.
2. **Past VRP profitability does not guarantee future results.** During prolonged crises (e.g., March 2020), realized volatility can exceed implied volatility for weeks, destroying short-volatility portfolios.
3. **The IV/HV ratio is a proxy, not a perfect IV Rank.** True IV Rank requires 52 weeks of option IV history. Our proxy is directionally accurate but may mis-rank names with structural changes in volatility regimes.
4. **Sector rotation can invalidate technical filters rapidly.** A "defensive" name can become a falling knife if sector dynamics shift.
5. **This research is for informational and educational purposes only.** It is not investment advice.

---

## Appendix: Finviz Screener URL Templates

**Strategy 1 – Cyclical Compression (initial screen):**
```
https://finviz.com/screener.ashx?v=111&f=sec_energy|sec_materials|sec_industrials|sec_financials|sec_realestate|sec_healthcare,sh_avgvol_o500,sh_opt_option,sh_price_o15,ta_rsi_30to70,sh_relvol_o1.2&o=-relativevolume
```
*(Note: Additional IV/HV filtering happens in the pipeline after data enrichment.)*

**Strategy 2 – Defensive Yield Capture (initial screen):**
```
https://finviz.com/screener.ashx?v=111&f=sec_utilities|sec_consumerstaples|sec_healthcare|sec_realestate|sec_financials,sh_avgvol_o300,sh_opt_option,sh_price_o20,fa_div_o2.5,ta_rsi_35to65,ta_sma50_pa,ta_beta_u1.2&o=-dividendyield
```
*(Note: Additional IV/HV and premium-yield filtering happens in the pipeline.)*

---

*End of Report*
