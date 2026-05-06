# Final Target Option Definition

This document records the final target-option decision for Earning-Edge V1.

The bot should use the Greek-based target method from `gp-target-option.md` as
the primary method for long calls and long puts. The simpler method from
`opus-target-option.md` should remain as the fallback path when provider data is
incomplete.

## Decision

Use a new `ExitTargetService` after final contract selection.

The service should calculate:

- target stock price
- target option sell price
- target gain percent
- stop-loss option price
- exit-by date
- expected holding days
- target method used

The recommendation should show these values to the user so every option idea has
a defined exit plan, not just an entry.

## Required Inputs

For the primary Greek-based method, the selected option contract should include:

- current option mid price
- current stock price
- target stock price
- strike
- expiry date
- planned holding days
- implied volatility
- expected IV change
- delta
- gamma
- theta
- vega

Alpaca Options Snapshots API is the preferred source for these fields. yfinance
remains the fallback options source. Missing Greeks should reduce confidence and
select a fallback method, not automatically kill the recommendation.

## Stock Target

The stock target should come from the trade thesis, not from a fixed option gain
percentage.

Start with expected move:

```text
expected_move = current_stock_price * implied_volatility * sqrt(days_to_expiry / 365)
```

Scale the move by direction conviction:

| Direction Score | Move Used |
|---|---:|
| 75+ | 100% of expected move |
| 60 to 74 | 60% to 70% of expected move |
| below 60 | 40% of expected move |

For calls, cap the target at the nearest realistic resistance level when it is
closer than the expected-move target. For puts, cap the target at the nearest
realistic support level when it is closer.

## Primary Option Target Formula

Use the Greek-based formula when delta, gamma, theta, vega, IV, and a usable
bid/ask/mid are present.

```text
stock_move = target_stock_price - current_stock_price

target_option_price =
current_mid
+ delta * stock_move
+ 0.5 * gamma * stock_move^2
+ theta * planned_holding_days
+ vega * expected_iv_change
```

Use signed delta. Calls normally have positive delta. Puts normally have
negative delta, so a lower stock target produces a positive target contribution.

Theta should use the same unit convention as the provider. If the provider
returns daily theta, multiply by planned holding days. If the provider returns
annualized theta, normalize it before applying the formula.

## Earnings and IV Crush

If the trade crosses earnings, estimate post-event IV change.

Preferred method:

```text
iv_adjustment = vega * expected_iv_change
```

`expected_iv_change` is usually negative after earnings for long premium. If
vega or a reliable IV-change estimate is unavailable, apply a conservative
haircut to estimated profit or extrinsic value. Do not blindly reduce the whole
option price unless no cleaner decomposition is available.

## Fallback Order

Use this deterministic order:

```text
If delta, gamma, theta, vega, IV, and bid/ask/mid are present:
    use full Greek-based target formula
Else if delta and bid/ask/mid are present:
    use delta-based estimate
Else:
    use intrinsic value at the stock target plus conservative remaining time value
```

Delta fallback:

```text
target_option_price = current_mid + delta * (target_stock_price - current_stock_price)
```

For earnings trades with no vega-based IV adjustment, apply a conservative
post-earnings haircut to estimated profit or extrinsic value.

Intrinsic fallback:

```text
call_intrinsic = max(target_stock_price - strike, 0)
put_intrinsic  = max(strike - target_stock_price, 0)

target_option_price = intrinsic_value + conservative_remaining_time_value
```

## Exit Rules

Every long-option recommendation should include:

1. Profit target: sell when the live option mid reaches `target_option_price`.
2. Stock target: sell or reassess when the underlying reaches `target_stock_price`.
3. Stop loss: cut if the option reaches `stop_loss_option_price`.
4. Time exit: exit by `exit_by_date`.
5. Thesis break: exit if the setup reason is invalidated.

Default stop-loss guidance for long premium:

```text
stop_loss_option_price = entry_option_price * 0.50
```

The system may tighten the stop when the thesis invalidation level is closer or
when data confidence is weak.

Default time exit:

```text
exit_by_date = min(planned_exit_date, expiry_date - 5 calendar days)
```

## Database Fields

Add these fields to `option_contracts` and `recommendations`:

```text
target_stock_price
target_option_price
target_gain_percent
stop_loss_option_price
exit_by_date
expected_holding_days
target_method
```

Allowed `target_method` values:

```text
full_greeks
delta_fallback
intrinsic_fallback
```

Add these fields to `option_contracts` when available from the options source:

```text
gamma
theta
vega
```

## User Output

Every long-option recommendation should tell the user:

- entry option price
- target option sell price
- stock target
- stop-loss option price
- exit-by date
- target method used when useful for logs or detail views

The target is guidance for manual review. The system still does not execute
trades.
