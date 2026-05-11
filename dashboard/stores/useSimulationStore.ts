import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { SimulationAccount } from "@/types/simulation";
import type { PnLSnapshot, OptionPriceSnapshot } from "@/components/options/PositionPnLChart";

type SimulationStore = {
  account: SimulationAccount | null;
  equityHistory: PnLSnapshot[];
  optionPriceHistory: Record<string, OptionPriceSnapshot[]>;

  setAccount: (account: SimulationAccount) => void;
  addEquitySnapshot: (snapshot: PnLSnapshot) => void;
  addOptionPriceSnapshot: (positionId: string, snapshot: OptionPriceSnapshot) => void;
  resetHistory: () => void;
};

const MAX_HISTORY = 500;

export const useSimulationStore = create<SimulationStore>()(
  persist(
    (set) => ({
      account: null,
      equityHistory: [],
      optionPriceHistory: {},

      setAccount: (account) =>
        set((state) => {
          const newEquity: PnLSnapshot = {
            timestamp: new Date().toISOString(),
            equity: account.totalPortfolioValue,
            unrealizedPnL: account.unrealizedPnl,
            realizedPnL: account.realizedPnl,
          };
          return {
            account,
            equityHistory: [...state.equityHistory, newEquity].slice(-MAX_HISTORY),
          };
        }),

      addEquitySnapshot: (snapshot) =>
        set((state) => ({
          equityHistory: [...state.equityHistory, snapshot].slice(-MAX_HISTORY),
        })),

      addOptionPriceSnapshot: (positionId, snapshot) =>
        set((state) => ({
          optionPriceHistory: {
            ...state.optionPriceHistory,
            [positionId]: [
              ...(state.optionPriceHistory[positionId] ?? []),
              snapshot,
            ].slice(-MAX_HISTORY),
          },
        })),

      resetHistory: () =>
        set({ equityHistory: [], optionPriceHistory: {} }),
    }),
    {
      name: "earning-edge-simulation-v1",
      partialize: (state) => ({
        equityHistory: state.equityHistory,
        optionPriceHistory: state.optionPriceHistory,
      }),
    },
  ),
);
