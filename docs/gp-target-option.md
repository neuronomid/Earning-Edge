# Option Target Definition

This note defines how to set a target exit price for a purchased option contract.

The target should not be an arbitrary percentage gain on the option itself. It should be derived from the stock thesis, the expected holding period, and the option's pricing inputs.

## Core Idea

For a long call or long put, the system should estimate the option's fair value at the intended exit point and sell when the live option mid-price reaches that target.

The target depends on:

- current underlying price
- target underlying price
- strike
- expiry date
- days remaining
- implied volatility
- delta, gamma, theta, and vega
- bid/ask spread and liquidity

## Target Formula

For a long call:

```text
target_option_price =
current_mid
+ delta * (stock_target - current_stock_price)
+ 0.5 * gamma * (stock_target - current_stock_price)^2
+ theta * days_held
+ vega * expected_iv_change
```

For a long put:

```text
target_option_price =
current_mid
+ abs(delta) * (current_stock_price - stock_target)
+ 0.5 * gamma * (stock_target - current_stock_price)^2
+ theta * days_held
+ vega * expected_iv_change
```

If Greeks are missing, use a simpler fallback:

```text
target_option_price = intrinsic_value_at_stock_target + estimated_remaining_time_value
```

## Intrinsic Value

For a call:

```text
intrinsic = max(stock_target - strike, 0)
```

For a put:

```text
intrinsic = max(strike - stock_target, 0)
```

## Exit Rules

The recommendation should include three exit conditions:

1. Profit target: sell when option mid >= target option price.
2. Time stop: sell if the target is not reached by the planned exit date.
3. Thesis stop: sell if the underlying invalidates the setup or the option loses too much value.

## Earnings Warning

If the trade crosses earnings, the target must account for IV crush. In that case, the system should calculate both:

- pre-earnings target
- post-earnings target

The post-earnings target should usually be lower for long premium because implied volatility often drops after the event.

## Recommended Bot Behavior

The bot should output:

- entry price
- target sell price
- invalidation level
- target date
- reasoning for the target

The default exit target should be based on modeled fair value at the chosen stock target and date, not a fixed percentage gain.
