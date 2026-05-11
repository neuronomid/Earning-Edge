import type { OptionSide, OptionType } from "./calculateOptionPnL";

export type MaxLoss = { value: number; isUnlimited: false } | { isUnlimited: true };

export function calculateMaxLoss(
  optionType: OptionType,
  side: OptionSide,
  strike: number,
  premium: number,
  quantity: number,
  multiplier = 100,
): MaxLoss {
  if (side === "LONG") {
    return { value: round2(premium * quantity * multiplier), isUnlimited: false };
  }
  if (optionType === "CALL") {
    return { isUnlimited: true };
  }
  return {
    value: round2((strike - premium) * quantity * multiplier),
    isUnlimited: false,
  };
}

export function maxLossText(loss: MaxLoss): string {
  if (loss.isUnlimited) return "Unlimited";
  return formatCurrency(loss.value);
}

function formatCurrency(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function round2(n: number) {
  return Math.round(n * 100) / 100;
}
