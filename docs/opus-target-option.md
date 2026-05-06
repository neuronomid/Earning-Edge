# Option Target Definition — Simple Version

**Purpose:** Define a clear exit plan for every recommended option contract, so the user knows when to sell before expiry instead of just guessing.

---

## The 3 Questions

### 1. Where do you think the stock will go?

Use the **expected move** — how much the market thinks the stock will swing after earnings.

```text
expected_move_$ = current_price × IV × √(days_to_expiry / 365)
```

Pick a target based on conviction:

| Conviction | Stock Target |
|---|---|
| High (direction score ≥ 75) | 100% of expected move |
| Medium | 60–70% of expected move |
| Low | 40% of expected move (take quick profits) |

Also check the next **resistance level** (for calls) or **support level** (for puts) on the chart. Use whichever target is **closer** — that's the realistic exit price.

---

### 2. What will the option be worth when the stock hits that target?

Use **delta** as a shortcut:

> If delta is 0.50, every $1 the stock moves up = the call gains roughly $0.50.

```text
target_option_price ≈ entry_option_price + delta × (target_stock − entry_stock) × IV_crush_factor
```

**The IV crush catch (post-earnings):** option prices drop because volatility collapses after the earnings announcement. Shave **20–35%** off the estimate to stay realistic:

| Hold Period | IV Crush Factor |
|---|---|
| Pre-earnings (rare) | 1.00 |
| Post-earnings | 0.65 – 0.80 |

---

### 3. When should you actually sell?

Don't wait for just one trigger. Use **multiple exit rules**:

| Rule | What it Means |
|---|---|
| **Take profit** | Sell when option reaches the target price you calculated (or +100%, whichever comes first) |
| **Quick profit** | Sell half at +50% to lock in gains |
| **Stop loss** | If option drops 50% below entry, cut the loss |
| **Time exit** | Always sell at least 5 days before expiry (theta decay accelerates near expiry) |
| **Thesis break** | If the reason you bought is gone (bad news, guidance cut, etc.), exit immediately |

---

## What the Bot Should Tell the User

Every recommendation must include:

- **Sell at:** $X.XX *(option price target)*
- **Stock target:** $YYY.YY
- **Stop loss:** $X.XX
- **Exit by:** [date]

---

## Concrete Example

**Setup:**
- Stock: ABC at $100
- Expected move (post-earnings): $8
- Buy: Call option at $2.00, delta 0.50, expires in 14 days
- Conviction: High

**Step 1 — Stock Target:**
- Expected move = $8 → high conviction → target full move
- **Target stock price = $108**

**Step 2 — Option Target:**
- Stock move = $108 − $100 = $8
- Raw option gain = 0.50 × $8 = $4.00
- Estimated option price = $2.00 + $4.00 = $6.00
- Apply IV crush factor (0.70): $6.00 × 0.70 = **$4.20**
- Round to a realistic exit: **$4.00**

**Step 3 — Exit Rules:**
- Take profit: **Sell at $4.00** (option price)
- Quick profit: Sell half at $3.00 (+50%)
- Stop loss: **Cut at $1.00** (−50%)
- Time exit: **Exit by [expiry minus 5 days]**

---

## The Bottom Line

> "Buy this call for **$2.00**.
> Sell it when the stock hits **$108** OR the option reaches **$4.00**, whichever comes first.
> Cut losses at **$1.00**.
> Get out by **Friday** no matter what."

That's the entire plan — a clear price to sell at AND a date to exit by, not just an entry.

---

## Suggested New Output Fields

Add to `recommendations` and `option_contracts` tables:

```text
entry_option_price          # what user pays
target_stock_price          # what stock needs to do
target_option_price         # primary sell trigger
target_gain_percent         # e.g. +85%
stop_loss_option_price      # cut at -50%
exit_by_date                # theta cliff date
expected_holding_days       # 3-10 typical post-earnings
```

---

## Main Tradeoff

**Delta-based estimate (recommended):**
- Fast, deterministic, ~10–15% error vs. real option price
- Good enough for guidance (we're not executing trades)

**Full Black-Scholes recompute:**
- More accurate but needs reliable IV term-structure data
- Alpaca/yfinance IV is sometimes flaky
- Extra precision rarely changes the user's exit decision

For Earning-Edge: stick with the delta-based approach. Build it as a new **`ExitTargetService`** that runs after contract selection and writes target fields into `option_contracts` and `recommendations` tables.
