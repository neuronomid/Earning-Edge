# Proposed News Solution for Earning-Edge

## 1. Problem

The current news flow is unstable because it depends on open-web search and article scraping. That creates variance from:

- open-web search result changes
- random article download failures
- dynamic article page content
- async article ordering
- nonzero LLM temperature

The goal is to make back-to-back runs materially more deterministic without relying on TTL caching as the main fix.

## 2. Proposed Source Stack

Use this source stack:

- `Finnhub` for recent structured stock news
- `SEC EDGAR` for official filings and current-year reports
- open-web search and scraping only as an optional fallback when fixed sources are sparse

`Alpha Vantage` is intentionally excluded from the news architecture because of request limits.

## 3. Finnhub Policy

Fetch up to the last `120 days` of company news for each ticker.

Rank the results with strong recency bias:

- highest weight: last `7 days`
- normal current-news window: last `30 days`
- older `31-120 day` items only if they are thesis-changing

Treat these as thesis-changing examples:

- earnings-related coverage
- guidance changes
- acquisitions
- lawsuits or investigations
- major analyst actions
- product launches
- restructuring
- large contracts or customer wins

Apply relevance filtering before any LLM step:

- prefer items that mention the ticker or company name in the headline or summary
- down-rank broad market articles where the company is only a side mention
- deduplicate by URL, title, and timestamp
- sort deterministically by relevance, freshness, source quality, then URL or title

Do not pass the full raw Finnhub feed to the LLM. Send only the top `5-10` cleaned items.

## 4. SEC EDGAR Policy

Fetch SEC filings for the current calendar year from `January 1` through the run date.

Include these forms:

- `8-K`
- `10-Q`
- `10-K`
- `10-Q/A` when present
- `10-K/A` when present

Treat `Form 4` as a separate insider-activity signal, not equal to core filings.

SEC EDGAR is official catalyst evidence, not a full substitute for market news. All SEC requests must use a proper `User-Agent`.

## 5. LLM and Scoring Use

The LLM should receive only the cleaned, ranked Finnhub plus SEC packet.

The summarizer temperature should be set to `0`.

The LLM must use source-backed evidence only and should summarize:

- bullish evidence
- bearish evidence
- neutral context
- key uncertainty

Stale or weakly relevant items should not drive the direction score.

## 6. Why This Is Better

This approach:

- removes unstable article scraping from the primary path
- improves repeatability between runs
- lowers noise
- keeps an auditable evidence trail
- uses structured JSON feeds instead of brittle HTML extraction

## 7. CSCO Validation Note

Live smoke testing for `CSCO` showed that the proposed stack is viable.

- SEC EDGAR successfully returned recent `8-K` and `Form 4` filings for Cisco in the current year.
- Finnhub successfully returned recent company-news items for `CSCO`.
- The Finnhub feed was usable but noisy, which confirms the need for relevance filtering and ranking before sending items to the LLM.

The main takeaway from the CSCO test is that SEC is reliable for official filings, while Finnhub is reliable for structured recent news as long as the raw feed is filtered before scoring and summarization.
