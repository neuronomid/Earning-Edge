# Strategy 2: Two Complementary Finviz Options Setups

**Purpose:** Use Finviz as the primary visible screener, collect 5 candidates from each of two complementary screens, score the 10-stock universe, pass only the best 4 scored finalists to the LLM, and send the best option contract recommendation to the user.

This strategy is intentionally broad at the screener layer. Finviz should identify liquid, visible candidate pools; the system should validate earnings dates, market data, news, fundamentals, option chains, liquidity, spreads, IV, and trend quality downstream. Over-filtering in Finviz creates false "no trade" weeks before the scoring system has a chance to do its job.

---

## Strategy A - Catalyst Confluence

**Role:** Primary earnings catalyst screen.

**Premise:** Earnings create forced movement, but the screener should not try to prove the entire trade. The highest-value first step is to capture the largest USA-listed companies reporting next week, then let the scoring engine and LLM decide whether the option chain, trend, sentiment, and earnings context justify a trade.

**Required Finviz URL:**

```text
https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap
```

**Process:** Use the top 5 visible rows from this URL.

### Filters

| Category | Filter | Value | Why |
|---|---|---|---|
| Descriptive | Earnings Date | Next Week | Keeps the catalyst inside the option decision window |
| Descriptive | Country | USA | Better options liquidity and data coverage |
| Sort | Market Cap | Descending | Starts with the deepest, most institutionally followed names |

### Why It Changed

The previous Strategy A used earnings plus optionable, price, volume, analyst, surprise, growth, trend, RSI, and relative-volume filters in Finviz. That is too strict for an automated weekly bot. On May 5, 2026, the broad required URL returned hundreds of rows, while the over-filtered catalyst screen returned only two rows before validation. The right place to reject bad setups is the scoring stage, not the initial visible screen.

### Downstream Checks

The system should validate:

- earnings date from Finnhub/yfinance when available
- optionability and option-chain depth from the options provider
- bid/ask spread, open interest, volume, IV, delta, breakeven, expiry fit
- recent returns, relative strength vs SPY/QQQ/sector, volume expansion
- recent news, guidance, analyst changes, company-specific catalysts
- fundamentals and earnings quality where data is available

---

## Strategy B - Liquid Momentum Setup

**Role:** Structure-driven diversifier.

**Premise:** Some weeks have weak earnings setups. Strategy B finds liquid, optionable, higher-beta stocks already in established uptrends and near their highs. It is not required to have an earnings catalyst; it exists to surface tradeable momentum setups that may have cleaner options than the earnings names.

**Finviz URL:**

```text
https://finviz.com/screener?v=111&f=cap_midover,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,ta_sma50_pa,ta_sma200_pa,ta_highlow52w_b20h,ta_beta_o1,ta_rsi_40to70&o=-relativevolume
```

**Process:** Use the top 5 visible rows from this URL.

### Filters

| Category | Filter | Value | Why |
|---|---|---|---|
| Descriptive | Country | USA | Better options liquidity and data coverage |
| Descriptive | Market Cap | +Mid, over $2B | Avoids fragile microcap option chains |
| Descriptive | Average Volume | Over 1M | Keeps stock liquidity acceptable |
| Descriptive | Price | Over $20 | Avoids low-price option noise |
| Descriptive | Optionable | Yes | Mandatory for contract selection |
| Technical | 50-Day SMA | Price above | Intermediate trend confirmation |
| Technical | 200-Day SMA | Price above | Long-term trend confirmation |
| Technical | 52-Week High | Within 20% | Keeps the setup near leadership territory |
| Technical | Beta | Over 1 | Enough movement potential for options |
| Technical | RSI | 40 to 70 | Avoids both weak trends and severely overbought names |
| Sort | Relative Volume | Descending | Brings current participation to the top |

### Why It Changed

The previous Strategy B combined pattern, insider, short-float, low-volatility, 52-week-high, beta, relative-volume, and performance filters. In live Finviz, that exact combination produced `0 Total`, so the bot had no structure-driven candidates. The revised filter set is the sweet spot: enough constraints to avoid low-quality names, but broad enough to produce a usable pool in normal markets.

Pattern and volatility are still useful, but they should be downstream scoring inputs or optional tie-breakers, not hard Finviz gates. Finviz pattern filters can be noisy and can collapse the candidate universe unpredictably.

---

## Merge, Score, and LLM Flow

1. Run Strategy A and keep the top 5 visible rows.
2. Run Strategy B and keep the top 5 visible rows.
3. Merge and dedupe by ticker, preserving Strategy A when the same ticker appears in both.
4. Enrich every candidate with market data, news, earnings data, and option chains.
5. Score all merged candidates.
6. Pass only the best 4 scored candidates to the LLM.
7. The LLM chooses one ticker and one exact contract from the supplied option-chain candidates, or returns no trade.

The LLM should not invent contracts. It can only choose from contracts that survived the option-chain and hard-filter process.

### Top-4 Finalist Ranking

Rank candidates for the LLM by:

1. final opportunity score
2. data confidence score
3. direction score
4. option contract viability and liquidity

This keeps LLM cost and attention focused on the highest-quality setups while still preserving the full 10-candidate audit trail in exported results.

---

## Alternative Button Flow

The first Telegram recommendation should assess the highest-ranked finalist. If the user presses **Alternative**, the system should not merely list stored alternatives. It should run the same LLM decision/reporting flow constrained to the next-best finalist that has not already been shown.

Expected behavior:

1. First scan: assess finalist #1 and send the full report.
2. First Alternative click: assess finalist #2 and send a full report in the same format.
3. Second Alternative click: assess finalist #3 and send a full report.
4. Continue until no stored finalists remain, then tell the user no further qualified alternatives are available.

The alternative flow should reuse stored finalists, option chains, and scoring artifacts from the original run. Before the LLM makes the alternative decision, refresh market/news context where the configured APIs are available; if those calls fail, fall back to the stored run artifacts. It should not re-run the whole screener unless the original run is stale.

---

## Failure Handling

Finviz automation must stay retry-safe and stateless:

1. load the page
2. retry the page once
3. retry with a clean browser context
4. if Finviz is still unusable, fall back to backup earnings sources

If Finviz fails and backup earnings candidates are used, surface this exact warning:

```text
⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.
```

A legitimate Finviz `0 Total` page is not a browser failure. It should return an empty candidate list for that strategy and let the other strategy continue.

---

## Analyst Notes

The strategy should favor option trades where the stock setup and contract setup agree. A good stock with a bad option chain is not a trade. A liquid contract on a weak stock is also not a trade.

Important rejection reasons:

- spreads are too wide
- open interest or volume is too thin
- IV is too expensive relative to expected move
- breakeven is unrealistic
- earnings timing creates unacceptable IV-crush risk
- trend and news conflict
- market or sector context is moving against the setup
- data confidence is low

The goal is not to force a weekly trade. The goal is to reliably find the best available setup and say no trade when the top setup does not clear the bar.
