"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { type PaperPosition, type PaperState } from "@/lib/dashboard-data";
import { fetchMultiplePrices, type LiveOptionPrice } from "@/lib/price-service";
import { checkStopLossTakeProfit, savePaperState } from "@/lib/paper-store";

export type SimulationAlert = {
  id: string;
  type: "stop_loss" | "take_profit";
  ticker: string;
  message: string;
};

export function useSimulation(
  paperState: PaperState,
  setPaperState: React.Dispatch<React.SetStateAction<PaperState>>,
) {
  const [livePrices, setLivePrices] = useState<Record<string, LiveOptionPrice>>({});
  const [alerts, setAlerts] = useState<SimulationAlert[]>([]);
  const [isSimulating, setIsSimulating] = useState(false);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const openPositions = paperState.positions.filter((p) => p.status === "open");

  const fetchPrices = useCallback(async () => {
    if (openPositions.length === 0) return;
    setIsSimulating(true);
    try {
      const prices = await fetchMultiplePrices(openPositions);
      setLivePrices(prices);
      setLastUpdate(new Date().toLocaleTimeString());

      // Check SL/TP
      const { state: newState, alerts: sltpAlerts } = checkStopLossTakeProfit(
        paperState,
        prices,
      );

      if (sltpAlerts.length > 0) {
        setPaperState(newState);
        savePaperState(newState);
        const newAlertItems: SimulationAlert[] = sltpAlerts.map((a) => ({
          id: `${a.positionId}-${a.type}-${Date.now()}`,
          type: a.type,
          ticker: a.ticker,
          message: `${a.ticker} ${a.type === "stop_loss" ? "stop loss" : "take profit"} triggered!`,
        }));
        setAlerts((prev) => [...newAlertItems, ...prev].slice(0, 10));
      } else {
        // Just update current premiums
        setPaperState((prev) => {
          const updated = {
            ...prev,
            positions: prev.positions.map((pos) => {
              if (pos.status !== "open") return pos;
              const price = prices[pos.id];
              if (price?.mid) {
                return { ...pos, currentPremium: price.mid };
              }
              return pos;
            }),
          };
          savePaperState(updated);
          return updated;
        });
      }
    } catch {
      // Silently fail - prices will retry next poll
    } finally {
      setIsSimulating(false);
    }
  }, [openPositions, paperState, setPaperState]);

  // Auto-poll every 30 seconds
  useEffect(() => {
    if (openPositions.length === 0) {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
      return;
    }

    // Initial fetch
    void fetchPrices();

    intervalRef.current = setInterval(() => {
      void fetchPrices();
    }, 30000);

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    };
  }, [fetchPrices, openPositions.length]);

  const dismissAlert = useCallback((id: string) => {
    setAlerts((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const clearAllAlerts = useCallback(() => {
    setAlerts([]);
  }, []);

  return { livePrices, alerts, isSimulating, lastUpdate, fetchPrices, dismissAlert, clearAllAlerts };
}
