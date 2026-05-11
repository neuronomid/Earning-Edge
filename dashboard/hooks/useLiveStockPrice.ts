"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { DataMode } from "@/lib/marketData/MarketDataProvider";

export type LivePriceStatus = "CONNECTED" | "POLLING" | "DISCONNECTED" | "ERROR";

export interface LivePriceState {
  symbol: string;
  currentPrice: number | null;
  previousPrice: number | null;
  bid: number | null;
  ask: number | null;
  change: number | null;
  changePercent: number | null;
  lastUpdated: string | null;
  provider: string;
  dataMode: DataMode;
  status: LivePriceStatus;
  error?: string;
}

export interface UseLiveStockPriceOptions {
  symbol: string;
  userId?: string;
  intervalMs?: number;
  enabled?: boolean;
}

export function useLiveStockPrice({
  symbol,
  userId,
  intervalMs = 5000,
  enabled = true,
}: UseLiveStockPriceOptions): LivePriceState & { refreshNow: () => void } {
  const [state, setState] = useState<LivePriceState>({
    symbol,
    currentPrice: null,
    previousPrice: null,
    bid: null,
    ask: null,
    change: null,
    changePercent: null,
    lastUpdated: null,
    provider: "unknown",
    dataMode: "POLLING",
    status: "DISCONNECTED",
  });

  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isFetchingRef = useRef(false);
  // Tracks last confirmed price so we can compute tick-level change
  const lastKnownPriceRef = useRef<number | null>(null);

  const fetchPrice = useCallback(async () => {
    if (!enabled || !symbol || isFetchingRef.current) return;
    isFetchingRef.current = true;

    setState((s) => ({ ...s, status: "POLLING" }));

    try {
      const params = new URLSearchParams({ symbol });
      if (userId) params.set("userId", userId);
      const response = await fetch(`/api/market-data/stock-quote?${params.toString()}`, {
        cache: "no-store",
      });

      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { error?: string };
        setState((s) => ({
          ...s,
          status: "ERROR",
          dataMode: "ERROR" as DataMode,
          error: body.error ?? `HTTP ${response.status}`,
        }));
        return;
      }

      const data = (await response.json()) as {
        symbol?: string;
        price?: number;
        bid?: number | null;
        ask?: number | null;
        previousClose?: number | null;
        change?: number | null;
        changePercent?: number | null;
        timestamp?: string;
        provider?: string;
        dataMode?: DataMode;
        _fallbackReason?: string;
      };

      const newPrice = data.price ?? null;
      if (newPrice === null) {
        setState((s) => ({ ...s, status: "ERROR", error: "No price in response." }));
        return;
      }

      const prevKnown = lastKnownPriceRef.current;
      // Use tick-level delta when we have a previous known price, otherwise fall back to
      // daily change from the quote (change vs. previousClose).
      const tickChange =
        prevKnown !== null
          ? parseFloat((newPrice - prevKnown).toFixed(4))
          : (data.change ?? null);
      const tickChangePercent =
        prevKnown !== null && prevKnown !== 0
          ? parseFloat((((newPrice - prevKnown) / prevKnown) * 100).toFixed(4))
          : (data.changePercent ?? null);

      if (process.env.NODE_ENV === "development") {
        console.log(
          `[useLiveStockPrice] ${symbol} → $${newPrice.toFixed(2)}`,
          `Δ${tickChange !== null ? tickChange.toFixed(4) : "n/a"}`,
          `mode=${data.dataMode ?? "?"}`,
          `src=${data.provider ?? "?"}`,
          new Date().toLocaleTimeString(),
        );
      }

      setState({
        symbol: (data.symbol ?? symbol).toUpperCase(),
        currentPrice: newPrice,
        previousPrice: prevKnown,
        bid: data.bid ?? null,
        ask: data.ask ?? null,
        change: tickChange,
        changePercent: tickChangePercent,
        lastUpdated: new Date().toLocaleTimeString(),
        provider: data.provider ?? "unknown",
        dataMode: data.dataMode ?? "POLLING",
        status: "CONNECTED",
        error: undefined,
      });

      lastKnownPriceRef.current = newPrice;
    } catch (err) {
      setState((s) => ({
        ...s,
        status: "ERROR",
        dataMode: "ERROR" as DataMode,
        error: err instanceof Error ? err.message : "Fetch failed.",
      }));
    } finally {
      isFetchingRef.current = false;
    }
  }, [symbol, userId, enabled]);

  useEffect(() => {
    if (!enabled) {
      if (intervalRef.current) clearInterval(intervalRef.current);
      setState((s) => ({ ...s, status: "DISCONNECTED" }));
      return;
    }

    // Fetch immediately, then on each interval
    void fetchPrice();
    intervalRef.current = setInterval(() => void fetchPrice(), intervalMs);

    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [fetchPrice, intervalMs, enabled]);

  return { ...state, refreshNow: fetchPrice };
}
