export type AccountSummary = {
  startingBalance: number;
  cashBalance: number;
  reservedMargin: number;
  openPositionsValue: number;
  realizedPnL: number;
  unrealizedPnL: number;
  equity: number;
  buyingPower: number;
};

export type PositionForSummary = {
  side: "LONG" | "SHORT";
  entryOptionPrice: number;
  currentOptionPrice: number;
  quantity: number;
  multiplier?: number;
  strike?: number;
};

export function calculateAccountSummary(
  startingBalance: number,
  realizedPnL: number,
  positions: PositionForSummary[],
): AccountSummary {
  const multiplier = 100;
  let openPositionsValue = 0;
  let unrealizedPnL = 0;
  let reservedMargin = 0;
  let cashBalance = startingBalance + realizedPnL;

  for (const pos of positions) {
    const m = pos.multiplier ?? multiplier;
    const entryValue = pos.entryOptionPrice * pos.quantity * m;
    const currentValue = pos.currentOptionPrice * pos.quantity * m;

    if (pos.side === "LONG") {
      openPositionsValue += currentValue;
      unrealizedPnL += currentValue - entryValue;
      cashBalance -= entryValue;
    } else {
      const credit = entryValue;
      const liability = currentValue;
      openPositionsValue += credit;
      unrealizedPnL += credit - liability;
      const margin = pos.strike
        ? Math.max(pos.strike * m * pos.quantity * 0.2, credit * 2)
        : credit * 2;
      reservedMargin += margin;
    }
  }

  const equity = cashBalance + openPositionsValue;
  const buyingPower = Math.max(0, equity - reservedMargin);

  return {
    startingBalance,
    cashBalance: round2(cashBalance),
    reservedMargin: round2(reservedMargin),
    openPositionsValue: round2(openPositionsValue),
    realizedPnL: round2(realizedPnL),
    unrealizedPnL: round2(unrealizedPnL),
    equity: round2(equity),
    buyingPower: round2(buyingPower),
  };
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}
