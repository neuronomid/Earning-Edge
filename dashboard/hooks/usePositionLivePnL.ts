"use client";

import { useMemo, useRef } from "react";
import { useLiveStockPrice } from "@/hooks/useLiveStockPrice";
import type { SimulationPosition } from "@/types/simulation";

export type OptionPriceSource = "LIVE_OPTION_QUOTE" | "ESTIMATED_FROM_STOCK" | "MOCK" | "STALE";

export interface LivePositionView extends SimulationPosition {
  liveUnderlyingPrice: number | null;
  underlyingChange: number | null;
  underlyingChangePercent: number | null;
  estimatedOptionPrice: number | null;
  optionPriceSource: OptionPriceSource;
  liveUnrealizedPnl: number | null;
  liveUnrealizedPnlPercent: number | null;
  liveMarketValue: number | null;
  stopLossTriggered: boolean;
  takeProfitTriggered: boolean;
}

function defaultDelta(optionType: "CALL" | "PUT"): number {
  return optionType === "CALL" ? 0.5 : -0.5;
}

/**
 * Enriches a single position with live underlying price data and estimated option P&L.
 * Exported as a named hook so the OpenPositionsTable can call it per-row.
 */
export function useSinglePositionLivePnL(
  position: SimulationPosition,
  intervalMs = 5000,
): LivePositionView {
  const entryUnderlyingRef = useRef(position.entryUnderlyingPrice);

  const live = useLiveStockPrice({
    symbol: position.symbol,
    userId: position.accountId,
    intervalMs,
    enabled: position.status === "OPEN",
  });

  return useMemo((): LivePositionView => {
    const entryUnderlying = entryUnderlyingRef.current;
    const liveUnderlying = live.currentPrice;

    // Underlying move
    const underlyingChange =
      liveUnderlying !== null && entryUnderlying !== null
        ? liveUnderlying - entryUnderlying
        : null;
    const underlyingChangePercent =
      underlyingChange !== null && entryUnderlying !== null && entryUnderlying !== 0
        ? (underlyingChange / entryUnderlying) * 100
        : null;

    // Option price source: prefer current server-side quote, fall back to estimation
    const serverOptionPrice =
      position.currentMid !== null && position.currentMid > 0
        ? position.currentMid
        : position.currentBid !== null &&
          position.currentAsk !== null &&
          position.currentBid > 0 &&
          position.currentAsk > 0
          ? (position.currentBid + position.currentAsk) / 2
          : position.currentMarkPrice > 0
            ? position.currentMarkPrice
            : null;

    let estimatedOptionPrice: number | null = null;
    let optionPriceSource: OptionPriceSource = "STALE";

    if (serverOptionPrice !== null && live.dataMode !== "MOCK") {
      // Server has a real quote — use it as-is
      estimatedOptionPrice = serverOptionPrice;
      optionPriceSource = live.dataMode === "REAL_TIME" ? "LIVE_OPTION_QUOTE" : "LIVE_OPTION_QUOTE";
    } else if (liveUnderlying !== null && entryUnderlying !== null && underlyingChange !== null) {
      // No live option quote → estimate via delta
      const delta = defaultDelta(position.optionType);
      const raw = position.averageEntryPrice + underlyingChange * delta;
      estimatedOptionPrice = Math.max(0.01, parseFloat(raw.toFixed(4)));
      optionPriceSource = live.dataMode === "MOCK" ? "MOCK" : "ESTIMATED_FROM_STOCK";
    } else if (serverOptionPrice !== null) {
      estimatedOptionPrice = serverOptionPrice;
      optionPriceSource = "STALE";
    }

    // Live P&L
    let liveUnrealizedPnl: number | null = null;
    let liveUnrealizedPnlPercent: number | null = null;
    let liveMarketValue: number | null = null;

    if (estimatedOptionPrice !== null) {
      const qty = position.quantity;
      const multiplier = 100;
      const value = estimatedOptionPrice * qty * multiplier;
      const basis = position.averageEntryPrice * qty * multiplier;
      liveMarketValue = parseFloat(value.toFixed(2));
      const pnl = position.positionSide === "LONG" ? value - basis : basis - value;
      liveUnrealizedPnl = parseFloat(pnl.toFixed(2));
      liveUnrealizedPnlPercent = basis !== 0 ? parseFloat(((pnl / basis) * 100).toFixed(2)) : 0;
    }

    // Stop / take-profit detection
    const markForCheck = estimatedOptionPrice ?? position.currentMarkPrice;
    const isLong = position.positionSide === "LONG";
    const stopLossTriggered =
      position.stopLoss !== null &&
      (isLong ? markForCheck <= position.stopLoss : markForCheck >= position.stopLoss);
    const takeProfitTriggered =
      position.takeProfit !== null &&
      (isLong ? markForCheck >= position.takeProfit : markForCheck <= position.takeProfit);

    return {
      ...position,
      liveUnderlyingPrice: liveUnderlying,
      underlyingChange,
      underlyingChangePercent,
      estimatedOptionPrice,
      optionPriceSource,
      liveUnrealizedPnl,
      liveUnrealizedPnlPercent,
      liveMarketValue,
      stopLossTriggered,
      takeProfitTriggered,
    };
  }, [position, live]);
}
