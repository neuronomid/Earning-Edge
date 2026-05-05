# Strategy 2: Two Complementary Finviz Options Setups

**Purpose:** Replace the current single TradingView screen ("earnings next week + market cap descending") with two complementary Finviz strategies. Each surfaces 5 stocks → system collects 10 candidates → LLM cross-compares and selects the best 5 overall.

**Why two strategies, not one:** A single screen — no matter how good — has a single failure mode. Two complementary screens (one catalyst-driven, one structure-driven) surface stocks from genuinely different selection universes. Even when one strategy has a weak week (no good earnings setups, market-wide volatility spike), the other still produces tradeable candidates. This is portfolio thinking applied to your screening layer.

---

## Strategy A — "Catalyst Confluence" 🥇 RANK #1

**Premise:** The single highest-probability options setup is a stock with **(a)** an earnings catalyst inside the option window **(b)** a confirmed multi-timeframe uptrend **(c)** a track record of beating estimates and **(d)** institutional positioning happening right now. When all four align, you have signal selection edge stacked on top of forced movement. Theta is paid for by the catalyst, and direction is biased by the trend + beat history.

**Best for:** Long calls 14–30 DTE, expiry **after** earnings to capture the move and avoid same-day IV crush traps.

### Filters

| Category | Filter | Value | Why |
|---|---|---|---|
| Descriptive | Exchange | NASDAQ + NYSE | Liquid US options markets |
| Descriptive | Country | USA | Liquidity, regulatory clarity |
| Descriptive | Market Cap | +Mid (over $2B) | Ensures Alpaca has deep option chains |
| Descriptive | Average Volume (3M) | Over 1M | Tight option spreads |
| Descriptive | Price | Over $20 | Avoids penny-option pricing distortions |
| Descriptive | **Optionable** | **Yes** | Mandatory — non-negotiable |
| Descriptive | Earnings Date | **This Week OR Next Week** | Forced catalyst inside option window |
| Descriptive | Analyst Recom. | Buy or better | Sell-side conviction = directional bias |
| Descriptive | Target Price | Above Price | LLM has fundamental upside thesis |
| Fundamental | **EPS Surprise** | Positive | **Beat last quarter** — strongest predictor of next beat |
| Fundamental | **Revenue Surprise** | Positive | Top-line beat (not just cost-cutting) |
| Fundamental | EPS Growth Qtr Over Qtr | Positive | Improving fundamentals trajectory |
| Fundamental | Sales Growth Qtr Over Qtr | Positive | Real business momentum |
| Technical | 20-Day SMA | Price above | Short-term trend confirmed |
| Technical | 50-Day SMA | Price above | Intermediate trend confirmed |
| Technical | 200-Day SMA | Price above | Long-term trend confirmed |
| Technical | Performance (Quarter) | Up | Quarterly momentum positive |
| Technical | RSI (14) | 50 to 70 | Strong but not blown out |
| Technical | Relative Volume | Over 1.3 | Smart money positioning happening **now** |

### Sort

**Primary:** `Relative Volume — Descending`
**Tiebreaker:** `Performance (Quarter) — Descending`

Relative volume is the single best free signal of institutional positioning into earnings. Sort puts the names with the most current participation at the top.

### Finviz URL Template

```
https://finviz.com/screener.ashx?v=111&f=cap_midover,
earningsdate_thisweek,exch_nasd,exch_nyse,fa_epsqoq_pos,
fa_epssurprise_pos,fa_revenuesurprise_pos,fa_salesqoq_pos,
geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,
sh_relvol_o1.5,an_recom_buybetter,targetprice_above,
ta_sma20_pa,ta_sma50_pa,ta_sma200_pa,
ta_perf_qup,ta_rsi_50to70&ft=4&o=-relativevolume
```

> **Note:** Run twice per scan — once with `earningsdate_thisweek`, once with `earningsdate_nextweek` — and dedupe results. Finviz's earnings filter is single-value only.

### Why This Wins
- **Causally-edged stock selection.** EPS Surprise + Revenue Surprise + multi-timeframe uptrend + analyst conviction are four *independent* signals that all point in the same direction. Confluence is rare and it pays.
- **Forced catalyst.** Theta isn't your enemy when earnings is 5–10 days away.
- **No "biggest by market cap" trap.** AAPL/MSFT can still appear, but only if they're actually setting up well — not by default.

### Expected Output
- 5–15 names per week typically.
- Skews toward growth tech, biotech (when reporting), and quality industrials in trending markets.
- Will be **empty** in unusual weeks (slow earnings calendars, broken markets) — that's a feature, not a bug. Strategy B picks up the slack.

---

## Strategy B — "Coiled Setup" 🥈 RANK #2

**Premise:** Not every week has great earnings setups, and not every great options trade requires earnings. This strategy targets stocks in **established long-term uptrends, currently consolidating near highs in bullish chart patterns with compressed volatility**. These are coiled springs — the catalyst doesn't matter because volatility expansion is statistically inevitable when a tight pattern resolves. The trend bias tells you which direction to lean.

**Best for:** Long calls 30–60 DTE on pattern resolution, OR straddles 30–45 DTE if pattern is ambiguous. Gives you more theta runway since there's no specific catalyst date.

### Filters

| Category | Filter | Value | Why |
|---|---|---|---|
| Descriptive | Exchange | NASDAQ + NYSE | Options liquidity |
| Descriptive | Country | USA | Liquidity, regulatory clarity |
| Descriptive | Market Cap | +Mid (over $2B) | Deep option chains |
| Descriptive | Average Volume (3M) | Over 2M | Higher bar — these aren't earnings plays so liquidity matters more |
| Descriptive | Price | Over $20 | Clean option pricing |
| Descriptive | **Optionable** | **Yes** | Mandatory |
| Descriptive | Float Short | Under 20% | Avoid pure squeeze plays (those go in a separate satellite strategy) |
| Descriptive | Insider Transactions | Positive (>0%) | Insiders buying = quality signal |
| Technical | 200-Day SMA | Price above | **Long-term uptrend intact** (most important filter) |
| Technical | 50-Day SMA | Price above | Intermediate trend confirmed |
| Technical | 52-Week High | Within 10% of high | In strong territory, room to break |
| Technical | Performance (Year) | Up | Positive 12-month base rate |
| Technical | Performance (Half Year) | Up | Recent persistence |
| Technical | RSI (14) | 40 to 65 | Pulled back / consolidating, not blown out |
| Technical | **Volatility (Week)** | **Under 4%** | **Compression — fuel for expansion** |
| Technical | **Pattern** | Channel Up OR Triangle Ascending | Bullish consolidation patterns |
| Technical | Beta | Over 1.0 | Will move when market moves |
| Technical | Relative Volume | Over 1.0 | Some current interest, not dead money |

### Sort

**Primary:** `Performance (Half Year) — Descending`
**Tiebreaker:** `Volatility (Week) — Ascending` (tightest squeezes float to top)

Sorting by half-year performance rewards stocks with the most persistent strength — exactly the kind of names where pattern resolutions resolve **upward** because supply has been absorbed over months.

### Finviz URL Template

```
https://finviz.com/screener.ashx?v=111&f=cap_midover,exch_nasd,exch_nyse,
geo_usa,sh_avgvol_o2000,sh_opt_option,sh_price_o20,sh_short_u20,
sh_insidertrans_pos,ta_sma200_pa,ta_sma50_pa,ta_highlow52w_b10h,
ta_perf_yup,ta_perf2_hup,ta_rsi_40to60,ta_volatility_wo4,
ta_pattern_channelup2,ta_beta_o1,sh_relvol_o1
&ft=4&o=-perfhalf
```

> **Note:** Finviz's pattern filter is single-select. Run twice — once with `ta_pattern_channelup2`, once with `ta_pattern_triangleascending` — and dedupe. Same workaround as Strategy A's earnings filter.

### Why This Works
- **No catalyst dependency.** Strategy still works when earnings season is light.
- **Compression-then-expansion** is one of the most documented patterns in markets. Bollinger, NR7, inside bars, triangles — all variations of the same statistical phenomenon. Vol mean-reverts.
- **Trend filter prevents catching falling knives.** Above 200-SMA + above 50-SMA + within 10% of 52w high means you're only screening **proven winners** in tight setups.
- **Pattern filter does heavy lifting.** Finviz's built-in pattern recognition is genuinely useful and saves you from writing your own pattern detection logic.

### Expected Output
- 5–20 names per week typically.
- Skews toward tech, semis, defense, momentum industrials.
- Different stocks than Strategy A 80%+ of the time — exactly what you want for diversity.

---

## How the Two Strategies Complement Each Other

| Dimension | Strategy A | Strategy B |
|---|---|---|
| **Selection edge** | Earnings beat history + analyst conviction | Pattern + trend persistence |
| **Catalyst** | Forced (earnings date) | Volatility expansion (no specific date) |
| **Best option** | Long calls/puts 14–30 DTE | Long calls/straddles 30–60 DTE |
| **IV state** | Elevated pre-earnings | Compressed (pre-breakout) |
| **Theta exposure** | Low (catalyst is near) | Higher (need patience) |
| **Failure mode** | Earnings miss + IV crush | Pattern fails / fakeout |
| **When it shines** | Strong earnings calendar | Trending markets, low VIX |
| **When it struggles** | Slow earnings weeks | Choppy/sideways tape |

The failure modes are **uncorrelated**, which is the whole point. Strategy A's bad weeks are usually Strategy B's good weeks and vice versa. This is the same logic as a diversified factor portfolio — you don't want all your selection edge depending on a single market regime.

---

## How the LLM Should Compare 10 → 5

When the system pipes 10 candidates (5 from A, 5 from B) into Claude Opus 4.7 Thinking, the prompt should explicitly ask for cross-strategy comparison along these axes:

1. **Setup quality** — How clean is the technical structure? How strong is the catalyst/pattern?
2. **Option chain quality** — Spread tightness, open interest, IV state vs historical norm.
3. **Risk/reward asymmetry** — Where's the stop? Where's the target? What's the implied move vs expected?
4. **Confluence with macro/sector** — Is the broader sector trending the same way?
5. **Independence** — Final 5 should not all come from the same sector or factor exposure.

The LLM should be allowed to pick **0–5 stocks** depending on quality. If only 2 setups are genuinely strong, recommend 2. The "always pick 5" rule is what generates noise. Quality > quantity.

---

## Implementation Notes for Your PRD

### Sections to Update

| PRD Section | Current | Change To |
|---|---|---|
| 1. Product Summary | "Earnings Options Recommendation Agent" | "Setup-Driven Options Recommendation Agent" |
| 2. Core Question | "Among largest earnings next week..." | "Across catalyst-driven and structure-driven setups, which option contract has best opportunity..." |
| 3.1 Workflow | Single TradingView screen | **Run Strategy A → Run Strategy B → Merge → Dedupe → LLM cross-compare → Pick 0–5** |
| 5. TradingView Integration | TradingView screener | **Replace with Finviz screener (entire section rewrite)** |
| 5.4 Required Fields | Ticker, Market Cap, Earnings Date | Add: **EPS Surprise, Revenue Surprise, Analyst Recom, Target Price, RSI, Pattern, Volatility (Week), Float Short, Insider Trans** |
| 27.3 Critical Fields | (existing) | Add: **strategy_source** field tracking which strategy surfaced each candidate (for V2 feedback agent attribution) |

### Browser Automation Notes

- Finviz is **less Playwright-friendly than TradingView** — but the URL parameter system is *more* automation-friendly. You can construct full filter URLs directly and just `page.goto(url)` then parse the HTML table. No need to click through filter UI.
- Finviz table is server-rendered HTML, so accessibility tree extraction works perfectly.
- For Strategy A and B, run **separate page loads with different URLs**, then merge results.
- Cache results for 5–10 minutes to avoid hammering Finviz (be a good citizen).
- Finviz Elite is **not required** for these filters — all are free-tier accessible.

### V2 Feedback Agent Integration

Tag each recommendation with the source strategy. After 8–12 weeks of data:
- If Strategy A is producing 70% of winners → reweight in favor of A
- If Strategy B's pattern-resolution trades are systematically failing → tighten the pattern filter or add ADX-equivalent confirmation
- Per-strategy win rate, avg return, and avg holding period become your feedback signal

This is the analytical foundation V2 needs.

---

## Final Ranking & Recommendation

| Rank | Strategy | Confidence | Default Weight |
|---|---|---|---|
| 🥇 #1 | **Catalyst Confluence (A)** | High | 50% — primary |
| 🥈 #2 | **Coiled Setup (B)** | Medium-High | 50% — diversifier |

Both strategies pull their weight. Strategy A is ranked higher because **the combination of earnings beat history + analyst conviction + multi-timeframe trend is the closest thing to documented edge in retail options screening**. Strategy B has a slightly lower base rate because pattern resolutions are noisier than earnings reactions, but its compounding benefit when combined with A is substantial — together they have lower selection variance than either alone.

**Bottom line for your PRD:** Run both, every Monday. Pipe 10 candidates to Claude. Trust the LLM to pick 0–5 based on cross-strategy comparison. Track results per strategy. In 12 weeks you'll know which one to weight heavier — and that's data nobody else trading retail options has.
