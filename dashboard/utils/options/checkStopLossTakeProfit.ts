import type { OptionSide } from "./calculateOptionPnL";

export type TriggerResult = "STOP_LOSS" | "TAKE_PROFIT" | null;

export function checkStopLossTakeProfit(params: {
  side: OptionSide;
  currentOptionPrice: number;
  entryOptionPrice: number;
  stopLossPrice?: number | null;
  takeProfitPrice?: number | null;
  stopLossPercent?: number | null;
  takeProfitPercent?: number | null;
}): TriggerResult {
  const pnlPct =
    params.entryOptionPrice > 0
      ? ((params.currentOptionPrice - params.entryOptionPrice) / params.entryOptionPrice) * 100
      : 0;

  const effectivePnlPct = params.side === "LONG" ? pnlPct : -pnlPct;

  if (params.side === "LONG") {
    if (params.stopLossPrice != null && params.currentOptionPrice <= params.stopLossPrice)
      return "STOP_LOSS";
    if (params.stopLossPercent != null && effectivePnlPct <= -Math.abs(params.stopLossPercent))
      return "STOP_LOSS";
    if (params.takeProfitPrice != null && params.currentOptionPrice >= params.takeProfitPrice)
      return "TAKE_PROFIT";
    if (params.takeProfitPercent != null && effectivePnlPct >= Math.abs(params.takeProfitPercent))
      return "TAKE_PROFIT";
  } else {
    if (params.stopLossPrice != null && params.currentOptionPrice >= params.stopLossPrice)
      return "STOP_LOSS";
    if (params.stopLossPercent != null && effectivePnlPct <= -Math.abs(params.stopLossPercent))
      return "STOP_LOSS";
    if (params.takeProfitPrice != null && params.currentOptionPrice <= params.takeProfitPrice)
      return "TAKE_PROFIT";
    if (params.takeProfitPercent != null && effectivePnlPct >= Math.abs(params.takeProfitPercent))
      return "TAKE_PROFIT";
  }

  return null;
}
