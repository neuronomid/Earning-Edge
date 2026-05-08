# Debug Guide: "No additional qualified alternatives" Message

## What I Found

I've analyzed the code and added comprehensive logging to help debug when you see the message "No additional qualified alternatives are available for this run."

## The Logic Flow

When you click the Alternative button, here's what happens:

1. **Load all recommendations already shown in this run** - these are the "shown" tickers
2. **Get top 4 candidates by score** - sorted by:
   - Final opportunity score (highest first)
   - Data confidence score
   - Direction score
3. **For each top 4 candidate:**
   - Skip if already shown
   - Load related option contracts
   - Find a viable contract
   - If no viable contract → skip this candidate
   - If viable → run the decision AI model
   - If decision says "recommend" or "watchlist" → show it
   - If decision says "no_trade" → skip this candidate
4. **If all 4 candidates are exhausted** → show "No additional qualified alternatives"

## Why the Message Appears

The message is NOT necessarily a bug. It appears when ONE of these is true:

1. ✅ **All top 4 candidates have been shown already** (legitimate - you've seen them all)
2. ✅ **A candidate has no viable option contracts** (legitimate - filters rejected them)
3. ✅ **Decision AI rejected the candidate** (legitimate - AI deemed it unsuitable)
4. ❌ **Bug scenario**: Only one candidate exists but you get the message on first Alternative click

## How to Check the Logs

After you click Alternative and see the message, check the logs:

```bash
tail -200 /Users/omid/Documents/Projects/Earning-Edge/var/log/telegram-bot.log | grep -A 50 "alternative_"
```

## What the Logs Will Tell You

Look for these patterns:

### Pattern 1: All Already Shown
```
alternative_ranked_candidates: ranked_count=4, ranked_tickers=[AAPL(score=80), MSFT(score=75), ...]
alternative_candidate_already_shown: candidate_ticker=AAPL
alternative_candidate_already_shown: candidate_ticker=MSFT
...
alternative_no_qualified_found: total_processed=4, shown_tickers=['AAPL', 'MSFT', ...]
```
→ This is **NOT a bug** - you've seen all top 4 candidates

### Pattern 2: Candidates Have No Viable Contracts
```
alternative_ranked_candidates: ranked_count=4, ranked_tickers=[AAPL(score=80), ...]
alternative_processing_candidate: candidate_ticker=AAPL, already_shown=False
alternative_pipeline_contracts_loaded: contract_count=5
alternative_pipeline_no_viable_contract: scored_count=5
...
```
→ This is **NOT a bug** - filters rejected the contracts

### Pattern 3: Decision AI Rejected Candidates
```
alternative_processing_candidate: candidate_ticker=AAPL, already_shown=False
alternative_decision_result: decision_action=no_trade
alternative_decision_no_trade: candidate_ticker=AAPL
...
```
→ This is **NOT a bug** - AI judged them unsuitable

### Pattern 4: Likely Bug
```
alternative_ranked_candidates: ranked_count=1, ranked_tickers=[AAPL(score=80)]
alternative_processing_candidate: candidate_ticker=AAPL, already_shown=False
alternative_pipeline_contracts_loaded: contract_count=3
alternative_decision_result: decision_action=recommend
alternative_recommendation_created: candidate_ticker=AAPL
```
Then when you click Alternative AGAIN immediately:
```
alternative_ranked_candidates: ranked_count=1, ranked_tickers=[AAPL(score=80)]
alternative_candidate_already_shown: candidate_ticker=AAPL
alternative_no_qualified_found: total_processed=1
```
→ Only 1 candidate, but you got "no alternatives" on first click - investigate

## Next Step

Please share the log output from:
```bash
tail -500 /Users/omid/Documents/Projects/Earning-Edge/var/log/telegram-bot.log | grep "alternative_"
```

This will help confirm whether it's:
- Working as designed (all candidates exhausted)
- A genuine bug (candidates missing/filters too strict)
