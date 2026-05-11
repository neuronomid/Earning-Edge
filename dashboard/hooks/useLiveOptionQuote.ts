"use client";

import { useCallback, useEffect, useRef } from "react";
import { useMarketDataStore } from "@/stores/useMarketDataStore";
import type { OptionQuoteRequest } from "@/lib/marketData/MarketDataProvider";

export function useLiveOptionQuote(
  request: OptionQuoteRequest | null,
  intervalMs = 5000,
) {
  const key = request
    ? `${request.ticker}:${request.expiry}:${request.optionType}:${request.strike}`
    : null;

  const { quotes, errors, isPolling, lastUpdated, setQuote, setError, setPolling, setLastUpdated } =
    useMarketDataStore();

  const quote = key ? (quotes[key] ?? null) : null;
  const error = key ? (errors[key] ?? null) : null;

  const fetchQuote = useCallback(async () => {
    if (!request || !key) return;
    setPolling(true);
    try {
      const response = await fetch("/api/market-data/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
        cache: "no-store",
      });
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        setError(key, body.error ?? `HTTP ${response.status}`);
        return;
      }
      const data = await response.json();
      setQuote(key, data);
      setLastUpdated(new Date().toLocaleTimeString());
    } catch (err) {
      setError(key, err instanceof Error ? err.message : "Fetch failed.");
    } finally {
      setPolling(false);
    }
  }, [key, request, setError, setPolling, setQuote, setLastUpdated]);

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    if (!request) return;
    void fetchQuote();
    intervalRef.current = setInterval(() => void fetchQuote(), intervalMs);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchQuote, intervalMs, request]);

  return { quote, error, isPolling, lastUpdated, refresh: fetchQuote };
}
