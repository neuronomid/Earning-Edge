"use client";

import { useCallback, useEffect, useState } from "react";
import { type OptionContract, type OptionQuote } from "@/types/option";

export function useOptionQuotes(contracts: OptionContract[], intervalMs = 5000) {
  const [quotes, setQuotes] = useState<Record<string, OptionQuote>>({});
  const [isLoading, setIsLoading] = useState(false);

  const refresh = useCallback(async () => {
    if (contracts.length === 0) return;
    setIsLoading(true);
    try {
      const response = await fetch("/api/simulation/prices", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ contracts }),
        cache: "no-store",
      });
      if (response.ok) {
        setQuotes((await response.json()) as Record<string, OptionQuote>);
      }
    } finally {
      setIsLoading(false);
    }
  }, [contracts]);

  useEffect(() => {
    void refresh();
    const intervalId = window.setInterval(() => void refresh(), intervalMs);
    return () => window.clearInterval(intervalId);
  }, [intervalMs, refresh]);

  return { quotes, isLoading, refresh };
}
