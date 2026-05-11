"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchSimulationAccount } from "@/lib/api";
import { type SimulationAccount } from "@/types/simulation";

export function usePortfolioPolling(accountId: string, startingCash: number, intervalMs = 30000) {
  const [account, setAccount] = useState<SimulationAccount | null>(null);
  const [isPolling, setIsPolling] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdate, setLastUpdate] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setIsPolling(true);
    try {
      const next = await fetchSimulationAccount(accountId, startingCash);
      setAccount(next);
      setLastUpdate(new Date().toLocaleTimeString());
      setError(null);
      return next;
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Portfolio polling failed.";
      setError(message);
      return null;
    } finally {
      setIsPolling(false);
    }
  }, [accountId, startingCash]);

  useEffect(() => {
    void refresh();
    const intervalId = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(intervalId);
  }, [intervalMs, refresh]);

  return { account, setAccount, isPolling, error, lastUpdate, refresh };
}
