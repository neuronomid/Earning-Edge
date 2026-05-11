import { getOrCreateAccount, simulationStore } from "@/lib/simulation/simulationStore";

describe("simulationStore", () => {
  beforeEach(() => {
    simulationStore().accounts.clear();
  });

  it("rebases paper cash when account size changes after trading activity", () => {
    const account = getOrCreateAccount("acct-1", 5000);
    account.orders = [{ id: "ord-1" } as never];

    const updated = getOrCreateAccount("acct-1", 10000);

    expect(updated.startingCash).toBe(10000);
    expect(updated.cashBalance).toBe(10000);
    expect(updated.totalPortfolioValue).toBe(10000);
    expect(updated.buyingPower).toBe(10000);
    expect(updated.orders).toHaveLength(1);
  });

  it("repairs stale paper accounts whose starting cash changed before cash was rebased", () => {
    const account = getOrCreateAccount("acct-2", 10000);
    account.cashBalance = 5116;
    account.totalPortfolioValue = 4977.5;
    account.buyingPower = 3616;
    account.closedPositions = [{ realizedPnl: -17 } as never];
    account.openPositions = [
      {
        positionSide: "SHORT",
        currentMarketValue: 138.5,
        unrealizedPnl: -5.5,
        realizedPnl: 0,
      } as never,
    ];

    const updated = getOrCreateAccount("acct-2", 10000);

    expect(updated.cashBalance).toBe(10116);
    expect(updated.totalPortfolioValue).toBe(9977.5);
    expect(updated.buyingPower).toBe(8616);
  });
});
