import { type SimulationAccount } from "@/types/simulation";

type SimulationStore = {
  accounts: Map<string, SimulationAccount>;
};

const globalStore = globalThis as typeof globalThis & {
  __earningEdgeSimulationStore?: SimulationStore;
};

export function simulationStore() {
  if (!globalStore.__earningEdgeSimulationStore) {
    globalStore.__earningEdgeSimulationStore = { accounts: new Map() };
  }
  return globalStore.__earningEdgeSimulationStore;
}

export function getOrCreateAccount(accountId: string, startingCash = 150000) {
  const store = simulationStore();
  const existing = store.accounts.get(accountId);
  if (existing) {
    if (existing.startingCash !== startingCash) {
      const cashDelta = startingCash - existing.startingCash;
      existing.startingCash = startingCash;
      existing.cashBalance = money(existing.cashBalance + cashDelta);
      existing.totalPortfolioValue = money(existing.totalPortfolioValue + cashDelta);
      existing.buyingPower = money(existing.buyingPower + cashDelta);
      existing.updatedAt = new Date().toISOString();
    }
    reconcileAccountSize(existing);
    return existing;
  }

  const account: SimulationAccount = {
    id: accountId,
    startingCash,
    cashBalance: startingCash,
    openPositions: [],
    closedPositions: [],
    orders: [],
    realizedPnl: 0,
    unrealizedPnl: 0,
    totalPortfolioValue: startingCash,
    buyingPower: startingCash,
    notifications: [],
    updatedAt: new Date().toISOString(),
  };
  store.accounts.set(accountId, account);
  return account;
}

function money(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function reconcileAccountSize(account: SimulationAccount) {
  const positions = [...account.openPositions, ...account.closedPositions];
  const realizedPnl = positions.reduce((sum, position) => sum + position.realizedPnl, 0);
  const unrealizedPnl = account.openPositions.reduce(
    (sum, position) => sum + position.unrealizedPnl,
    0,
  );
  const longValue = account.openPositions
    .filter((position) => position.positionSide === "LONG")
    .reduce((sum, position) => sum + position.currentMarketValue, 0);
  const shortLiability = account.openPositions
    .filter((position) => position.positionSide === "SHORT")
    .reduce((sum, position) => sum + position.currentMarketValue, 0);

  const targetPortfolioValue = money(account.startingCash + realizedPnl + unrealizedPnl);
  const portfolioDelta = money(targetPortfolioValue - account.totalPortfolioValue);
  if (Math.abs(portfolioDelta) < 0.01) return;

  account.cashBalance = money(targetPortfolioValue - longValue + shortLiability);
  account.totalPortfolioValue = targetPortfolioValue;
  account.buyingPower = money(account.buyingPower + portfolioDelta);
  account.updatedAt = new Date().toISOString();
}

export function findAccountByOrder(orderId: string) {
  for (const account of simulationStore().accounts.values()) {
    if (account.orders.some((order) => order.id === orderId)) return account;
  }
  return null;
}

export function findAccountByPosition(positionId: string) {
  for (const account of simulationStore().accounts.values()) {
    if (
      account.openPositions.some((position) => position.id === positionId) ||
      account.closedPositions.some((position) => position.id === positionId)
    ) {
      return account;
    }
  }
  return null;
}
