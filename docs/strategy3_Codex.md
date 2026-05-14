# Strategy 3-5 Research And Integration Report

Date: 2026-05-13

Author: Codex GPT-5.5, lead architect/moderator

Output target: `docs/strategy3_Codex.md`

## 1. Executive Summary

The current Earning-Edge candidate pipeline has two live strategy sources:

- Strategy 1: `catalyst_confluence`
- Strategy 2: `coiled_setup`

The objective is to add three more short-term options strategies so the final system has five total strategies. Each strategy should contribute its top five candidates, producing a 25-candidate deterministic pool:

- 5 candidates from `catalyst_confluence`
- 5 candidates from `coiled_setup`
- 5 candidates from new Strategy 3
- 5 candidates from new Strategy 4
- 5 candidates from new Strategy 5

All 25 candidates should then pass through the existing deterministic market-data, options-chain, scoring, sizing, veto, and ranking flow. Only the top four scored candidates should be passed to the LLM for deeper qualitative analysis. The LLM should review risk, context, and trade rationale for finalists only; it should not replace deterministic scoring or analyze all 25 candidates.

After ten independent research agents, source review, and consensus moderation, the selected new strategies are:

1. Strategy 3: `activist_13d_followthrough`
2. Strategy 4: `form4_cluster_buy`
3. Strategy 5: `post_earnings_drift`

The first two are deliberately non-technology focused and use official SEC filing data plus existing market/options sources. The third is broad-market but distinct from the existing earnings catalyst strategy because it trades post-earnings drift after the event, not pre-earnings setup.

The recommended implementation order is:

1. Implement `post_earnings_drift` first if the goal is fastest integration, because it reuses the existing earnings, market-data, and options pipeline most directly.
2. Implement `activist_13d_followthrough` second, because it is the strongest new non-tech event signal but needs an SEC event parser.
3. Implement `form4_cluster_buy` third, because it uses the same SEC infrastructure but requires more transaction-level parsing.

## 2. Current System Summary

This section is based on direct codebase inspection of the current repository. It does not assume unobserved architecture.

### Existing candidate entry point

Runtime candidate selection enters through:

- `app/pipeline/steps/candidates.py`

`CandidateSelectionStep` calls `MultiStrategyCandidateService.get_candidates()` and returns the merged candidate records and strategy reports to the pipeline.

### Existing multi-strategy service

The live multi-strategy merge point is:

- `app/services/multi_strategy_service.py`

`MultiStrategyCandidateService` currently owns two services:

- `CandidateService`, used for `catalyst_confluence`
- `CoiledSetupCandidateService`, used for `coiled_setup`

`get_candidates()` currently runs both services with `asyncio.gather(..., return_exceptions=True)`, builds `StrategyRunReport` objects, merges the rows, and deduplicates by ticker. The merge preserves `catalyst_confluence` first and then dedupes `coiled_setup` behind it.

The service currently treats a strategy as failed only when that service raises. This matters because `CoiledSetupCandidateService` catches Finviz errors and returns an empty tuple rather than raising.

### Existing Strategy 1: `catalyst_confluence`

Implementation anchor:

- `app/services/candidate_service.py`

Strategy source:

- `CATALYST_STRATEGY_SOURCE = "catalyst_confluence"`

Finviz strategy definition:

- `app/services/finviz/strategies.py`

Visible Finviz URL represented by the strategy:

```text
https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap
```

`CandidateService.get_top_five()` uses the Finviz runner with strategy A filters, retrieves the top five visible rows, validates earnings dates and quality checks, and falls back to backup earnings sources when Finviz fails or returns no usable rows.

Backup sources currently wired in `get_multi_strategy_service()` are:

- `YFinanceEarningsSource`
- `FinnhubEarningsSource`

If Strategy 1 falls back to backup candidates, the warning text must remain exactly:

```text
⚠️ Finviz did not load correctly, so I used backup earnings data for this scan.
```

Current behavior preserves visible Finviz rows when backup earnings dates conflict, attaching validation notes instead of silently dropping the row.

### Existing Strategy 2: `coiled_setup`

Implementation anchor:

- `app/services/coiled_setup_service.py`

Strategy source:

- `COILED_STRATEGY_SOURCE = "coiled_setup"`

Finviz strategy definition:

- `app/services/finviz/strategies.py`

Visible Finviz URL represented by the strategy:

```text
https://finviz.com/screener?v=111&f=cap_midover,geo_usa,sh_avgvol_o1000,sh_opt_option,sh_price_o20,ta_sma50_pa,ta_sma200_pa,ta_highlow52w_b20h,ta_beta_o1,ta_rsi_40to70&o=-relativevolume
```

`CoiledSetupCandidateService.get_top_five()` calls the Finviz runner and returns top rows. It logs Finviz errors and degrades to an empty tuple instead of raising.

### Finviz stack

The public Finviz browser and query stack lives in:

- `app/services/finviz/query.py`
- `app/services/finviz/browser.py`
- `app/services/finviz/runner.py`
- `app/services/finviz/strategies.py`

`FinvizQuery.to_url()` builds public screener URLs. `FinvizBrowserClient.capture_snapshot()` loads the visible screener page and extracts rows from the public table.

The browser retry ladder already follows the required stateless pattern:

1. retry the same page load once
2. retry with a clean browser context
3. let the service-level fallback handle failure

No hidden Finviz API, login, cookie dependency, or persistent authentication assumption should be introduced.

### Candidate models and strategy catalog

Key files:

- `app/services/candidate_models.py`
- `app/services/strategy_catalog.py`

`StrategySource` is currently a narrow literal with only:

```python
Literal["catalyst_confluence", "coiled_setup"]
```

`StrategyRunReport.strategy_source` and `CandidateRecord.strategy_source` depend on that type. The strategy catalog currently defines only the two live strategies.

Adding three strategies requires widening this strategy-source model and extending the catalog.

### Market-data sources

Key files:

- `app/services/market_data/service.py`
- `app/services/market_data/yf_client.py`
- `app/services/market_data/av_client.py`

The market-data service uses yfinance and Alpha Vantage. It computes stock returns, relative strength, volume comparisons, sector ETF context, SPY/QQQ context, and related market fields.

Existing sector ETF mapping can support non-tech strategies through sector-aware scoring and concentration controls.

### Options data sources

Key files:

- `app/services/options/service.py`
- `app/services/options/alpaca_client.py`
- `app/services/options/yfinance_client.py`

The options service uses Alpaca if credentials are configured and otherwise falls back to yfinance. Alpaca snapshots can provide quote, trade, greeks, volume, open interest, and implied volatility when available. yfinance provides option chains but has weaker greeks coverage.

Current contract support is single-leg oriented. The scoring types include:

```python
Strategy = Literal["long_call", "long_put", "short_put", "short_call"]
```

This is important because several research agents preferred debit spreads, calendars, or iron condors. Those structures are better risk-defined option implementations, but the current code does not appear to model multi-leg option strategies yet. The implementation-ready recommendation is to select single-leg long calls or long puts for v1 of the new event strategies, while separately tracking a backlog item to add multi-leg spread support before live spread recommendations.

### News and SEC sources

Key files:

- `app/services/news/service.py`
- `app/services/news/sources.py`

Existing news sources include:

- `FinnhubNewsSource`
- `SecEdgarNewsSource`

`SecEdgarNewsSource` currently fetches company tickers and company submissions, accepts selected forms such as `8-K`, `10-Q`, `10-K`, `10-Q/A`, `10-K/A`, and `4`, and returns news-style articles. It is not currently a general event parser for Schedule 13D or detailed Form 4 transaction clustering.

The selected SEC-based strategies should reuse the existing EDGAR source direction where practical, but they need a more structured SEC filing adapter or service.

### Existing scoring system

Key files:

- `app/pipeline/steps/scoring.py`
- `app/scoring/final.py`
- `app/scoring/direction.py`
- `app/scoring/contract.py`
- `app/scoring/confidence.py`
- `app/scoring/vetoes.py`
- `app/scoring/expiry.py`
- `app/scoring/strategy_select.py`

`score_candidate()` combines directional and contract scores, selects viable contracts, applies confidence and veto logic, and produces deterministic final scores.

`combine_scores()` currently weights:

- direction: 45%
- contract: 55%

The current direction scorer is generic. It uses trend, relative strength, volume, earnings expectation, market/sector environment, price structure, and confidence fields. It does not yet have strategy-specific event-signal scoring for 13D filings, Form 4 clusters, or post-earnings drift.

Current missing-earnings logic is special-cased for `coiled_setup` only:

- `app/scoring/confidence.py`
- `app/scoring/vetoes.py`

The new 13D and Form 4 strategies do not require upcoming earnings dates. The missing-earnings exemption must be expanded from a single `coiled_setup` check to an explicit set of no-earnings-required strategy sources.

### LLM analysis flow

Key files:

- `app/pipeline/orchestrator.py`
- `app/pipeline/steps/decide.py`
- `app/llm/schemas.py`
- `app/llm/router.py`

The orchestrator defines:

```python
DECISION_FINALIST_LIMIT = 4
```

`PipelineOrchestrator.evaluate_batch()` performs preliminary deterministic analysis, selects decision finalists, refreshes only those finalists with live news, and passes only the selected finalists to the decision stage.

`LLMDecisionStep` builds the LLM decision input from the candidates it receives. `validate_llm_decision()` constrains the LLM output so the selected ticker and selected contract must be among the visible deterministic candidates and contracts. It recomputes deterministic contract and final scores and prevents unsupported confidence inflation.

This design already matches the required principle: the LLM reviews finalists after deterministic scoring. The expansion to 25 candidates should preserve this behavior.

### Current limitations relevant to new strategies

- `StrategySource` only includes two strategy names.
- `StrategyRunReport` and strategy catalog are two-strategy oriented.
- `MultiStrategyCandidateService` is hard-coded to two services rather than a strategy runner list.
- Missing-earnings veto and confidence logic exempt only `coiled_setup`.
- `CandidateRecord` does not appear to carry structured event metadata such as filing accession, event date, event strength, Form 4 transaction fields, or post-earnings drift state.
- Existing SEC source is news/article oriented, not a structured filing event parser.
- Current option strategy model does not support multi-leg spreads, calendars, or iron condors.
- Tests currently cover two-strategy behavior and should be expanded to enforce 25-candidate and top-four finalist behavior.

## 3. Research Method

Ten independent research agents were spawned as requested. Each agent was instructed to independently research short-term options strategies, use recent and credible sources, evaluate data availability, and propose strategies that fit the current system and the free/no-login/no-CAPTCHA constraint.

The agents reviewed sources including:

- Academic and SSRN papers on activism, insider trading, earnings drift, options volume, volatility risk premia, and event-driven options.
- SEC documentation for EDGAR APIs, Schedule 13D/13G filings, Form 3/4/5 reporting, and ownership XML.
- Public data-provider documentation for Alpaca, yfinance, Finnhub, Alpha Vantage, Cboe, FDA, and ClinicalTrials.gov.
- Practitioner research on earnings implied volatility, IV crush, debit spreads, calendars, and options liquidity.

The consensus process judged every idea against these criteria:

- Evidence quality: whether the strategy had support from credible research or official documentation.
- System fit: whether it can use Finviz, Alpaca, Alpha Vantage, yfinance, Finnhub, SEC EDGAR, or another free and practical source.
- Automation reliability: whether the source is public, no-login, no-CAPTCHA, and realistic for scheduled automated use.
- Short-term options fit: whether the trade can normally resolve inside four weeks.
- Non-tech coverage: whether at least two of the selected strategies focus outside technology.
- Candidate production: whether the strategy can rank and return a top-five candidate set.
- Implementation cost: whether it can be integrated without redesigning the whole pipeline.
- Risk control: whether it avoids fragile, highly binary, or overfit signals.
- Distinctness: whether it adds a genuinely different signal from the current earnings catalyst and coiled setup strategies.

Consensus was not computed as a vote count. Weak assumptions were challenged, strategies dependent on unavailable data were rejected, and overlapping ideas were merged into cleaner implementable strategy definitions.

## 4. Strategies Proposed by Agents

### Activist 13D follow-through

Status: accepted as Strategy 3.

Basic description: identify fresh activist Schedule 13D filings, especially non-tech issuers where public activist disclosure can force repricing over the next several sessions. Trade short-dated bullish options only after price and liquidity confirmation.

Supporting reasoning: multiple agents identified hedge-fund activism and Schedule 13D disclosures as a strong event-driven signal. The 2024 beneficial ownership reporting modernization shortened the initial Schedule 13D deadline to five business days, improving signal freshness for public-data users.

Required data:

- New SC 13D or 13D/A filings
- Issuer ticker and CIK mapping
- Filer identity
- Stake percentage
- Item 4 intent language
- Filing date and accession number
- Stock liquidity, market cap, sector, and optionability
- Post-filing price and volume confirmation

Source requirements:

- Primary: SEC EDGAR APIs and public filing documents
- Existing support: yfinance, Alpaca, Finviz, Finnhub news
- No paid or login-gated source required

Strengths:

- Strong non-tech fit.
- Official filing data.
- Distinct from current strategies.
- Event horizon fits 14-28 DTE options.
- Good candidate for deterministic scoring.

Weaknesses:

- Needs structured EDGAR parsing.
- Requires careful exclusion of passive 13G-style ownership changes.
- Activist names may gap before the system can enter.
- Some targets have poor option liquidity.

Decision: accepted. It had strong evidence support, good data-source fit, and high non-tech value.

### Form 4 insider purchase cluster

Status: accepted as Strategy 4.

Basic description: identify clusters of open-market insider purchases reported on Form 4, then trade short-dated bullish options when the cluster occurs after a drawdown or near a technical recovery point.

Supporting reasoning: agents converged on the idea that insider buying is more useful when filtered to open-market buys, multiple insiders, meaningful dollar size, and weaker-information environments. Official Form 4 data is public and near-real-time.

Required data:

- Form 4 filing metadata
- Transaction code `P`
- Insider role
- Transaction date and filing date
- Shares and dollar value purchased
- Cluster count across insiders and days
- Stock drawdown/recovery context
- Option chain liquidity

Source requirements:

- Primary: SEC ownership XML or SEC insider transaction data sets
- Existing support: yfinance, Alpaca, Finviz
- Optional context: Finnhub/SEC news

Strengths:

- Strong non-tech fit.
- Official data.
- Less dependent on fragile web scraping.
- Works across industrials, energy, financials, healthcare services, consumer, and other non-tech groups.

Weaknesses:

- Needs exact transaction-code parsing to avoid grants, exercises, sales, and tax withholding.
- Filing can occur after the transaction date, reducing immediacy.
- Some clusters occur in illiquid small caps.
- Insider buys can be symbolic rather than economically meaningful.

Decision: accepted. It is practical and distinct, especially when constrained to clustered open-market buys with option-liquidity filters.

### Post-earnings drift

Status: accepted as Strategy 5.

Basic description: trade directional continuation after earnings, using the first one to three post-earnings sessions, gap direction, close location, relative volume, surprise/guidance proxy, and option liquidity.

Supporting reasoning: post-earnings announcement drift remains one of the better-documented short-horizon underreaction effects. It is distinct from the existing `catalyst_confluence` strategy, which identifies pre-earnings candidates.

Required data:

- Recently reported earnings event
- Earnings timing
- Gap direction and magnitude
- Close location and follow-through
- Relative volume
- Surprise or guidance proxy when available
- Option chain liquidity

Source requirements:

- Existing: Finnhub earnings calendar, yfinance, Alpha Vantage, SEC 8-K Item 2.02, Alpaca/yfinance options
- Finviz may be used for public liquidity/optionability screens, but post-earnings event logic should not depend on hidden Finviz endpoints.

Strengths:

- Strong research base.
- Short holding period.
- Reuses current earnings and market-data infrastructure.
- Can handle bullish and bearish candidates.

Weaknesses:

- Can enter after the best gap has already occurred.
- Requires stale-event filters.
- Surprise data may be incomplete on free plans.
- IV crush and wide spreads can damage long options if not filtered.

Decision: accepted. It is the easiest of the selected strategies to integrate and complements the existing pre-earnings scan.

### Buyback authorization drift

Status: rejected for this three-strategy slate; recommended for future backlog.

Basic description: identify new or enlarged repurchase authorizations and trade bullish follow-through when authorization size is meaningful relative to market cap.

Supporting reasoning: buyback announcements can create positive abnormal returns, especially when size is material and the market underreacts.

Required data:

- 8-K, 10-Q, 10-K, or press-release text
- Repurchase authorization amount
- Market cap
- Balance sheet and cash-flow context
- Option liquidity

Source requirements:

- SEC EDGAR filings
- yfinance/Alpha Vantage financial data
- Finviz/yfinance liquidity data

Strengths:

- Non-tech friendly.
- Uses public filings.
- Fits short-term bullish options when the announcement is material.

Weaknesses:

- Text classification is harder than 13D or Form 4 parsing.
- Buyback language is less standardized across filings.
- Actual repurchase execution may never happen.
- Signal can be confounded with earnings or capital structure news.

Decision: rejected for now. It is plausible but less implementation-ready than 13D, Form 4, and post-earnings drift.

### Financing shock puts

Status: rejected for this slate; possible future bearish SEC-event strategy.

Basic description: identify dilutive offerings, discounted financings, and convertible issuance and trade bearish follow-through.

Supporting reasoning: discounted financing can pressure near-term prices, especially in small/mid-cap issuers.

Required data:

- 8-K/S-3/prospectus supplement filings
- Offering size and discount
- Warrants or convertibles
- Float and market cap
- Option liquidity

Source requirements:

- SEC EDGAR
- yfinance/Finviz liquidity

Strengths:

- Public data.
- Clear short-term event.
- Non-tech and healthcare-heavy coverage.

Weaknesses:

- Many candidates are small, illiquid, or hard to trade with options.
- Downside gap can occur before entry.
- Can overlap with distressed or binary biotech risk.
- Requires careful parsing of financing terms.

Decision: rejected for now. It is too fragile as one of the first three additions.

### Generic non-tech 8-K follow-through

Status: merged into future EDGAR-event backlog, not selected directly.

Basic description: classify fresh 8-K filings across non-tech sectors and trade directional continuation.

Supporting reasoning: some research supports continued drift after material disclosures.

Required data:

- Fresh 8-K filings
- Filing item classification
- Exhibit parsing
- Tone/event classification
- Price/volume confirmation

Source requirements:

- SEC EDGAR
- Finnhub news
- yfinance/Alpaca/Finviz

Strengths:

- Broad non-tech event source.
- Public and automatable.

Weaknesses:

- Too broad for initial implementation.
- Requires event taxonomy and text classification.
- Filing item alone can be noisy.

Decision: rejected as a standalone v1 strategy. The stronger specific EDGAR strategies are 13D and Form 4.

### Cyclical industry momentum

Status: rejected/deferred.

Basic description: rank non-tech sectors and industries by relative strength, then select optionable stocks in leading groups.

Supporting reasoning: industry momentum has research support and can work over weeks.

Required data:

- Sector and industry returns
- Stock relative strength
- Trend filters
- Option liquidity

Source requirements:

- Finviz sector/industry screens
- yfinance ETF and stock history
- Alpaca/yfinance options

Strengths:

- Easy to implement.
- Non-tech friendly.
- Uses existing sources.

Weaknesses:

- Overlaps with the current `coiled_setup` strategy.
- Less event-driven.
- More vulnerable to broad-market reversals.
- Adds less orthogonal information than SEC event strategies.

Decision: rejected for this slate because it is too close to trend/relative-volume screening already present in Strategy 2.

### Option-flow confirmed breakout

Status: rejected/deferred as standalone; useful as confirmation.

Basic description: use unusual call/put volume, open interest, skew, and price breakout confirmation to rank short-term options candidates.

Supporting reasoning: options activity can contain information about future stock returns, but research is mixed and signed order flow is often unavailable from free sources.

Required data:

- Contract-level volume and open interest
- Call/put imbalance
- IV and spreads
- Price breakout/breakdown

Source requirements:

- Alpaca option snapshots when available
- yfinance option chains as fallback
- Finviz breakout screens

Strengths:

- Directly option-aware.
- Could improve contract selection.

Weaknesses:

- Free data lacks reliable signed flow.
- Raw volume can be hedging, closing, or stale.
- Susceptible to false positives and scanner-like noise.

Decision: rejected as a standalone top-five engine. Use option-flow proxies as scoring inputs or confirmation only.

### Defensive premium fade

Status: rejected/deferred.

Basic description: sell short-dated defined-risk premium in lower-gap non-tech sectors when implied volatility is elevated relative to realized volatility and no catalyst is scheduled.

Supporting reasoning: volatility risk premium can be positive, and lower-gap sectors may be better candidates for premium-selling automation.

Required data:

- Implied volatility
- Realized volatility
- Term structure
- Earnings and news blackout
- Option liquidity

Source requirements:

- Alpaca/yfinance options
- yfinance prices
- SEC/Finnhub news
- Finviz sectors

Strengths:

- Non-tech friendly.
- Distinct from event-driven long premium.

Weaknesses:

- Current system does not model multi-leg iron condors or credit spreads.
- Short-option assignment and tail risk need stronger risk controls.
- IV history is weak on free sources.

Decision: rejected for current architecture. Reconsider after multi-leg spreads and stronger IV history exist.

### Healthcare regulatory skew

Status: rejected/deferred.

Basic description: use FDA advisory committee events or trial readouts to trade defined-risk options in healthcare names.

Supporting reasoning: FDA events are public and can cause strong short-term repricing.

Required data:

- FDA event date
- Affected issuer and product mapping
- Regulatory status
- Option skew and liquidity

Source requirements:

- FDA advisory committee calendar
- ClinicalTrials.gov API
- SEC filings and press releases
- yfinance/Alpaca options

Strengths:

- Non-tech.
- Event-driven.
- Short-term.

Weaknesses:

- Sparse candidate set.
- Mapping events to tickers is operationally fragile.
- Binary gap risk is high.
- PDUFA dates are not always cleanly available from a single public source.

Decision: rejected for this slate. It may be useful as a specialized later strategy, not as a general top-five daily engine.

### Earnings IV calendar or pre-earnings volatility strategy

Status: rejected/deferred.

Basic description: exploit front/back IV term-structure around earnings using calendars or related structures.

Supporting reasoning: pre-earnings IV behavior is well known and can create structured options opportunities.

Required data:

- Confirmed earnings dates
- Front/back ATM IV
- Historical earnings realized moves
- Option spreads and open interest

Source requirements:

- yfinance/Alpaca options
- Finnhub/yfinance earnings calendar

Strengths:

- Directly option-specific.
- Uses existing earnings universe.

Weaknesses:

- Current system does not support multi-leg calendars.
- Requires reliable IV history for good ranking.
- Overlaps the current earnings-focused Strategy 1.

Decision: rejected for this slate. Revisit after multi-leg support.

### 0DTE, max-pain, pinning, rumor, and paid-flow strategies

Status: rejected.

Reasons:

- 0DTE strategies require intraday execution, gamma/risk monitoring, and continuous supervision.
- Max-pain and pinning are too noisy for deterministic candidate generation.
- M&A rumor strategies depend on fragile or proprietary sources.
- Paid unusual-options-flow, dark pool, or social scanners violate the free/no-login source constraints.

## 5. Scholastic Consensus

### Strongest agreements

The strongest cross-agent agreement was around three families:

1. SEC event strategies with official filing data.
2. Post-earnings drift strategies.
3. Options-flow or volatility signals as confirmation rather than standalone candidate engines.

Within SEC events, the cleanest and most supported subtypes were:

- Activist Schedule 13D follow-through.
- Clustered open-market insider purchases on Form 4.

These were preferred over generic 8-K classification because they have more structured filing forms and clearer event meaning.

### Main disagreements

Agents disagreed on whether premium-selling volatility strategies should be selected. Some argued for defensive-sector credit spreads or iron condors. This was rejected for the initial slate because the current code models single-leg strategies, not multi-leg defined-risk spreads, and because short-option risk needs stronger controls.

Agents also disagreed on whether healthcare regulatory events should be one of the three. The idea is real and non-tech, but the consensus process rejected it because source mapping is sparse and fragile, and the event distribution is too binary for a general top-five daily pipeline.

Agents disagreed on pure option-flow strategies. The final consensus was that options volume, open interest, spreads, and IV should improve contract scoring and signal confirmation, but free data is not reliable enough for a standalone top-five strategy based only on flow.

### Weak assumptions challenged

The following assumptions were rejected:

- That a strategy is practical just because it is academically interesting.
- That option volume alone is a reliable signal without signed flow or event context.
- That free option data is sufficient for sophisticated volatility surface arbitrage.
- That the current system can recommend calendars, verticals, and iron condors without schema changes.
- That a broad 8-K text classifier is a lower-risk first step than structured 13D/Form 4 parsers.
- That the pipeline should fabricate candidates to reach 25 when a live strategy has fewer than five valid candidates.

### Ideas preserved

The preserved components are:

- Official SEC filing events.
- Non-tech issuer emphasis.
- Post-event earnings drift.
- Strict option liquidity filters.
- Deterministic top-five per strategy.
- Existing top-four LLM finalist gate.
- Strategy-specific deterministic scoring before LLM review.

### Why the final three were selected

`activist_13d_followthrough` was selected because it is non-tech friendly, grounded in official filings, supported by activism research, and has a short event window that fits 14-28 DTE options.

`form4_cluster_buy` was selected because clustered open-market insider buying is structured, public, non-tech friendly, and distinct from both the current pre-earnings and technical coiled setup strategies.

`post_earnings_drift` was selected because it is the strongest low-friction addition. It reuses existing earnings and market-data infrastructure, adds post-event behavior, and can produce both bullish and bearish short-term options candidates.

## 6. New Strategy 3

### Strategy name

`activist_13d_followthrough`

### Core thesis

Fresh activist Schedule 13D filings can trigger short-term repricing as the market incorporates a new concentrated owner, activist intent, and potential operational, governance, strategic, or capital-allocation pressure. The opportunity is strongest when the filing is recent, the stake is meaningful, Item 4 language is active rather than passive, the stock is liquid and optionable, and price/volume confirm the filing.

### Stock universe

US-listed common stocks with listed options, sufficient price and volume, and public SEC filing coverage.

Recommended v1 filters:

- US-listed operating company.
- Optionable.
- Stock price above approximately $15-$20.
- Average daily volume above approximately 750k-1M shares.
- Market cap above approximately $500M.
- Avoid extreme microcaps and distressed issuers.
- Avoid names with no viable options contract after spread/open-interest filters.

### Sector focus

Non-technology by design. Preferred sectors:

- Industrials
- Consumer discretionary and staples
- Energy
- Materials
- Financials
- Healthcare services and equipment
- Real estate, if option liquidity is adequate

Technology names should not be banned, but they should be deprioritized so the strategy remains a non-tech contributor. If a tech issuer appears, it should need a materially stronger event score to outrank non-tech candidates.

### Why it fits short-term options

The event date is discrete and public. The expected trade resolution is the market's first repricing phase after the filing, not the full activist campaign. This fits a 5-15 trading-day hold using 14-28 DTE options.

### Data requirements

- Recent SC 13D and substantive SC 13D/A filings.
- Filing date and accession number.
- Issuer CIK and ticker.
- Filer name.
- Stake percentage.
- Item 4 intent text or a simplified active-intent flag.
- Filing URL for audit.
- Price and volume behavior since filing.
- Sector and market cap.
- Optionability and option-chain liquidity.

### Data sources

Primary sources:

- SEC EDGAR APIs and public filing documents.
- Existing yfinance market-data path.
- Existing Alpaca/yfinance options path.

Supporting sources:

- Finviz public screener pages for liquidity, sector, and optionability confirmation.
- Finnhub company news for context, not as the primary signal.

No new paid or login-gated source is required.

### Candidate selection rules

The strategy should produce exactly five top candidates when the qualified live universe is available. It should not invent candidates if the universe is empty.

Recommended deterministic selection tiers:

1. Tier 1: initial SC 13D filings from the last 5 trading days.
2. Tier 2: substantive SC 13D/A filings from the last 10 trading days where stake increased, Item 4 changed, or campaign pressure escalated.
3. Tier 3: still-active SC 13D events from the last 20 trading days where price has not exhausted the move and option liquidity remains acceptable.

Filters:

- Exclude pure passive 13G-style ownership.
- Exclude filings with no active intent language.
- Exclude issuers with unusable options.
- Exclude stocks with bid/ask spreads above the system's option-liquidity tolerance.
- Penalize earnings inside the next 5 trading days unless the system intentionally combines events.
- Penalize one-day gaps that already exceed a configurable exhaustion threshold.
- Penalize technology sector candidates to preserve non-tech focus.

Suggested ranking formula:

```text
event_score =
  stake_size_score
  + active_intent_score
  + filer_quality_score
  + recency_score
  + relative_volume_score
  + price_confirmation_score
  + option_liquidity_score
  - gap_exhaustion_penalty
  - earnings_collision_penalty
  - tech_concentration_penalty
```

The top five by `event_score` become the strategy's candidates.

### How it produces 5 candidates

The service should scan deterministic tiers in order until it has at least five qualifying candidates. It should return the top five after ranking and dedupe within the strategy by ticker.

If live conditions produce fewer than five valid candidates, the strategy should return the valid subset and attach a strategy warning rather than backfilling with fabricated or low-quality symbols. Tests with frozen fixtures should enforce the normal five-candidate behavior.

### Option contract selection logic

Research agents generally preferred bull call spreads for defined risk. Current code does not appear to support multi-leg spreads. Therefore:

Recommended v1 with current system:

- Direction: bullish.
- Preferred strategy type: `long_call`.
- Expiration: 14-28 DTE.
- Delta target: approximately 0.35-0.55 when greeks are available.
- Minimum open interest and volume thresholds should match or extend existing contract scoring.
- Reject wide bid/ask spreads.
- Prefer expirations after the expected 5-15 trading-day follow-through window but not so far out that premium sensitivity is diluted.

Future improvement:

- Add multi-leg support for bull call spreads and then use a defined-risk debit spread as the preferred contract structure.

### Entry logic

Enter only after the filing is public and the stock confirms:

- Filing published through SEC.
- Stock holds above filing-day low or breaks above filing-day high.
- Relative volume is above normal.
- Broad market and sector context are not severely adverse.
- No imminent earnings collision unless explicitly allowed.

Preferred entry window:

- Next regular session after the filing.
- Or after day-1 consolidation if the first move is too extended.

### Exit logic

Exit triggers:

- Option reaches 50-70% gain.
- Stock closes below filing-day low or below a configured confirmation level.
- Relative volume collapses and price fails to follow through.
- Earnings or another binary event enters the immediate window.
- Maximum holding period is reached.

### Risk management

- Default to long-premium defined-risk exposure in v1.
- Limit position size because filings can be crowded and gaps can reverse.
- Reject illiquid options.
- Reject stale events.
- Reject or penalize extreme first-day gaps.
- Track campaign/event URL for audit.

### Maximum holding period

Maximum recommended holding period: 20 calendar days or 15 trading days, whichever comes first. Contracts should normally have 14-28 DTE at entry and should not be held close to expiration unless explicitly scored as acceptable.

### Scoring considerations

The existing scoring system should add an event-signal component for this strategy. Generic trend and volume scoring alone will understate the reason the candidate exists.

Suggested additions:

- `event_recency_score`
- `stake_percent_score`
- `activist_intent_score`
- `price_confirmation_score`
- `filing_quality_score`
- `option_liquidity_score`
- `earnings_collision_penalty`

The strategy should be exempt from missing-earnings vetoes because it is not an earnings strategy.

### Failure modes

- Filing is active but the market has already priced it.
- Item 4 parsing misclassifies passive language as activist.
- Filer reputation is unknown or low quality.
- Options are too illiquid.
- Earnings, financing, or macro events dominate the activist signal.
- Tech candidates creep into the strategy and create sector concentration.
- SEC rate limits or filing fetch failures reduce the candidate count.

### Implementation notes

Likely new modules:

- `app/services/activist_13d_service.py`
- `app/services/sec/filings_client.py`
- `app/services/sec/activist_13d_parser.py`

Potential reused modules:

- `app/services/news/sources.py` for SEC access patterns.
- `app/services/market_data/service.py` for price/volume confirmation.
- `app/services/options/service.py` for contract viability.
- `app/services/strategy_catalog.py` for strategy metadata.

Persisting event metadata may require schema changes if the implementation wants audit-grade fields beyond `validation_notes`.

## 7. New Strategy 4

### Strategy name

`form4_cluster_buy`

### Core thesis

Open-market insider purchases can be informative, but the useful automated signal is not any single insider filing. The higher-quality signal is a recent cluster of real open-market purchases by multiple insiders, especially senior officers or directors, where purchase size is meaningful and price action confirms a recovery or accumulation pattern.

### Stock universe

US-listed common stocks with listed options and SEC Form 4 coverage.

Recommended v1 filters:

- Optionable stock.
- Stock price above approximately $10-$15.
- Average daily volume above approximately 500k-1M shares.
- Market cap above approximately $300M-$500M.
- Avoid penny stocks, shells, and issuers with unusable options.

### Sector focus

Non-technology by design. Preferred sectors:

- Regional banks and financials
- Insurers
- Energy
- Industrials
- Consumer
- Materials
- Healthcare services and equipment

Technology should be allowed only when the cluster score is exceptional and sector concentration limits are still respected.

### Why it fits short-term options

Form 4 filings must be reported quickly, and clusters can create a short-term sentiment and information signal. The trade thesis is a 5-15 trading-day rebound or continuation after the cluster becomes public, making 14-35 DTE bullish options appropriate.

### Data requirements

- Form 4 filings.
- Transaction code.
- Insider role.
- Transaction date.
- Filing date.
- Shares purchased.
- Transaction price.
- Total dollar value.
- Number of unique insiders.
- Cluster window.
- Stock drawdown/recovery context.
- Option chain liquidity.

### Data sources

Primary sources:

- SEC ownership XML.
- SEC insider transaction data sets.
- EDGAR company submissions.

Supporting sources:

- yfinance for price history.
- Alpaca/yfinance for option chains.
- Finviz for sector, price, and liquidity screens.
- Finnhub/SEC news for excluding conflicting events.

No new paid or login-gated source is required.

### Candidate selection rules

The strategy should rank recent open-market purchase clusters. It should ignore grants, exercises, tax withholding, derivative conversions, sales, and non-purchase transaction codes.

Recommended cluster criteria:

- At least two open-market purchases in the last 10 trading days.
- Prefer at least two unique insiders.
- Transaction code must be `P`.
- Aggregate purchase value above a configurable threshold.
- Senior officer/director purchases receive extra weight.
- Price should show stabilization, reversal, or constructive accumulation after a drawdown.
- Options must be liquid enough for the current scoring engine.

Suggested ranking formula:

```text
cluster_score =
  unique_insider_count_score
  + seniority_score
  + aggregate_dollar_score
  + purchase_size_vs_market_cap_score
  + recency_score
  + drawdown_recovery_score
  + relative_volume_score
  + option_liquidity_score
  - symbolic_purchase_penalty
  - financing_overhang_penalty
  - earnings_collision_penalty
  - tech_concentration_penalty
```

### How it produces 5 candidates

The service should scan deterministic windows:

1. Tier 1: clusters from the last 5 trading days.
2. Tier 2: clusters from the last 10 trading days.
3. Tier 3: clusters from the last 20 trading days where price confirmation remains valid.

Return the top five ranked tickers. If fewer than five valid clusters exist, return the valid subset with a warning rather than fabricating candidates.

### Option contract selection logic

Recommended v1 with current system:

- Direction: bullish.
- Preferred strategy type: `long_call`.
- Expiration: 14-35 DTE.
- Delta target: approximately 0.35-0.55 where greeks are available.
- Reject wide bid/ask spreads.
- Require minimum open interest or volume.
- Prefer contracts with enough time for a 5-15 trading-day move but not excessive time premium.

Future improvement:

- Add bull call spread support and prefer defined-risk debit spreads for lower premium outlay.

### Entry logic

Enter after public Form 4 confirmation and price validation:

- Cluster is confirmed from SEC data.
- Purchases are real open-market buys.
- Stock closes above a short-term confirmation level, such as prior close, 5-day VWAP, or 20-day moving average.
- No immediate negative 8-K, financing, or earnings collision.
- Options meet liquidity requirements.

### Exit logic

Exit triggers:

- Option reaches 40-60% gain.
- Stock closes below cluster low or confirmation level.
- New negative filing/news invalidates the thesis.
- Candidate fails to follow through within 5 trading days.
- Maximum holding period is reached.

### Risk management

- Reject tiny symbolic purchases.
- Require cluster behavior rather than one small buy.
- Avoid illiquid options.
- Avoid names with likely financing overhang or distressed balance sheets when detectable.
- Penalize near-term earnings unless explicitly combined with another strategy.
- Keep position sizing conservative because insider-buy signals can be slow.

### Maximum holding period

Maximum recommended holding period: 28 calendar days or 15 trading days, whichever comes first.

### Scoring considerations

The existing scoring engine should incorporate a strategy-specific cluster signal. Generic technical scoring may miss the event quality.

Suggested additions:

- `cluster_count_score`
- `seniority_score`
- `purchase_value_score`
- `recency_score`
- `drawdown_recovery_score`
- `filing_quality_score`
- `option_liquidity_score`

The strategy should be exempt from missing-earnings vetoes because an earnings date is not required.

### Failure modes

- Transaction parser includes non-buy transactions by mistake.
- Insider purchase is symbolic.
- Cluster reflects morale support rather than information.
- Filing delay makes entry stale.
- Small-cap options are too wide.
- Negative financing, litigation, or macro news overrides the signal.
- Sector stress dominates individual insider-buy signal.

### Implementation notes

Likely new modules:

- `app/services/form4_cluster_service.py`
- `app/services/sec/form4_parser.py`
- `app/services/sec/insider_cluster.py`

Potential reused modules:

- Existing SEC access patterns in `app/services/news/sources.py`.
- Existing market-data and options services.
- Existing scoring and veto modules after strategy-source expansion.

The parser should store enough audit data to prove that each candidate came from real open-market purchase transactions.

## 8. New Strategy 5

### Strategy name

`post_earnings_drift`

### Core thesis

Earnings information is not always fully incorporated immediately. Strong positive or negative earnings reactions can drift for several sessions, especially when the market sees a surprise, guidance change, high relative volume, and continued price confirmation. This strategy trades after earnings, so it does not duplicate the existing pre-earnings `catalyst_confluence` strategy.

### Stock universe

US-listed optionable stocks that reported earnings in the last one to three regular sessions.

Recommended v1 filters:

- Confirmed recent earnings event.
- Optionable.
- Stock price above approximately $15-$20.
- Adequate stock volume.
- Adequate option open interest/volume and acceptable spread.
- Avoid events older than three sessions unless explicit follow-through remains strong.

### Sector focus

Broad-market. This strategy may include technology, but the overall three-strategy set remains non-tech balanced because Strategy 3 and Strategy 4 are non-tech focused.

To avoid concentration, the ranker should include sector caps or penalties if technology already dominates the 25-candidate pool.

### Why it fits short-term options

The expected drift window is short: usually 3-10 trading days after the report. Options with 7-28 DTE can express the direction while limiting holding period to less than four weeks.

### Data requirements

- Recent earnings date and timing.
- Gap direction and size.
- Earnings-day and day-after close location.
- Relative volume.
- Surprise proxy if available.
- Guidance or 8-K confirmation when available.
- Option chain liquidity.
- Market and sector context.

### Data sources

Primary sources:

- Existing Finnhub earnings data where configured.
- Existing yfinance earnings and price data.
- Existing Alpha Vantage market data where available.
- SEC 8-K Item 2.02 filings for earnings releases.
- Existing Alpaca/yfinance options paths.

Supporting sources:

- Finviz public pages for liquidity and optionability confirmation.
- Finnhub news for qualitative context, not as a replacement for deterministic scoring.

No new paid or login-gated source is required.

### Candidate selection rules

The strategy should evaluate stocks with earnings in the last one to three sessions.

Bullish candidate requirements:

- Positive gap or strong intraday reversal after earnings.
- Close in upper portion of earnings-day range.
- Relative volume materially above average.
- Day-1 or day-2 continuation, or at minimum no gap failure.
- Viable call option contracts.

Bearish candidate requirements:

- Negative gap or strong post-earnings rejection.
- Close in lower portion of earnings-day range.
- Relative volume materially above average.
- Day-1 or day-2 continuation lower, or no recovery above earnings-day midpoint.
- Viable put option contracts.

Suggested ranking formula:

```text
drift_score =
  earnings_recency_score
  + absolute_gap_score
  + close_location_score
  + relative_volume_score
  + followthrough_score
  + surprise_or_guidance_score
  + option_liquidity_score
  + market_sector_alignment_score
  - stale_event_penalty
  - gap_exhaustion_penalty
  - wide_spread_penalty
```

The strategy should rank bullish and bearish setups together by absolute opportunity score while preserving direction for contract selection.

### How it produces 5 candidates

The service should scan deterministic windows:

1. Tier 1: earnings from the previous regular session.
2. Tier 2: earnings from the last two regular sessions.
3. Tier 3: earnings from the last three regular sessions with strong follow-through.

Return the top five ranked candidates. If fewer than five valid events exist, return a valid subset with a warning.

### Option contract selection logic

Recommended v1 with current system:

- Bullish drift: `long_call`.
- Bearish drift: `long_put`.
- Expiration: 7-28 DTE, with preference for 14-21 DTE when liquidity is sufficient.
- Delta target: approximately 0.35-0.55 when greeks are available.
- Reject wide spreads and thin open interest.
- Avoid contracts where IV crush has left pricing stale or spreads unreliable.

Future improvement:

- Add vertical spread support and use call debit spreads or put debit spreads to reduce post-earnings premium cost.

### Entry logic

Enter after earnings reaction is observable:

- Do not enter before the earnings event.
- Enter day 0 after the market has had time to establish direction, or day 1/day 2 if continuation is confirmed.
- Require price to hold the earnings-direction level, such as gap midpoint, earnings-day VWAP, or earnings-day high/low.
- Require options to pass liquidity filters.

### Exit logic

Exit triggers:

- Option reaches 50-70% gain.
- Stock reverses through earnings-day midpoint.
- Stock loses the confirmation level.
- Relative volume normalizes and price stalls.
- 3-10 trading days have elapsed without continuation.
- Maximum holding period is reached.

### Risk management

- Avoid chasing extreme one-day gaps without consolidation.
- Avoid wide post-earnings option spreads.
- Avoid stale earnings older than three sessions.
- Apply sector concentration limits.
- Penalize poor broad-market or sector alignment.
- Keep maximum hold short because drift edge decays.

### Maximum holding period

Maximum recommended holding period: 21 calendar days or 10 trading days, whichever comes first.

### Scoring considerations

This strategy can reuse more of the existing direction scorer than the SEC strategies because post-earnings drift is visible in price, volume, trend, and relative strength. It still needs event-specific scoring fields:

- `earnings_recency_score`
- `gap_score`
- `close_location_score`
- `followthrough_score`
- `surprise_score` when available
- `guidance_or_8k_score` when available

Unlike 13D and Form 4, this strategy should have an earnings date. Missing earnings data should reduce confidence or veto the candidate unless a reliable SEC 8-K earnings release confirms the event.

### Failure modes

- Gap exhausts before entry.
- Earnings surprise data is missing or inaccurate.
- IV crush and spread behavior make options unattractive.
- Broad market reversal overwhelms the signal.
- Strategy enters stale events.
- LLM overexplains a deterministic drift setup unless constrained to finalists only.

### Implementation notes

Likely new module:

- `app/services/post_earnings_drift_service.py`

Potential reused modules:

- `app/services/candidate_service.py` earnings-source patterns.
- `app/services/market_data/service.py` for price and volume features.
- `app/services/options/service.py` for chain viability.
- `app/services/news/sources.py` for SEC 8-K context.

This is the easiest selected strategy to integrate first because it requires less new source infrastructure than the two SEC event strategies.

## 9. Updated 5-Strategy Pipeline

The final pipeline should be:

1. Strategy 1 `catalyst_confluence` produces top 5 candidates.
2. Strategy 2 `coiled_setup` produces top 5 candidates.
3. Strategy 3 `activist_13d_followthrough` produces top 5 candidates.
4. Strategy 4 `form4_cluster_buy` produces top 5 candidates.
5. Strategy 5 `post_earnings_drift` produces top 5 candidates.

Target candidate pool:

```text
5 strategies x 5 candidates = 25 candidates
```

All 25 candidates should pass through the existing deterministic analysis flow:

1. Market-data fetch.
2. News/context fetch according to existing finalist refresh behavior.
3. Options-chain fetch.
4. Expected-move and liquidity evaluation.
5. Deterministic direction and contract scoring.
6. Vetoes and confidence scoring.
7. Sizing.
8. Ranking.

Then:

```text
Top 4 deterministic finalists -> LLM decision step
```

The LLM should only see the top four finalists selected by deterministic scoring. It should not analyze all 25 and should not override deterministic ranking without explicit, validated reasoning. The current orchestrator already defines `DECISION_FINALIST_LIMIT = 4`; the implementation should preserve and test that behavior with a 25-candidate fixture.

### Merge and dedupe priority

The current system preserves `catalyst_confluence` before `coiled_setup`. That behavior should remain.

Recommended priority order:

1. `catalyst_confluence`
2. `coiled_setup`
3. `activist_13d_followthrough`
4. `form4_cluster_buy`
5. `post_earnings_drift`

If a ticker appears in multiple strategies, v1 should preserve the first candidate by priority and attach secondary-source notes if the schema supports it. If the schema is later expanded, store `primary_strategy_source` plus `supporting_strategy_sources` so a duplicate signal can improve confidence rather than disappear.

### Live candidate-count reality

The target system should normally produce 25 candidates. However, live public data can produce fewer than five valid candidates for an event strategy on quiet days. The system should never fabricate symbols to reach 25. It should:

- deterministically widen lookback tiers within strategy rules;
- return the top five if enough valid candidates exist;
- return a partial set with a warning if fewer exist;
- preserve audit logs explaining candidate count.

Frozen-data tests should enforce the 25-candidate happy path.

## 10. Scoring System Integration

### Can the existing scoring system support the new strategies?

Partially. The current deterministic scoring flow, options-chain evaluation, veto logic, and top-four LLM gate are good foundations. The architecture can support new strategies if the strategy-source model, strategy catalog, missing-earnings rules, event metadata, and strategy-specific scoring are extended.

### Required shared scoring changes

1. Widen `StrategySource` in `app/services/candidate_models.py`.
2. Extend `app/services/strategy_catalog.py` with the three new strategy definitions.
3. Replace hard-coded `strategy_source == "coiled_setup"` missing-earnings exemptions with a set such as:

```python
NO_EARNINGS_REQUIRED_STRATEGIES = {
    "coiled_setup",
    "activist_13d_followthrough",
    "form4_cluster_buy",
}
```

4. Keep `post_earnings_drift` earnings-required.
5. Add event metadata to `CandidateRecord`, `CandidateContext`, or a related candidate-event model.
6. Add deterministic strategy-signal scoring before LLM review.
7. Add sector concentration penalties or caps so the expanded pool does not become tech-heavy.

### Strategy-specific scoring needed

For `activist_13d_followthrough`:

- filing recency
- stake size
- active Item 4 intent
- filer quality
- price/volume confirmation
- option liquidity
- gap exhaustion penalty
- earnings collision penalty

For `form4_cluster_buy`:

- unique insider count
- insider seniority
- aggregate purchase value
- purchase size relative to market cap
- cluster recency
- drawdown/recovery confirmation
- symbolic-purchase penalty
- financing overhang penalty

For `post_earnings_drift`:

- earnings recency
- gap size and direction
- close location
- relative volume
- day-1/day-2 follow-through
- surprise/guidance proxy
- stale event penalty
- gap exhaustion penalty

### Shared scoring to reuse

Existing reusable scoring elements:

- trend and relative strength
- volume confirmation
- market and sector environment
- option bid/ask spread
- open interest and volume
- expiration validity
- contract viability
- confidence bands
- vetoes
- final deterministic score combination

### Penalties and filters

Apply these across new strategies:

- wide option spread penalty
- low open interest penalty
- low stock volume penalty
- stale event penalty
- sector concentration penalty
- technology concentration penalty for the new strategy set
- upcoming earnings collision penalty for non-earnings strategies
- missing source confidence penalty
- yfinance fallback confidence penalty where greeks are unavailable
- extreme one-day move/gap exhaustion penalty

### Keeping scoring deterministic

All ranking and candidate selection should use deterministic formulas and frozen inputs. The LLM should not create, reorder, or rescue candidates outside the top four.

Recommended rule:

- Deterministic score decides the top four.
- LLM can choose among the top four only.
- LLM must reference deterministic scores and visible risks.
- `validate_llm_decision()` must continue to reject tickers and contracts outside the finalist payload.
- If the LLM disagrees with the top-ranked deterministic candidate, it must provide a risk-based reason that passes validation.

## 11. Data Source Plan

### `activist_13d_followthrough`

Required data:

- SC 13D and 13D/A filings.
- Issuer ticker/CIK mapping.
- Stake percent.
- Filer identity.
- Item 4 active-intent language.
- Price/volume confirmation.
- Option chain liquidity.

Existing source that can provide it:

- SEC EDGAR APIs for filings and CIK mapping.
- yfinance and Alpha Vantage for price/volume context.
- Alpaca/yfinance options for chains.
- Finviz public screener pages for liquidity and optionability checks.

Backup source:

- Finnhub company news can confirm public activist headlines, but should not replace SEC as primary source.

New source recommended:

- No mandatory new source. Implement a structured SEC filing client/parser using SEC's public APIs.

Access method:

- API-based SEC JSON endpoints and public filing documents.
- Existing market/options adapters.
- Finviz only through public screener pages if used.

Rate-limit concerns:

- SEC requires a responsible user agent and fair-access behavior.
- Add caching and throttling.

Reliability concerns:

- Filing text formats vary.
- Item 4 parsing can be imperfect.
- Ticker mapping must handle issuer changes.

Missing data behavior:

- If SEC filing data is unavailable, return no candidates for the strategy and emit a warning.
- If option data is missing, candidate can be filtered out or allowed into scoring with a likely contract veto.

### `form4_cluster_buy`

Required data:

- Form 4 filings.
- Ownership XML transaction details.
- Transaction code `P`.
- Insider role.
- Shares, price, and dollar amount.
- Cluster window and unique insider count.
- Stock/option liquidity.

Existing source that can provide it:

- SEC ownership XML and insider transaction data sets.
- yfinance/Alpha Vantage for price history.
- Alpaca/yfinance for options.
- Finviz public screens for liquidity and sector.

Backup source:

- No reliable substitute for SEC transaction data should be used as primary. yfinance insider pages may be useful for manual context but should not be a primary automated source.

New source recommended:

- No mandatory new source. Add a structured SEC ownership parser.

Access method:

- SEC public filing XML and data sets.
- Existing market/options adapters.

Rate-limit concerns:

- Same SEC fair-access constraints as the 13D strategy.
- Cache parsed Form 4 filings by accession number.

Reliability concerns:

- Transaction codes must be parsed correctly.
- Amendments and derivative transactions can be misleading.
- Some issuers have thin options.

Missing data behavior:

- If Form 4 XML cannot be parsed, exclude the filing.
- If fewer than five clusters exist, return a partial set with warning.

### `post_earnings_drift`

Required data:

- Recent earnings events.
- Price gap and close location.
- Relative volume.
- Surprise or guidance proxy where available.
- Option liquidity.

Existing source that can provide it:

- Finnhub earnings calendar and news.
- yfinance price and earnings data.
- SEC 8-K Item 2.02 filings through EDGAR.
- Alpha Vantage market data.
- Alpaca/yfinance options.
- Finviz for visible liquidity and optionability confirmation.

Backup source:

- yfinance can back up Finnhub earnings data.
- SEC 8-K can confirm event timing and release context.

New source recommended:

- None required.

Access method:

- API/library-based existing adapters.
- SEC public API for 8-K confirmation if needed.
- Public Finviz pages only for visible liquidity screens.

Rate-limit concerns:

- Finnhub free tier can be rate-limited.
- Alpha Vantage free tier is rate-limited.
- yfinance is unofficial and can be unreliable.

Reliability concerns:

- Earnings timing can be ambiguous.
- Surprise data may be missing.
- Option spreads can widen after earnings.

Missing data behavior:

- If earnings date is unconfirmed, exclude or severely penalize.
- If surprise is missing but price/volume reaction is clear, allow the candidate with lower confidence.
- If options are missing, scoring should veto the trade.

## 12. Implementation Plan

### Phase 1: Inspect and prepare data/schema/config

Files to inspect or modify:

- `app/services/candidate_models.py`
- `app/services/strategy_catalog.py`
- `app/services/multi_strategy_service.py`
- `app/core/config.py`
- `app/db/models/candidate.py`
- `app/db/models/recommendation.py`
- `app/scoring/confidence.py`
- `app/scoring/vetoes.py`
- `app/scoring/types.py`

Tasks:

- Widen `StrategySource` to include the three new slugs.
- Confirm slug lengths fit existing `String(32)` database fields.
- Add catalog entries for new strategies.
- Add strategy config for lookbacks, sector focus, candidate limit, and enabled/disabled flags if desired.
- Decide whether to add candidate event metadata fields or a related event table.
- Add missing-earnings exemption set for non-earnings strategies.
- Decide whether v1 remains single-leg only or begins multi-leg schema work.

### Phase 2: Add candidate generation for Strategy 3

New service:

- `app/services/activist_13d_service.py`

Likely supporting modules:

- `app/services/sec/filings_client.py`
- `app/services/sec/activist_13d_parser.py`

Tasks:

- Fetch recent SC 13D and SC 13D/A filings.
- Parse issuer, filer, stake, accession, filing date, and active-intent fields.
- Enrich with market and optionability filters.
- Rank by deterministic `event_score`.
- Return top five `CandidateRecord` objects with `strategy_source="activist_13d_followthrough"`.

### Phase 3: Add candidate generation for Strategy 4

New service:

- `app/services/form4_cluster_service.py`

Likely supporting modules:

- `app/services/sec/form4_parser.py`
- `app/services/sec/insider_cluster.py`

Tasks:

- Fetch and parse Form 4 ownership XML.
- Keep only transaction code `P`.
- Build clusters by ticker and date window.
- Enrich with price recovery, sector, liquidity, and options availability.
- Rank by deterministic `cluster_score`.
- Return top five `CandidateRecord` objects with `strategy_source="form4_cluster_buy"`.

### Phase 4: Add candidate generation for Strategy 5

New service:

- `app/services/post_earnings_drift_service.py`

Tasks:

- Build recent earnings universe from Finnhub/yfinance/SEC as available.
- Compute gap, close location, relative volume, and follow-through.
- Determine bullish or bearish bias.
- Enrich with options liquidity.
- Rank by deterministic `drift_score`.
- Return top five `CandidateRecord` objects with `strategy_source="post_earnings_drift"`.

### Phase 5: Integrate all candidates into the scoring pipeline

Files to modify:

- `app/services/multi_strategy_service.py`
- `app/pipeline/steps/candidates.py` if the return shape changes
- `app/services/candidate_models.py`
- `app/services/strategy_catalog.py`

Tasks:

- Refactor `MultiStrategyCandidateService` from two hard-coded strategy calls to a deterministic strategy-runner list.
- Preserve existing Strategy 1 fallback warning exactly.
- Preserve Strategy 2 behavior where Finviz errors degrade to empty results unless intentionally changed with tests.
- Add per-strategy warnings and `StrategyRunReport` entries.
- Merge and dedupe in deterministic priority order.
- Preserve current catalyst priority on duplicates.
- Ensure normal happy path produces 25 candidates.

### Phase 6: Send only top 4 candidates to LLM

Files to verify or modify:

- `app/pipeline/orchestrator.py`
- `app/pipeline/steps/decide.py`
- `app/llm/schemas.py`

Tasks:

- Preserve `DECISION_FINALIST_LIMIT = 4`.
- Add a test using 25 preliminary candidates that confirms only four are refreshed with live news and passed to the decision step.
- Ensure LLM payload excludes non-finalist candidates.
- Ensure LLM validation continues to reject tickers/contracts outside the deterministic finalist payload.

### Phase 7: Add logging and auditability

Files/modules to inspect:

- `app/services/logging_service.py` if used by pipeline logging
- `app/db/models/candidate.py`
- `app/db/models/recommendation.py`
- candidate event metadata storage if added

Tasks:

- Log strategy source, candidate rank, score components, source URLs, and warnings.
- Store SEC accession numbers for 13D/Form 4 events.
- Store event dates and reason codes.
- Store whether a candidate was deduped or preserved as primary.
- Store finalist selection reason and deterministic rank.

### Phase 8: Add tests and backtesting

Test files to extend or add:

- `tests/test_multi_strategy_service.py`
- `tests/test_recommendation_pipeline.py`
- `tests/test_scoring_engine.py`
- `tests/test_pipeline_determinism.py`
- `tests/test_finviz_runner.py`
- new tests for SEC parsers and new services

Tasks:

- Add frozen SEC filing fixtures.
- Add frozen earnings drift fixtures.
- Add deterministic ranking tests.
- Add missing-data tests.
- Add 25-candidate and top-four finalist tests.
- Add backtesting harnesses before paper/live use.

## 13. Required Tests

Unit tests for each new candidate generator:

- `activist_13d_followthrough` returns top five from frozen 13D fixtures.
- `form4_cluster_buy` returns top five from frozen Form 4 fixtures.
- `post_earnings_drift` returns top five from frozen earnings fixtures.

Unit tests for strategy-specific scoring:

- 13D event score ranks fresh active filings above stale/passive filings.
- Form 4 cluster score ranks multi-insider open-market buys above symbolic single buys.
- Post-earnings drift score ranks confirmed follow-through above gap failures.

Data-source tests:

- SEC CIK/ticker mapping.
- SEC 13D parser.
- SEC Form 4 XML parser.
- Finnhub/yfinance earnings fallback.
- Option-chain fallback from Alpaca to yfinance.

Missing-data tests:

- SEC unavailable.
- malformed filing.
- missing earnings surprise.
- missing option greeks.
- empty option chain.
- Finviz load failure behavior unchanged for existing strategies.

Candidate-count tests:

- each strategy returns five candidates on frozen happy path.
- five strategies produce 25 candidates on frozen happy path.
- duplicate tickers are deduped in priority order.
- partial candidate sets produce warnings and do not fabricate symbols.

Top-four selection tests:

- 25 preliminary candidates produce exactly four decision finalists.
- only four finalists receive live-news refresh when live-news gating applies.
- only four finalists are passed to `LLMDecisionStep`.

LLM payload validation tests:

- LLM cannot select a ticker outside the finalist set.
- LLM cannot select a contract outside viable finalist contracts.
- LLM cannot inflate confidence beyond validated deterministic bounds.
- LLM disagreement with top deterministic rank must include a validated reason.

Determinism tests:

- frozen inputs produce identical candidate order.
- strategy merge order is stable.
- scoring order is stable.
- dedupe order is stable.

Regression tests with frozen data:

- existing `catalyst_confluence` fallback warning remains exact.
- existing `coiled_setup` empty-on-Finviz-error behavior remains unless intentionally changed.
- current top-four LLM finalist limit remains intact.

Backtesting tests:

- 13D strategy event-window returns with liquidity filters.
- Form 4 cluster event-window returns with transaction-code validation.
- Post-earnings drift returns across bullish and bearish branches.
- option spread/slippage assumptions stress test.
- sector concentration stress test.

Failure-mode tests:

- SEC rate-limit or network failure.
- Finviz browser failure.
- yfinance empty data.
- Alpaca unavailable.
- options too illiquid.
- earnings collision.
- sector concentration.
- stale event.

## 14. Risk Analysis

### Weak or delayed data

Public data can be delayed, incomplete, or unavailable. SEC filings are official but require careful throttling and parsing. yfinance is unofficial and can fail. Finnhub and Alpha Vantage free tiers can be rate-limited.

Mitigation:

- Cache source responses.
- Preserve source URLs and timestamps.
- Use deterministic fallback order.
- Return warnings instead of silently degrading quality.

### Poor option liquidity

Many SEC-event names have listed options but poor spreads or weak open interest.

Mitigation:

- Apply hard option liquidity filters before recommendation.
- Penalize wide spreads in scoring.
- Prefer more liquid expirations.
- Allow candidate generation but veto contract selection when chains are unusable.

### Wide bid/ask spreads

Short-term options around events can have wide spreads, especially after earnings or activist gaps.

Mitigation:

- Reject contracts beyond spread thresholds.
- Penalize stale quotes.
- Prefer contracts with real volume and open interest.

### Low open interest

Low open interest makes fills and exits harder.

Mitigation:

- Require minimum OI/volume or score penalties.
- Avoid small issuers even when event signal is strong.

### Overfitting

Event strategies can be overfit to recent examples or hand-picked thresholds.

Mitigation:

- Use broad historical fixtures and walk-forward testing.
- Keep formulas simple.
- Test by sector and market regime.
- Avoid optimizing thresholds to a small sample.

### Sector concentration

The existing and new strategies could cluster in technology, mega-cap earnings, or a single macro-sensitive sector.

Mitigation:

- Explicitly non-tech focus for 13D and Form 4 strategies.
- Add sector concentration penalties.
- Track strategy and sector allocation in logs.

### Catalyst failure

Activist filings, insider buys, and earnings drift can fail quickly.

Mitigation:

- Use confirmation rules.
- Exit on invalidation levels.
- Keep maximum holding periods short.
- Do not average down.

### Free API limitations

Free data sources can have rate limits, incomplete fields, or inconsistent schemas.

Mitigation:

- Prefer official SEC data for filing events.
- Use Alpaca options when configured and yfinance as fallback.
- Cache expensive source calls.
- Add missing-data warnings.

### Fragile web scraping

Finviz is visible-page scraping and can break if the page changes.

Mitigation:

- Keep Finviz usage on public screener pages only.
- Preserve the existing retry ladder.
- Avoid adding login, cookies, private APIs, or hidden endpoints.
- Use SEC/yfinance/Finnhub for new event logic where possible.

### LLM hallucination

The LLM may invent reasons or overstate confidence.

Mitigation:

- Send only top four deterministic finalists.
- Include source-backed facts and score components.
- Keep validation constraints in `LLMDecisionStep`.
- Reject unsupported ticker/contract selections.

### LLM nondeterminism

LLM output can vary run to run.

Mitigation:

- Deterministic scoring controls finalist set.
- LLM only provides qualitative review after scoring.
- Store LLM rationale and validated deterministic score.

### Short-option assignment risk

Some rejected strategies require short options, credit spreads, or iron condors. Current system supports `short_put` and `short_call` at the type level, but short-option assignment and margin risk need stronger controls.

Mitigation:

- Use long calls/puts for v1 new strategies.
- Do not recommend multi-leg or short-premium strategies until schema, margin, and assignment controls are implemented.

### Macro events affecting all strategies

Rate decisions, CPI, geopolitical shocks, and broad volatility spikes can overwhelm individual signals.

Mitigation:

- Use market and sector environment scoring.
- Add macro blackout or risk-reduction rules if needed.
- Keep holding periods short.

## 15. Final Recommendation

Add these three strategies:

1. `activist_13d_followthrough`
2. `form4_cluster_buy`
3. `post_earnings_drift`

These were selected because they have the best combination of research support, short-term options fit, public-data availability, non-tech diversification, and compatibility with the existing Earning-Edge pipeline.

Rejected strategies were weaker for practical reasons:

- Buyback drift is plausible but requires harder text classification.
- Generic 8-K follow-through is too broad for v1.
- Financing-shock puts are fragile and often illiquid.
- Defensive premium fade needs multi-leg and short-option controls.
- Healthcare regulatory skew is sparse and binary.
- Earnings calendars and IV term-structure trades need multi-leg support.
- Pure option-flow strategies require better signed flow than free sources provide.
- 0DTE, max-pain, pinning, rumor, and paid-flow strategies do not fit the constraints.

Recommended implementation order:

1. `post_earnings_drift`, because it reuses the most existing infrastructure and can validate the 25-candidate/top-four LLM flow quickly.
2. `activist_13d_followthrough`, because it is the strongest new non-tech event strategy.
3. `form4_cluster_buy`, because it builds on the same SEC parser foundation but needs transaction-level clustering.

Before paper or live use, the system must test:

- SEC parser correctness.
- 25-candidate happy path.
- top-four LLM finalist limit.
- option-liquidity filters.
- missing-data degradation.
- deterministic rankings.
- sector concentration controls.
- frozen-data backtests.
- existing Strategy 1 fallback warning and Strategy 2 failure behavior.

Unresolved implementation decisions:

- Whether to add structured event metadata to the database in v1 or store event details in validation notes first.
- Whether to add multi-leg spreads before live trading or keep v1 to single-leg long calls/puts.
- Whether live operation must hard-require 25 candidates or allow partial strategy output with warnings on quiet event days.
- Exact score thresholds for liquidity, event recency, and gap exhaustion, which should be tuned with frozen fixtures and backtests.

## References

- SEC EDGAR APIs: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC Schedule 13D/13G guide: https://www.sec.gov/submit-filings/filer-support-resources/how-do-i-guides/file-schedule-13d-schedule-13-g-corresponding-amendments
- SEC beneficial ownership modernization: https://www.sec.gov/rules-regulations/2023/10/33-11180
- SEC press release on beneficial ownership rules: https://www.sec.gov/newsroom/press-releases/2023-219
- SEC Forms 3/4/5 investor bulletin: https://www.sec.gov/forms/forms-3-4-5.pdf
- SEC insider transactions data sets: https://www.sec.gov/data-research/sec-markets-data/insider-transactions-data-sets
- SEC ownership XML technical specification: https://www.sec.gov/info/edgar/ownershipxmltechspec-v2.htm
- SEC Form 8-K instructions: https://www.sec.gov/divisions/corpfin/forms/8-k.htm
- Alpaca option chain docs: https://docs.alpaca.markets/us/reference/optionchain
- Alpaca option snapshots docs: https://docs.alpaca.markets/us/reference/optionsnapshots
- Alpaca historical options data: https://docs.alpaca.markets/us/docs/historical-option-data
- yfinance documentation: https://ranaroussi.github.io/yfinance/index.html
- Finnhub API documentation: https://finnhub.io/docs/api
- Alpha Vantage documentation: https://www.alphavantage.co/documentation/
- Cboe weekly options directory: https://www.cboe.com/markets/us/options/symbol-directory/weeklys-options
- Brav et al., Hedge Fund Activism: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=948907
- Polk et al., 13D timing study: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4596959
- Shareholder activism study, Journal of Financial Economics: https://www.sciencedirect.com/science/article/pii/S0304405X21003950
- Collin-Dufresne, Fos, Muravyev, activist trading and options price discovery: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2675866
- Jeon and Sulaeman, insider trading and options: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4864272
- Alldredge and Blank, insider clusters: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2781761
- Jeng, Metrick, Zeckhauser, insider trading: https://www.nber.org/papers/w6913
- Cohen, Malloy, Pomorski, insider trading: https://www.nber.org/papers/w16454
- Akbas et al., Post-Earnings Announcement Drift over the past century: https://ssrn.com/abstract=4373735
- Double Machine Learning and PEAD, JFQA: https://doi.org/10.1017/S0022109023000133
- Chan and Marsh, Overnight PEAD and SEC Form 8-K: https://ssrn.com/abstract=4765828
- Govindaraj, Liu, Livnat, PEAD: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2146181
- Lipkin, Tatevossian, K M, earnings moves and pre-earnings implied volatility: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4701633
- Honarvar and Howard, options-implied signals: https://ssrn.com/abstract=4766424
- Pan and Poteshman, option volume and stock prices: https://www.nber.org/papers/w10925
- Michael, Cucuringu, Howison, option volume imbalance: https://ssrn.com/abstract=4019647
- Bohmann and Patel, options before FDA announcements: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3223184
- 0DTE risk paper: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4692190
- FDA advisory committee calendar: https://www.fda.gov/advisory-committees/advisory-committee-calendar
- ClinicalTrials.gov API: https://clinicaltrials.gov/data-about-studies/learn-about-api
