import { calculateOptionPnL } from "../utils/options/calculateOptionPnL";
import { calculateBreakeven } from "../utils/options/calculateBreakeven";
import { calculateMaxLoss } from "../utils/options/calculateMaxLoss";
import { calculateMaxProfit } from "../utils/options/calculateMaxProfit";
import { checkStopLossTakeProfit } from "../utils/options/checkStopLossTakeProfit";
import { calculateAccountSummary } from "../utils/options/calculateAccountSummary";

// ── Helpers ─────────────────────────────────────────────────────────────────
function r2(n: number) {
  return Math.round(n * 100) / 100;
}

// ── Buy Call P&L ─────────────────────────────────────────────────────────────
describe("Buy Call P&L", () => {
  test("profit: option price rises from 0.03 to 0.08", () => {
    const result = calculateOptionPnL({
      side: "LONG",
      entryOptionPrice: 0.03,
      currentOptionPrice: 0.08,
      quantity: 1,
    });
    expect(result.unrealizedPnL).toBe(5); // (0.08-0.03)*1*100
    expect(result.entryValue).toBe(3);
    expect(result.currentValue).toBe(8);
  });

  test("loss: option price falls from 0.10 to 0.05", () => {
    const result = calculateOptionPnL({
      side: "LONG",
      entryOptionPrice: 0.1,
      currentOptionPrice: 0.05,
      quantity: 2,
    });
    expect(result.unrealizedPnL).toBe(-10); // (0.05-0.10)*2*100
  });

  test("breakeven = strike + premium", () => {
    expect(calculateBreakeven("CALL", "LONG", 100, 3)).toBe(103);
  });

  test("max loss = premium * quantity * 100", () => {
    const ml = calculateMaxLoss("CALL", "LONG", 100, 3, 2);
    expect(ml.isUnlimited).toBe(false);
    if (!ml.isUnlimited) expect(ml.value).toBe(600);
  });

  test("max profit = unlimited", () => {
    const mp = calculateMaxProfit("CALL", "LONG", 100, 3, 1);
    expect(mp.isUnlimited).toBe(true);
  });
});

// ── Buy Put P&L ──────────────────────────────────────────────────────────────
describe("Buy Put P&L", () => {
  test("profit: option price rises from 0.50 to 1.20", () => {
    const result = calculateOptionPnL({
      side: "LONG",
      entryOptionPrice: 0.5,
      currentOptionPrice: 1.2,
      quantity: 1,
    });
    expect(result.unrealizedPnL).toBe(70);
  });

  test("loss: option price falls from 0.50 to 0.20", () => {
    const result = calculateOptionPnL({
      side: "LONG",
      entryOptionPrice: 0.5,
      currentOptionPrice: 0.2,
      quantity: 1,
    });
    expect(result.unrealizedPnL).toBe(-30);
  });

  test("breakeven = strike - premium", () => {
    expect(calculateBreakeven("PUT", "LONG", 100, 5)).toBe(95);
  });

  test("max loss = premium paid", () => {
    const ml = calculateMaxLoss("PUT", "LONG", 100, 5, 1);
    expect(ml.isUnlimited).toBe(false);
    if (!ml.isUnlimited) expect(ml.value).toBe(500);
  });

  test("max profit finite (strike - premium)", () => {
    const mp = calculateMaxProfit("PUT", "LONG", 100, 5, 1);
    expect(mp.isUnlimited).toBe(false);
    if (!mp.isUnlimited) expect(mp.value).toBe(9500); // (100-5)*1*100
  });
});

// ── Short Call P&L ────────────────────────────────────────────────────────────
describe("Short Call P&L", () => {
  test("profit: option price falls from 0.50 to 0.20 (short gains)", () => {
    const result = calculateOptionPnL({
      side: "SHORT",
      entryOptionPrice: 0.5,
      currentOptionPrice: 0.2,
      quantity: 1,
    });
    expect(result.unrealizedPnL).toBe(30);
  });

  test("loss: option price rises from 0.50 to 1.00 (short loses)", () => {
    const result = calculateOptionPnL({
      side: "SHORT",
      entryOptionPrice: 0.5,
      currentOptionPrice: 1.0,
      quantity: 1,
    });
    expect(result.unrealizedPnL).toBe(-50);
  });

  test("max profit = premium received", () => {
    const mp = calculateMaxProfit("CALL", "SHORT", 100, 5, 1);
    expect(mp.isUnlimited).toBe(false);
    if (!mp.isUnlimited) expect(mp.value).toBe(500);
  });

  test("max loss = unlimited", () => {
    const ml = calculateMaxLoss("CALL", "SHORT", 100, 5, 1);
    expect(ml.isUnlimited).toBe(true);
  });
});

// ── Short Put P&L ─────────────────────────────────────────────────────────────
describe("Short Put P&L", () => {
  test("profit: option price falls from 1.00 to 0.50", () => {
    const result = calculateOptionPnL({
      side: "SHORT",
      entryOptionPrice: 1.0,
      currentOptionPrice: 0.5,
      quantity: 2,
    });
    expect(result.unrealizedPnL).toBe(100);
  });

  test("breakeven = strike - premium", () => {
    expect(calculateBreakeven("PUT", "SHORT", 100, 5)).toBe(95);
  });

  test("max profit = premium received", () => {
    const mp = calculateMaxProfit("PUT", "SHORT", 100, 5, 1);
    expect(mp.isUnlimited).toBe(false);
    if (!mp.isUnlimited) expect(mp.value).toBe(500);
  });

  test("max loss = (strike - premium) * qty * 100", () => {
    const ml = calculateMaxLoss("PUT", "SHORT", 100, 5, 1);
    expect(ml.isUnlimited).toBe(false);
    if (!ml.isUnlimited) expect(ml.value).toBe(9500);
  });
});

// ── Stop Loss / Take Profit — Long ────────────────────────────────────────────
describe("Stop loss and take profit — long option", () => {
  test("stop loss triggers when price falls to stopLossPrice", () => {
    const result = checkStopLossTakeProfit({
      side: "LONG",
      currentOptionPrice: 0.03,
      entryOptionPrice: 0.10,
      stopLossPrice: 0.05,
    });
    expect(result).toBe("STOP_LOSS");
  });

  test("take profit triggers when price rises to takeProfitPrice", () => {
    const result = checkStopLossTakeProfit({
      side: "LONG",
      currentOptionPrice: 0.20,
      entryOptionPrice: 0.10,
      takeProfitPrice: 0.15,
    });
    expect(result).toBe("TAKE_PROFIT");
  });

  test("stop loss triggers on percent loss", () => {
    const result = checkStopLossTakeProfit({
      side: "LONG",
      currentOptionPrice: 0.05,
      entryOptionPrice: 0.10,
      stopLossPercent: 40, // -40% triggers at ≤ -40%
    });
    expect(result).toBe("STOP_LOSS");
  });

  test("no trigger when price is between SL and TP", () => {
    const result = checkStopLossTakeProfit({
      side: "LONG",
      currentOptionPrice: 0.12,
      entryOptionPrice: 0.10,
      stopLossPrice: 0.07,
      takeProfitPrice: 0.20,
    });
    expect(result).toBeNull();
  });
});

// ── Stop Loss / Take Profit — Short ───────────────────────────────────────────
describe("Stop loss and take profit — short option", () => {
  test("stop loss triggers when price rises above stopLossPrice", () => {
    const result = checkStopLossTakeProfit({
      side: "SHORT",
      currentOptionPrice: 1.50,
      entryOptionPrice: 0.50,
      stopLossPrice: 1.00,
    });
    expect(result).toBe("STOP_LOSS");
  });

  test("take profit triggers when price falls below takeProfitPrice", () => {
    const result = checkStopLossTakeProfit({
      side: "SHORT",
      currentOptionPrice: 0.10,
      entryOptionPrice: 0.50,
      takeProfitPrice: 0.25,
    });
    expect(result).toBe("TAKE_PROFIT");
  });
});

// ── Account balance after opening long option ─────────────────────────────────
describe("Account balance", () => {
  test("cash decreases by debit when opening long call", () => {
    const summary = calculateAccountSummary(10000, 0, [
      { side: "LONG", entryOptionPrice: 0.03, currentOptionPrice: 0.03, quantity: 1 },
    ]);
    expect(summary.cashBalance).toBe(r2(10000 - 0.03 * 100));
  });

  test("equity includes current position value for long", () => {
    const summary = calculateAccountSummary(10000, 0, [
      { side: "LONG", entryOptionPrice: 0.03, currentOptionPrice: 0.08, quantity: 1 },
    ]);
    // equity = cashBalance + openPositionsValue
    expect(summary.equity).toBe(r2(summary.cashBalance + summary.openPositionsValue));
    expect(summary.unrealizedPnL).toBe(5);
  });

  test("cash increases by credit when opening short put", () => {
    const summary = calculateAccountSummary(10000, 0, [
      { side: "SHORT", entryOptionPrice: 0.50, currentOptionPrice: 0.50, quantity: 1, strike: 50 },
    ]);
    // Short: credit added to cash, liability tracked
    expect(summary.unrealizedPnL).toBe(0);
  });

  test("realized pnl is applied after close", () => {
    const summary = calculateAccountSummary(10000, 500, []);
    expect(summary.cashBalance).toBe(10500);
    expect(summary.realizedPnL).toBe(500);
  });

  test("closing long option adds cash back", () => {
    // Simulate: open at 0.03, close at 0.08 → realized PnL = +5
    const summary = calculateAccountSummary(10000, 5, []);
    expect(summary.cashBalance).toBe(10005);
  });
});
