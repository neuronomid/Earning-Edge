import { type ActivityItem, type PaperPosition, type PaperState } from "@/lib/dashboard-data";
import { type LiveOptionPrice } from "@/lib/price-service";

const STORAGE_KEY = "earning-edge-paper-state-v5";

export function loadPaperState(fallbackBalance: number): PaperState {
  if (typeof window === "undefined") {
    return { startingBalance: fallbackBalance, positions: [], feedback: {}, activity: [] };
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as PaperState;
      if (parsed && Array.isArray(parsed.positions)) {
        return { ...parsed, startingBalance: parsed.startingBalance || fallbackBalance };
      }
    }
  } catch {
    window.localStorage.removeItem(STORAGE_KEY);
  }
  return { startingBalance: fallbackBalance, positions: [], feedback: {}, activity: [] };
}

export function savePaperState(state: PaperState) {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
}

export function createPaperPosition(
  state: PaperState,
  params: {
    recommendationId: string;
    ticker: string;
    companyName: string;
    optionType: "Call" | "Put";
    positionSide: "Long" | "Short";
    strike: number;
    expiry: string;
    quantity: number;
    entryPremium: number;
    currentPremium: number;
    maxLossText: string;
    thesis: string;
    stopLoss?: number | null;
    takeProfit?: number | null;
  },
): PaperState {
  const capitalReserved =
    params.positionSide === "Long"
      ? params.entryPremium * 100 * params.quantity
      : params.strike * 100 * params.quantity * 0.2;

  const position: PaperPosition = {
    id: `pos-${Date.now()}`,
    recommendationId: params.recommendationId,
    ticker: params.ticker,
    companyName: params.companyName,
    optionType: params.optionType,
    positionSide: params.positionSide,
    strike: params.strike,
    expiry: params.expiry,
    quantity: params.quantity,
    entryPremium: params.entryPremium,
    currentPremium: params.currentPremium,
    capitalReserved,
    maxLossText: params.maxLossText,
    thesis: params.thesis,
    openedAt: new Date().toISOString(),
    status: "open",
    stopLoss: params.stopLoss ?? null,
    takeProfit: params.takeProfit ?? null,
    triggeredBy: null,
  };

  const activity: ActivityItem = {
    id: `act-${Date.now()}`,
    title: `${params.ticker} paper position opened`,
    detail: `Simulated ${params.quantity} contract(s) at ${formatCurrency(params.entryPremium * 100)} per contract.`,
    tone: "positive",
    timestamp: new Date().toISOString(),
  };

  return {
    ...state,
    positions: [position, ...state.positions],
    activity: [activity, ...state.activity].slice(0, 50),
  };
}

export function closePaperPosition(
  state: PaperState,
  positionId: string,
  closePremium: number,
  triggeredBy?: "stop_loss" | "take_profit",
): PaperState {
  const pos = state.positions.find((p) => p.id === positionId);
  if (!pos || pos.status !== "open") return state;

  const pnl = positionPnl(pos, closePremium);
  const activity: ActivityItem = {
    id: `act-${Date.now()}`,
    title: `${pos.ticker} paper position closed`,
    detail: triggeredBy
      ? `${triggeredBy === "stop_loss" ? "Stop loss" : "Take profit"} triggered. Realized P&L: ${formatCurrency(pnl)}`
      : `Realized P&L: ${formatCurrency(pnl)}`,
    tone: pnl >= 0 ? "positive" : "warning",
    timestamp: new Date().toISOString(),
  };

  return {
    ...state,
    positions: state.positions.map((p) =>
      p.id === positionId
        ? {
            ...p,
            status: "closed" as const,
            closedAt: new Date().toISOString(),
            closedPremium: closePremium,
            triggeredBy: triggeredBy ?? null,
          }
        : p,
    ),
    activity: [activity, ...state.activity].slice(0, 50),
  };
}

export function checkStopLossTakeProfit(
  state: PaperState,
  livePrices: Record<string, LiveOptionPrice>,
): { state: PaperState; alerts: Array<{ positionId: string; type: "stop_loss" | "take_profit"; ticker: string }> } {
  const alerts: Array<{ positionId: string; type: "stop_loss" | "take_profit"; ticker: string }> = [];

  const newPositions = state.positions.map((pos) => {
    if (pos.status !== "open") return pos;
    const live = livePrices[pos.id];
    if (!live || !live.mid) return pos;

    // For long positions: SL < entry, TP > entry
    // For short positions: SL > entry, TP < entry
    if (pos.stopLoss !== null && pos.stopLoss !== undefined && pos.stopLoss !== 0) {
      const slHit =
        pos.positionSide === "Long"
          ? live.mid <= pos.stopLoss
          : live.mid >= pos.stopLoss;
      if (slHit) {
        alerts.push({ positionId: pos.id, type: "stop_loss", ticker: pos.ticker });
        return {
          ...pos,
          status: "closed" as const,
          closedAt: new Date().toISOString(),
          closedPremium: live.mid,
          triggeredBy: "stop_loss" as const,
        };
      }
    }

    if (pos.takeProfit !== null && pos.takeProfit !== undefined && pos.takeProfit !== 0) {
      const tpHit =
        pos.positionSide === "Long"
          ? live.mid >= pos.takeProfit
          : live.mid <= pos.takeProfit;
      if (tpHit) {
        alerts.push({ positionId: pos.id, type: "take_profit", ticker: pos.ticker });
        return {
          ...pos,
          status: "closed" as const,
          closedAt: new Date().toISOString(),
          closedPremium: live.mid,
          triggeredBy: "take_profit" as const,
        };
      }
    }

    return { ...pos, currentPremium: live.mid };
  });

  const closedCount = newPositions.filter((p) => p.status === "closed" && p.triggeredBy).length;
  const originalClosedCount = state.positions.filter((p) => p.status === "closed" && p.triggeredBy).length;

  let newState = state;
  if (closedCount > originalClosedCount) {
    const newActivities: ActivityItem[] = alerts.map((alert) => ({
      id: `act-${Date.now()}-${alert.positionId}`,
      title: `${alert.ticker} ${alert.type === "stop_loss" ? "stop loss" : "take profit"} triggered`,
      detail: `Position closed automatically at ${alert.type === "stop_loss" ? "stop loss" : "take profit"}.`,
      tone: alert.type === "take_profit" ? "positive" : "warning",
      timestamp: new Date().toISOString(),
    }));

    newState = {
      ...state,
      positions: newPositions,
      activity: [...newActivities, ...state.activity].slice(0, 50),
    };
  } else {
    newState = { ...state, positions: newPositions };
  }

  return { state: newState, alerts };
}

export function positionPnl(position: PaperPosition, markPremium: number): number {
  const contractDelta =
    position.positionSide === "Long"
      ? markPremium - position.entryPremium
      : position.entryPremium - markPremium;
  return contractDelta * 100 * position.quantity;
}

export function computePaperStats(state: PaperState, markPremiums: Record<string, number>) {
  const openPositions = state.positions.filter((p) => p.status === "open");
  const closedPositions = state.positions.filter((p) => p.status === "closed");

  const reservedCapital = openPositions.reduce((sum, p) => sum + p.capitalReserved, 0);

  const unrealizedPnl = openPositions.reduce((sum, p) => {
    const mark = markPremiums[p.id] ?? markPremiums[p.ticker] ?? p.currentPremium;
    return sum + positionPnl(p, mark);
  }, 0);

  const realizedPnl = closedPositions.reduce((sum, p) => {
    const mark = p.closedPremium ?? p.currentPremium;
    return sum + positionPnl({ ...p, positionSide: p.positionSide }, mark);
  }, 0);

  const equity = state.startingBalance + realizedPnl + unrealizedPnl;
  const availableCapital = equity - reservedCapital;

  const winRate =
    closedPositions.length === 0
      ? 0
      : (closedPositions.filter((p) => {
          const mark = p.closedPremium ?? p.currentPremium;
          return positionPnl({ ...p, positionSide: p.positionSide }, mark) > 0;
        }).length /
          closedPositions.length) *
        100;

  return { openPositions, closedPositions, reservedCapital, unrealizedPnl, realizedPnl, equity, availableCapital, winRate };
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value);
}
