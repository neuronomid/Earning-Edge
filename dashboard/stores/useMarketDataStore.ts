import { create } from "zustand";
import type { OptionQuoteResult } from "@/lib/marketData/MarketDataProvider";

type MarketDataStore = {
  quotes: Record<string, OptionQuoteResult>;
  isPolling: boolean;
  lastUpdated: string | null;
  errors: Record<string, string>;

  setQuote: (key: string, quote: OptionQuoteResult) => void;
  setError: (key: string, error: string) => void;
  clearError: (key: string) => void;
  setPolling: (polling: boolean) => void;
  setLastUpdated: (ts: string) => void;
};

export const useMarketDataStore = create<MarketDataStore>((set) => ({
  quotes: {},
  isPolling: false,
  lastUpdated: null,
  errors: {},

  setQuote: (key, quote) =>
    set((state) => ({
      quotes: { ...state.quotes, [key]: quote },
      errors: Object.fromEntries(Object.entries(state.errors).filter(([k]) => k !== key)),
    })),

  setError: (key, error) =>
    set((state) => ({ errors: { ...state.errors, [key]: error } })),

  clearError: (key) =>
    set((state) => ({
      errors: Object.fromEntries(Object.entries(state.errors).filter(([k]) => k !== key)),
    })),

  setPolling: (polling) => set({ isPolling: polling }),
  setLastUpdated: (ts) => set({ lastUpdated: ts }),
}));
