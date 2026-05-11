export type OptionSide = "LONG" | "SHORT";
export type OptionType = "CALL" | "PUT";

export type OptionPnLInput = {
  side: OptionSide;
  entryOptionPrice: number;
  currentOptionPrice: number;
  quantity: number;
  multiplier?: number;
};

export type OptionPnLResult = {
  unrealizedPnL: number;
  unrealizedPnLPercent: number;
  entryValue: number;
  currentValue: number;
};

export function calculateOptionPnL(input: OptionPnLInput): OptionPnLResult {
  const multiplier = input.multiplier ?? 100;
  const entryValue = input.entryOptionPrice * input.quantity * multiplier;
  const currentValue = input.currentOptionPrice * input.quantity * multiplier;

  const unrealizedPnL =
    input.side === "LONG" ? currentValue - entryValue : entryValue - currentValue;

  const unrealizedPnLPercent =
    entryValue === 0 ? 0 : (unrealizedPnL / Math.abs(entryValue)) * 100;

  return {
    unrealizedPnL: round2(unrealizedPnL),
    unrealizedPnLPercent: round2(unrealizedPnLPercent),
    entryValue: round2(entryValue),
    currentValue: round2(currentValue),
  };
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}
