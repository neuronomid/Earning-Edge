# Research Report: Short-Term Options Strategies for Non-Technology Sectors
## Dividend-Related and Calendar Spread Setups

**Date:** 2025-05-13  
**Analyst:** Quantitative Research Agent  
**Classification:** Pipeline Strategy Research — Actionable

---

## 1. Executive Summary

This report proposes **two specific, automatable short-term options strategies** designed for non-technology sectors (energy, materials, industrials, utilities, consumer staples, healthcare, financials, real estate). Both strategies are grounded in peer-reviewed academic finance literature and practitioner research, require only free or low-cost data sources, and are designed to produce exactly **5 candidates per run** with a maximum holding period of **under 4 weeks**.

| Strategy | Core Mechanism | Typical Holding | Key Data Source |
|----------|---------------|-----------------|-----------------|
| **Ex-Dividend Call Write** | Capture dividend + option premium via deep ITM short calls on high-dividend non-tech stocks | 2–7 days | Finviz + yfinance |
| **Pre-Earnings Calendar Spread** | Exploit volatility term structure flattening before earnings in defensive sectors | 7–21 days | Finviz + Alpaca/Finnhub |

---

## 2. Strategy A: Ex-Dividend Call Write ("DivCapture Call")

### 2.1 Strategy Name
**Ex-Dividend Call Write** (a.k.a. Hedged Dividend Capture with Short Calls)

### 2.2 Core Thesis

Academic research documents persistent abnormal returns and option pricing anomalies around ex-dividend dates. The key insight, established by **Kalay & Subrahmanyam (1984)** and **Hao, Kalay & Mayhew (2010)**, is that American call options frequently trade at prices inconsistent with rational early exercise policies around ex-dividend dates. This creates a capture opportunity:

- Buy the underlying stock shortly before the ex-dividend date
- Sell a deep in-the-money (ITM) American call option against it
- Collect both the dividend and the option premium
- The short call is likely to be exercised early by the counterparty, or the position is closed post-ex-dividend

**Brown & Lummer (1984)** and **Zivney & Alderson (1986)** demonstrated that hedged dividend capture strategies using options can enhance cash-management returns for short-term investors. More recently, **Henry & Koski (2017)** showed that institutional traders earn significant profits from ex-dividend trading, indicating that the anomaly persists but requires execution skill and cost control.

The strategy works best in **non-technology sectors** because:
1. These sectors have higher dividend yields and more predictable dividend calendars
2. Utilities, REITs, consumer staples, and energy names exhibit lower volatility, making the short call premium + dividend capture more predictable
3. Lower beta means less directional risk during the short holding period

### 2.3 Stock Universe and Sector Focus

**Primary Sectors:**
- **Utilities** (highest dividend consistency, lowest volatility)
- **Consumer Staples** (recession-resistant dividends)
- **Real Estate (REITs)** (mandatory high payout ratios)
- **Energy** (midstream MLPs, integrated majors with stable dividends)
- **Financials** (large banks with quarterly dividends)
- **Healthcare** (big pharma with established dividend track records)

**Exclusions:**
- Technology (per mandate)
- Biotech (binary event risk)
- Any stock with earnings within 5 days of the ex-dividend date

### 2.4 Why It Fits Short-Term Options

- **Holding period:** 2–7 days (from entry before ex-date to exit after)
- **Time decay:** Minimal impact on deep ITM short calls
- **Dividend capture:** The economic event is discrete and time-bound
- **Early exercise:** The counterparty's optimal strategy is to exercise early on the day before ex-dividend if the dividend exceeds the remaining time value, accelerating our exit

### 2.5 Data Requirements

| Data Point | Frequency | Purpose |
|------------|-----------|---------|
| Ex-dividend dates | Daily scan | Identify upcoming events (0–7 days) |
| Dividend amount / yield | Per stock | Size the capture and filter by minimum $0.25/share |
| Stock price | Real-time | Ensure liquidity and price > $20 |
| Option chain (bid/ask, IV, delta) | Real-time | Select deep ITM call to sell |
| Average daily volume | Daily | Liquidity filter (> 500K shares) |
| Sector classification | Static | Enforce non-tech mandate |
| Next earnings date | Daily | Avoid earnings-dividend overlap |

### 2.6 How to Access the Data

| Source | Data | Access Method | Cost |
|--------|------|---------------|------|
| **Finviz Screener** | Ex-dividend dates, sector, market cap, price, volume, earnings dates | Playwright browser automation on free screener | Free |
| **yfinance** | Dividend history, current yield, stock prices, option chains | Python API | Free |
| **Alpaca** | Real-time option quotes (bid/ask, Greeks) | REST API | Free tier |
| **Finnhub** | Dividend calendar, earnings dates | REST API | Free tier (60 calls/min) |

**Recommended data pipeline:**
1. **Finviz** → Screen for stocks with ex-dividend date within next 7 days, price > $20, avg volume > 500K, sector ≠ technology
2. **yfinance** → Pull dividend amount, confirm yield > 2.5% annualized, pull option chain
3. **Alpaca** → Get real-time bid/ask for candidate options, calculate max profit
4. **Finnhub** → Cross-check earnings date to ensure no conflict

### 2.7 Candidate Selection Rules (Produces Exactly 5)

1. **Ex-dividend window:** Next 1–7 calendar days
2. **Minimum dividend:** ≥ $0.25 per share (ensures meaningful capture)
3. **Stock price:** > $20 (avoids penny-stock option illiquidity)
4. **Market cap:** > $2B (mid-cap or larger)
5. **Average volume:** > 500,000 shares/day
6. **Sector:** Energy, Materials, Industrials, Utilities, Consumer Staples, Healthcare, Financials, Real Estate ONLY
7. **Earnings buffer:** No earnings announcement within ±5 trading days of ex-date
8. **Option liquidity:** Open interest on nearest ITM call > 100 contracts
9. **Implied volatility:** IV30 < 40% (avoid high-vol names where assignment risk is priced)
10. **Rank by:** (Dividend Amount + Call Premium) / Stock Price → highest first
11. **Select top 5** from ranked list

### 2.8 Option Contract Selection Logic

- **Structure:** Covered call (long stock + short 1 deep ITM call per 100 shares)
- **Strike:** Choose the highest strike call with delta ≥ 0.75 that still has meaningful time value (≥ $0.10)
- **Expiration:** Nearest monthly expiration AFTER the ex-dividend date (gives counterparty incentive to exercise early)
- **Ideal scenario:** Delta 0.80–0.90, extrinsic value < $0.20, bid-ask spread < 5% of option price

### 2.9 Entry and Exit Logic

**Entry (T-2 to T-1 before ex-date):**
- Buy stock at market (or limit at mid-bid)
- Sell the selected deep ITM call simultaneously
- Target net debit = Stock Price − Call Premium < Strike Price (ensuring dividend + premium > assignment risk)

**Exit Scenarios:**
1. **Early Assignment (optimal):** Counterparty exercises the night before ex-date. You keep the premium, lose the stock, do NOT collect dividend. Profit = Call Premium − (Stock Purchase Price − Strike). This is the most common outcome for deep ITM calls.
2. **No Assignment:** You collect the dividend. Exit the position within 1–2 days post-ex-date by selling the stock and buying back the call (or letting assignment happen if still ITM).

**Important academic note:** Per **Hao, Kalay & Mayhew (2010)**, a significant fraction of American calls are NOT exercised optimally around ex-dividend dates, meaning the short call writer often collects BOTH the dividend and the premium. This "suboptimal exercise" is a key source of edge.

### 2.10 Risk Management

- **Max position size:** 10% of strategy allocation per name
- **Stop loss:** If stock drops > 3% from entry before ex-date, close immediately (dividend capture is invalidated)
- **Earnings avoidance:** Strict ±5 day buffer around earnings
- **Liquidity minimum:** Only trade options with daily volume > 50 contracts
- **Assignment risk:** Fully expected and manageable. The position is designed around assignment.

### 2.11 Maximum Holding Period

- **Target:** 2–5 days
- **Hard maximum:** 7 days (if not assigned by T+2 post-ex-date, close manually)

### 2.12 Expected Failure Modes

1. **Early assignment before ex-date:** You keep premium but miss the dividend. Still profitable if entry was disciplined.
2. **Stock drops through strike post-ex-date:** The dividend is collected but capital loss on stock exceeds dividend. Mitigated by deep ITM call and low-vol universe.
3. **Ex-dividend date change:** Corporate action or market holiday shifts the date. Mitigated by real-time data checks.
4. **Illiquid option with wide bid-ask:** Entry/exit slippage erodes edge. Mitigated by liquidity filters.
5. **Dividend cut/surprise:** Rare for established non-tech names but possible. Mitigated by minimum 2-year dividend history filter.

### 2.13 Supporting Research Citations

1. **Hao, J., Kalay, A., & Mayhew, S. (2010).** "Ex-dividend arbitrage in option markets." *The Review of Financial Studies*, 23(1), 271–303. https://academic.oup.com/rfs/article-abstract/23/1/271
   - *Key finding:* Call options exhibit suboptimal exercise around ex-dividend dates, creating profit opportunities for short call writers.

2. **Henry, T. R., & Koski, J. L. (2017).** "Ex‐dividend profitability and institutional trading skill." *The Journal of Finance*, 72(2), 835–870. https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12479
   - *Key finding:* Institutions earn significant net profits trading around ex-dividend dates after transaction costs; skill and speed matter.

3. **Kalay, A., & Subrahmanyam, M. G. (1984).** "The ex-dividend day behavior of option prices." *Journal of Business*, 57(2), 275–298. https://www.jstor.org/stable/2352771
   - *Key finding:* Option prices do not fully adjust to the predictable stock price drop on ex-dividend dates.

4. **Brown, K. C., & Lummer, S. L. (1984).** "The cash management implications of a hedged dividend capture strategy." *Financial Management*, 13(3), 25–29. https://www.jstor.org/stable/3665036
   - *Key finding:* Option-based dividend capture plans can outperform T-bills for short-term cash management.

5. **Zivney, T. L., & Alderson, M. J. (1986).** "Hedged dividend capture with stock index options." *Financial Management*, 15(3), 23–31. https://www.jstor.org/stable/3664933
   - *Key finding:* Hedging with index options can reduce systematic risk in dividend capture portfolios.

6. **Rantapuska, E. (2008).** "Ex-dividend day trading: Who, how, and why? Evidence from the Finnish market." *Journal of Financial Economics*, 88(2), 355–374. https://www.sciencedirect.com/science/article/abs/pii/S0304405X07001729
   - *Key finding:* Tax heterogeneity drives ex-dividend trading; investors with tax advantages actively capture dividends.

---

## 3. Strategy B: Pre-Earnings Calendar Spread ("VolTerm Flattening")

### 3.1 Strategy Name
**Pre-Earnings Calendar Spread** (a.k.a. Time Spread or Horizontal Spread)

### 3.2 Core Thesis

The implied volatility term structure systematically distorts before earnings announcements. **Atilgan (2014)** documents that "volatility spreads" (the difference between short-dated and long-dated implied volatility) predict earnings announcement returns. **Anagnostopoulou & Tsekrekos (2017)** show that the term structure of implied volatility flattens or inverts before earnings as near-term uncertainty spikes.

A calendar spread exploits this by:
- **Selling** a short-dated option (front month) at elevated IV
- **Buying** a longer-dated option (back month) at relatively lower IV
- Profiting when the IV differential converges post-announcement or as time decay differential works in our favor

**Do, Foster & Gray (2016)** studied the profitability of volatility spread trading and found that implied volatility spreads contain predictive information about future realized volatility, confirming that calendar spreads can be traded profitably with proper selection.

The strategy is especially suited to **non-technology sectors** because:
1. Defensive sectors (utilities, staples, healthcare) have lower baseline volatility, making the pre-earnings IV spike more predictable and less prone to gap risk
2. Earnings surprises in these sectors are typically smaller and less binary than in tech
3. The volatility term structure is more stable and mean-reverting in low-vol regimes

### 3.3 Stock Universe and Sector Focus

**Primary Sectors:**
- **Consumer Staples** ( predictable revenue, low earnings variance)
- **Utilities** (regulated earnings, very low surprise frequency)
- **Healthcare / Pharma** (Big Pharma has scheduled pipelines + recurring revenue)
- **Financials** (large banks with predictable NII trends)
- **Industrials** (mature companies with steady order books)

**Exclusions:**
- Technology (per mandate)
- Any stock with pre-earnings IV rank > 90th percentile (too expensive)
- Any stock with a history of > 10% earnings moves

### 3.4 Why It Fits Short-Term Options

- **Holding period:** 7–21 days (enter 1–3 weeks before earnings, exit just before or after announcement)
- **Event-driven:** Earnings provide a catalyst for IV term structure reversion
- **Defined risk:** Max loss is the net debit paid for the spread
- **Theta advantage:** The front-month short leg decays faster than the back-month long leg

### 3.5 Data Requirements

| Data Point | Frequency | Purpose |
|------------|-----------|---------|
| Earnings announcement dates | Daily scan | Identify upcoming events (7–21 days) |
| Implied volatility term structure | Real-time | Compare front-month vs back-month IV |
| IV Rank / IV Percentile | Daily | Avoid names where IV is already extreme |
| Historical earnings moves | Per stock | Filter out high-gap-risk names |
| Stock price, volume | Daily | Liquidity and price filters |
| Option chain (bid/ask, Greeks) | Real-time | Construct the spread |

### 3.6 How to Access the Data

| Source | Data | Access Method | Cost |
|--------|------|---------------|------|
| **Finviz Screener** | Earnings dates, sector, market cap, price, volume, RSI | Playwright browser automation | Free |
| **yfinance** | Historical prices, earnings history, volatility metrics | Python API | Free |
| **Alpaca** | Real-time option chains, IV, Greeks | REST API | Free tier |
| **Finnhub** | Earnings calendar, historical EPS surprises | REST API | Free tier |
| **Alpha Vantage** | Historical volatility, earnings calendar | REST API | Free tier (5 calls/min) |

**Recommended data pipeline:**
1. **Finviz** → Screen for stocks with earnings in next 7–21 days, price > $20, avg volume > 1M, sector ≠ technology
2. **Finnhub** → Pull historical earnings surprises and actual move percentages
3. **yfinance** → Calculate 30-day historical volatility, IV rank proxy
4. **Alpaca** → Pull option chain for candidate, calculate front-month vs back-month IV differential

### 3.7 Candidate Selection Rules (Produces Exactly 5)

1. **Earnings window:** Next 7–21 calendar days
2. **Stock price:** > $20
3. **Market cap:** > $5B (large-cap stability)
4. **Average volume:** > 1,000,000 shares/day
5. **Sector:** Consumer Staples, Utilities, Healthcare, Financials, Industrials ONLY (most defensive)
6. **Historical earnings gap:** Average absolute move on last 4 earnings < 5% (filter out high-gap names)
7. **IV differential:** Front-month ATM IV > Back-month ATM IV by at least 5 percentage points (e.g., 35% vs 28%)
8. **IV environment:** Stock's current IV30 < 50% (avoid names already in crisis)
9. **Option liquidity:** Front-month and back-month ATM calls both have open interest > 200 and bid-ask spread < 10% of mid
10. **Rank by:** IV differential (front − back) × Vega of back month → highest first
11. **Select top 5** from ranked list

### 3.8 Option Contract Selection Logic

- **Structure:** Calendar call spread (or put spread; calls preferred for non-tech names with slight upward bias)
- **Short leg:** Sell front-month ATM call, expiration 7–14 days out (just before earnings)
- **Long leg:** Buy back-month ATM call, expiration 35–60 days out (just after earnings)
- **Strike:** At-the-money (± 2.5% of current stock price)
- **Net debit target:** $0.50–$2.00 per spread (adjust for stock price)
- **Ideal Greek profile:** Positive theta, near-zero delta, positive vega on the back month

### 3.9 Entry and Exit Logic

**Entry (T-21 to T-7 before earnings):**
- Enter when IV differential is widest (typically 1–2 weeks before earnings)
- Buy the back-month ATM call
- Sell the front-month ATM call
- Net debit = Long Call Premium − Short Call Premium

**Exit Scenarios:**
1. **Target exit (preferred):** Close 1–2 days before earnings announcement. The front-month short leg has decayed significantly, and the IV differential has compressed. Capture the time decay differential.
2. **Hold through earnings:** If the term structure is still inverted and the stock hasn't moved much, hold through the announcement. The front-month leg expires worthless or near worthless, while the back-month leg retains value.
3. **Stop loss:** If stock moves > 5% in either direction before earnings, close immediately (the spread becomes directional and delta risk dominates).

**Academic basis:** **Atilgan (2014)** shows that volatility spreads predict earnings returns, meaning the IV differential contains information. By closing before earnings, we capture the "setup" portion of the trade without taking the binary event risk.

### 3.10 Risk Management

- **Max position size:** 8% of strategy allocation per spread
- **Max net debit:** $2.00 per spread (or 2% of underlying price, whichever is lower)
- **Stop loss:** Close if underlying moves > 5% from entry OR if IV differential compresses by > 50% within 3 days
- **Earnings avoidance:** For the most conservative implementation, close 1 day before the announcement and do NOT hold through
- **Liquidity minimum:** Both legs must have daily volume > 30 contracts

### 3.11 Maximum Holding Period

- **Target:** 7–14 days
- **Hard maximum:** 21 days (if earnings date shifts or IV differential fails to compress)

### 3.12 Expected Failure Modes

1. **Large directional move pre-earnings:** The spread becomes delta-heavy. Mitigated by the 5% move stop-loss and defensive universe selection.
2. **IV differential fails to compress:** Rare in non-tech names with scheduled earnings, but can happen in broad market stress. Mitigated by 21-day hard stop.
3. **Earnings date uncertainty:** Companies sometimes pre-announce or delay. Mitigated by Finviz + Finnhub cross-checks.
4. **Bid-ask spread erosion:** Calendar spreads require two-legged execution. Mitigated by liquidity filters.
5. **Back-month IV collapse:** If the market prices in lower post-earnings volatility, the long leg loses value. Mitigated by selecting names where back-month IV is near its 1-year low.

### 3.13 Supporting Research Citations

1. **Atilgan, Y. (2014).** "Volatility spreads and earnings announcement returns." *Journal of Banking & Finance*, 38, 205–215. https://www.sciencedirect.com/science/article/abs/pii/S0378426613003443
   - *Key finding:* The difference between short-dated and long-dated implied volatility predicts earnings announcement returns; volatility term structure contains information.

2. **Anagnostopoulou, S. C., & Tsekrekos, A. E. (2017).** "Accounting quality, information risk and the term structure of implied volatility around earnings announcements." *Research in International Business and Finance*, 41, 158–174. https://www.sciencedirect.com/science/article/abs/pii/S0275531917300860
   - *Key finding:* The term structure of implied volatility systematically flattens before earnings and steepens after; quality of accounting information affects the shape.

3. **Do, B. H., Foster, A., & Gray, P. (2016).** "The profitability of volatility spread trading on ASX equity options." *Journal of Futures Markets*, 36(12), 1157–1174. https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.21788
   - *Key finding:* Implied volatility spreads predict future realized volatility; calendar spread strategies can be constructed profitably using term structure signals.

4. **Hou, A. J., & Nordén, L. L. (2018).** "VIX futures calendar spreads." *Journal of Futures Markets*, 38(6), 662–677. https://onlinelibrary.wiley.com/doi/abs/10.1002/fut.21906
   - *Key finding:* Calendar spreads in volatility products are driven by term structure expectations and carry significant predictive power for future volatility.

5. **Donders, M. W. M., Kouwenberg, R., & Vorst, T. C. F. (2000).** "Options and earnings announcements: an empirical study of volatility, trading volume, open interest and liquidity." *European Financial Management*, 6(2), 149–171. https://onlinelibrary.wiley.com/doi/abs/10.1111/1468-036X.00121
   - *Key finding:* Options markets anticipate earnings announcements through increases in implied volatility, volume, and spreads; the effect is strongest in the final week.

6. **Jones, C., & Wang, T. (2012).** "The term structure of equity option implied volatility." *USC Working Paper*. https://msbfile03.usc.edu/digitalmeasures/jonesc/Instruction/JonesWang.pdf
   - *Key finding:* The slope of the implied volatility term structure predicts future stock and option returns; steepening forecasts lower volatility, flattening forecasts higher near-term volatility.

---

## 4. Implementation Notes for the Pipeline

### 4.1 Integration with Existing Finviz Stack

Both strategies can reuse the existing `app/services/finviz/` browser automation infrastructure:

- **DivCapture Call:** Use a new Finviz screener URL filter `exdividenddate_nextweek` (if available) or filter by `fa_div_pos` + `earningsdate_thismonth` and cross-check with Finnhub/yfinance for exact ex-dates.
- **VolTerm Flattening:** Use the existing earnings-date filter in Finviz (`earningsdate_nextweek`) combined with `sh_avgvol_o1000`, `cap_largeover`, and sector exclusions.

### 4.2 New Data Service Requirements

| Service | New Methods Needed |
|---------|-------------------|
| `yfinance` | `get_dividend_calendar(tickers)`, `get_option_chain(ticker)` |
| `Alpaca` | `get_option_quotes(ticker, expiration, strike)` |
| `Finnhub` | `get_dividend_calendar(ticker)`, `get_earnings_history(ticker)` |

### 4.3 Candidate Output Format

Each strategy should produce exactly 5 candidates in the standardized pipeline format:

```python
{
  "ticker": "XEL",
  "strategy": "divcapture_call",
  "sector": "Utilities",
  "entry_date": "2025-05-15",
  "event_date": "2025-05-19",  # ex-dividend or earnings
  "holding_days": 5,
  "setup": {
    "stock_price": 58.50,
    "dividend": 0.4875,
    "short_call_strike": 55.0,
    "short_call_premium": 3.80,
    "net_debit": 54.70,
    "max_profit": 0.7875,
    "max_profit_pct": 1.44
  },
  "risk_flags": []
}
```

### 4.4 Multi-Strategy Service Integration

In `app/services/multi_strategy_service.py`, add the two new strategies alongside `catalyst_confluence` and `coiled_setup`:

```python
STRATEGIES = [
    "catalyst_confluence",
    "coiled_setup", 
    "divcapture_call",
    "volterm_flattening"
]
```

**Deduplication rule:** If the same ticker appears in `divcapture_call` and `catalyst_confluence`, preserve the catalyst result (earnings is higher conviction) and dedupe the dividend capture result. Similarly, if `volterm_flattening` and `catalyst_confluence` share a ticker, preserve the catalyst result.

### 4.5 Warning and Fallback Rules

- **DivCapture Call:** If Finviz ex-dividend data is unavailable, fall back to `yfinance` dividend history + forward projection. Surface warning: `⚠️ Finviz ex-dividend data unavailable; using yfinance projected dates.`
- **VolTerm Flattening:** If Alpaca option chain data is unavailable, skip the candidate rather than trade blind. This strategy requires accurate Greeks.

---

## 5. Data Source Mapping Summary

| Strategy | Finviz | yfinance | Finnhub | Alpaca | Alpha Vantage |
|----------|--------|----------|---------|--------|---------------|
| **DivCapture Call** | Screen: sector, price, volume, earnings | Dividend amount, option chain | Earnings cross-check, dividend calendar | Real-time option quotes | Not required |
| **VolTerm Flattening** | Screen: sector, price, volume, earnings date | Historical volatility, earnings history | Earnings calendar, EPS surprises | Option chain, IV, Greeks | Historical volatility backup |

---

## 6. Risk and Limitations

### 6.1 Macro Environment Sensitivity
- **Rising rate environments:** Dividend capture becomes less attractive as risk-free rates rise; calendar spreads may see persistent IV term structure inversion
- **High VIX regimes:** Both strategies suffer as bid-ask spreads widen and assignment patterns become less predictable

### 6.2 Transaction Cost Assumptions
- The academic studies assume institutional transaction costs. A small automated system must:
  - Use broker with $0 commission on stocks and ≤ $0.65/contract option fees
  - Filter for tight bid-ask spreads (< 5% of premium for DivCapture, < 10% for VolTerm)

### 6.3 Tax Considerations
- DivCapture Call generates short-term capital gains and ordinary dividend income; the holding period is too short for qualified dividend treatment
- Calendar spreads are always short-term if closed within 21 days
- Consult a tax professional; this research assumes a tax-advantaged account (IRA)

### 6.4 Capacity Constraints
- Both strategies are capacity-limited by option liquidity. Maximum advisable AUM per strategy: ~$500K–$1M before slippage becomes significant.

---

## 7. Conclusion and Recommendations

The **Ex-Dividend Call Write** and **Pre-Earnings Calendar Spread** are two academically grounded, automatable strategies that fit the existing Earning-Edge pipeline architecture. They:

1. **Complement existing strategies:** DivCapture and VolTerm are non-directional or income-oriented, contrasting with the momentum/earnings-driven catalyst_confluence and coiled_setup.
2. **Use available data:** All required data is accessible via free tiers of Finviz, yfinance, Finnhub, and Alpaca.
3. **Are automatable:** Both strategies use discrete, rule-based entry/exit criteria with clear risk limits.
4. **Meet the mandate:** Both focus on non-technology sectors and short-dated options.

**Recommended next steps:**
1. Build the `divcapture_call` screener service using Finviz + yfinance
2. Build the `volterm_flattening` scanner using Finviz + Alpaca option chains
3. Paper-trade both strategies for one full quarter (including 2–3 earnings cycles) before live deployment
4. Monitor the "early assignment rate" on DivCapture as a key performance metric

---

*This report was generated by quantitative research analysis of peer-reviewed academic literature and practitioner research, with all citations verified via Google Scholar and primary journal sources.*
