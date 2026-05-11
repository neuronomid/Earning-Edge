import Decimal from "decimal.js";
import { type OptionQuote } from "@/types/option";
import {
  type PositionSide,
  type SimulationAccount,
  type SimulationNotification,
  type SimulationOrder,
  type SimulationPosition,
} from "@/types/simulation";
import { fetchLatestOptionQuotes } from "@/lib/simulation/optionQuoteService";
import {
  money,
  optionMarkPrice,
  optionNotional,
  premium,
  toDecimal,
} from "@/lib/simulation/pricingUtils";
import { shortMarginRequirement } from "@/lib/simulation/riskCalculationService";

export async function refreshAccount(account: SimulationAccount) {
  const contracts = [
    ...account.openPositions.map((position) => position.contract),
    ...account.orders.filter((order) => order.status === "PENDING").map((order) => order.contract),
  ];
  const uniqueContracts = Array.from(
    new Map(contracts.map((contract) => [contract.contractId, contract])).values(),
  );
  const quotes = await fetchLatestOptionQuotes(uniqueContracts, account.id);

  account.openPositions = account.openPositions.map((position) =>
    applyQuoteToPosition(position, quotes[position.contractId]),
  );

  for (const position of [...account.openPositions]) {
    const quote = quotes[position.contractId];
    if (!quote) continue;
    const trigger = triggeredExit(position);
    if (trigger) {
      closePositionAtMarket(account, position.id, quote, trigger);
    }
  }

  return finalizeAccount(account);
}

export function applyQuoteToPosition(position: SimulationPosition, quote?: OptionQuote) {
  if (!quote) return recalculatePosition(position);
  return recalculatePosition({
    ...position,
    contract: {
      ...position.contract,
      bid: quote.bid,
      ask: quote.ask,
      mid: quote.mid,
      lastPrice: quote.lastPrice,
      source: quote.source,
      underlyingPrice: quote.underlyingPrice ?? position.contract.underlyingPrice,
    },
    currentBid: quote.bid,
    currentAsk: quote.ask,
    currentMid: quote.mid,
    currentMarkPrice: premium(optionMarkPrice(quote, position.positionSide)),
    lastQuoteAt: quote.timestamp,
  });
}

export function recalculatePosition(position: SimulationPosition) {
  const mark = toDecimal(position.currentMarkPrice);
  const quantity = toDecimal(position.quantity);
  const value = optionNotional(mark, quantity);
  const basis = optionNotional(position.averageEntryPrice, quantity);
  const pnl =
    position.positionSide === "LONG" ? value.minus(basis) : basis.minus(value);
  const pnlPercent = basis.eq(0) ? new Decimal(0) : pnl.div(basis).mul(100);

  return {
    ...position,
    currentMarketValue: money(value),
    costBasis: money(basis),
    unrealizedPnl: money(pnl),
    unrealizedPnlPercent: pnlPercent.toDecimalPlaces(2).toNumber(),
  };
}

export function closePositionAtMarket(
  account: SimulationAccount,
  positionId: string,
  quote: OptionQuote,
  triggerReason?: "STOP_LOSS" | "TAKE_PROFIT",
) {
  const position = account.openPositions.find((item) => item.id === positionId);
  if (!position) return null;
  const closePrice =
    position.positionSide === "LONG"
      ? quote.bid !== null
        ? toDecimal(quote.bid)
        : optionMarkPrice(quote, "LONG")
      : quote.ask !== null
        ? toDecimal(quote.ask)
        : optionMarkPrice(quote, "SHORT");

  const proceedsOrCost = optionNotional(closePrice, position.quantity);
  const basis = optionNotional(position.averageEntryPrice, position.quantity);
  const realized =
    position.positionSide === "LONG" ? proceedsOrCost.minus(basis) : basis.minus(proceedsOrCost);

  account.cashBalance =
    position.positionSide === "LONG"
      ? money(toDecimal(account.cashBalance).plus(proceedsOrCost))
      : money(toDecimal(account.cashBalance).minus(proceedsOrCost));

  const closed = recalculatePosition({
    ...position,
    quantity: position.quantity,
    status: "CLOSED",
    closeReason: (triggerReason ?? "MANUAL") as import("@/types/simulation").CloseReason,
    closedAt: new Date().toISOString(),
    closedPrice: premium(closePrice),
    currentMarkPrice: premium(closePrice),
    realizedPnl: money(toDecimal(position.realizedPnl).plus(realized)),
    unrealizedPnl: 0,
    unrealizedPnlPercent: 0,
  });

  account.openPositions = account.openPositions.filter((item) => item.id !== position.id);
  account.closedPositions = [closed, ...account.closedPositions];
  account.orders = [
    buildClosingOrder(account.id, closed, premium(closePrice), triggerReason),
    ...account.orders,
  ];
  if (triggerReason) {
    account.notifications = [
      notification(
        triggerReason === "STOP_LOSS" ? "WARNING" : "SUCCESS",
        `${closed.symbol} ${triggerReason === "STOP_LOSS" ? "stop loss" : "take profit"} triggered at $${premium(closePrice).toFixed(2)}.`,
      ),
      ...account.notifications,
    ].slice(0, 20);
  }
  return closed;
}

export function finalizeAccount(account: SimulationAccount) {
  account.openPositions = account.openPositions.map(recalculatePosition);
  const realizedPnl = [...account.openPositions, ...account.closedPositions].reduce(
    (sum, position) => sum.plus(position.realizedPnl),
    new Decimal(0),
  );
  const unrealizedPnl = account.openPositions.reduce(
    (sum, position) => sum.plus(position.unrealizedPnl),
    new Decimal(0),
  );
  const longValue = account.openPositions
    .filter((position) => position.positionSide === "LONG")
    .reduce((sum, position) => sum.plus(position.currentMarketValue), new Decimal(0));
  const shortLiability = account.openPositions
    .filter((position) => position.positionSide === "SHORT")
    .reduce((sum, position) => sum.plus(position.currentMarketValue), new Decimal(0));
  const shortMargin = account.openPositions
    .filter((position) => position.positionSide === "SHORT")
    .reduce(
      (sum, position) => sum.plus(shortMarginRequirement(position.contract, position.quantity)),
      new Decimal(0),
    );

  account.realizedPnl = money(realizedPnl);
  account.unrealizedPnl = money(unrealizedPnl);
  account.totalPortfolioValue = money(toDecimal(account.cashBalance).plus(longValue).minus(shortLiability));
  account.buyingPower = money(toDecimal(account.cashBalance).minus(shortMargin));
  account.updatedAt = new Date().toISOString();
  return account;
}

export function updatePositionRisk(
  account: SimulationAccount,
  positionId: string,
  stopLoss: number | null,
  takeProfit: number | null,
) {
  account.openPositions = account.openPositions.map((position) =>
    position.id === positionId ? { ...position, stopLoss, takeProfit } : position,
  );
  account.notifications = [
    notification("INFO", "Stop loss / take profit controls updated."),
    ...account.notifications,
  ].slice(0, 20);
  return finalizeAccount(account);
}

function triggeredExit(position: SimulationPosition) {
  const mark = position.currentMarkPrice;
  if (position.positionSide === "LONG") {
    if (position.stopLoss !== null && mark <= position.stopLoss) return "STOP_LOSS" as const;
    if (position.takeProfit !== null && mark >= position.takeProfit) return "TAKE_PROFIT" as const;
  } else {
    if (position.stopLoss !== null && mark >= position.stopLoss) return "STOP_LOSS" as const;
    if (position.takeProfit !== null && mark <= position.takeProfit) return "TAKE_PROFIT" as const;
  }
  return null;
}

function buildClosingOrder(
  accountId: string,
  position: SimulationPosition,
  fillPrice: number,
  triggerReason?: "STOP_LOSS" | "TAKE_PROFIT",
): SimulationOrder {
  return {
    id: `ord-${crypto.randomUUID()}`,
    accountId,
    symbol: position.symbol,
    contractId: position.contractId,
    contract: position.contract,
    optionType: position.optionType,
    side: position.positionSide === "LONG" ? "SELL" : "BUY",
    orderType: "MARKET",
    quantity: position.quantity,
    limitPrice: null,
    fillPrice,
    status: "FILLED",
    createdAt: new Date().toISOString(),
    filledAt: new Date().toISOString(),
    stopLoss: null,
    takeProfit: null,
    triggerReason,
    strategy: position.strategy ?? null,
  };
}

function notification(
  type: SimulationNotification["type"],
  message: string,
): SimulationNotification {
  return {
    id: `note-${crypto.randomUUID()}`,
    type,
    message,
    createdAt: new Date().toISOString(),
  };
}
