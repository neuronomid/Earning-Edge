import type { OptionSide, OptionType } from "./calculateOptionPnL";

export function calculateBreakeven(
  optionType: OptionType,
  side: OptionSide,
  strike: number,
  premium: number,
): number {
  void side;
  if (optionType === "CALL") return round4(strike + premium);
  return round4(strike - premium);
}

function round4(n: number) {
  return Math.round(n * 10000) / 10000;
}
