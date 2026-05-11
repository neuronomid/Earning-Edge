import Decimal from "decimal.js";
import {
  type OrderSide,
  type PlaceOrderPayload,
  type PlaceOrderResponse,
  type SimulationAccount,
  type SimulationOrder,
  type SimulationPosition,
} from "@/types/simulation";
import { type OptionQuote } from "@/types/option";
import { fetchLatestOptionQuote, fetchLatestOptionQuotes } from "@/lib/simulation/optionQuoteService";
import {
  ensurePositiveInteger,
  executionPrice,
  money,
  optionMarkPrice,
  optionNotional,
  premium,
  toDecimal,
} from "@/lib/simulation/pricingUtils";
import { shortMarginRequirement } from "@/lib/simulation/riskCalculationService";
import { finalizeAccount } from "@/lib/simulation/portfolioService";
import { getOrCreateAccount } from "@/lib/simulation/simulationStore";

export async function placeSimulationOrder(
  payload: PlaceOrderPayload,
  startingCash?: number,
): Promise<PlaceOrderResponse> {
  const account = getOrCreateAccount(payload.accountId, startingCash);
  const quote = await fetchLatestOptionQuote(payload.contract, payload.accountId);
  const order = buildOrder(payload);
  const fillPrice = getFillPrice(order, quote);

  if (fillPrice === null) {
    order.status = "PENDING";
    account.orders = [order, ...account.orders];
    return { account: finalizeAccount(account), order };
  }

  const rejectionReason = validateFill(account, order, fillPrice);
  if (rejectionReason) {
    order.status = "REJECTED";
    order.rejectionReason = rejectionReason;
    account.orders = [order, ...account.orders];
    return { account: finalizeAccount(account), order };
  }

  fillOrder(account, order, fillPrice, quote);
  account.orders = [order, ...account.orders];
  account.notifications = [
    {
      id: `note-${crypto.randomUUID()}`,
      type: "SUCCESS" as const,
      message: `${order.side} ${order.quantity} ${order.symbol} ${order.optionType} filled at $${fillPrice.toFixed(2)}.`,
      createdAt: new Date().toISOString(),
    },
    ...account.notifications,
  ].slice(0, 20);
  return { account: finalizeAccount(account), order };
}

export async function processPendingOrders(account: SimulationAccount) {
  const pending = account.orders.filter((order) => order.status === "PENDING");
  if (pending.length === 0) return finalizeAccount(account);

  const quotes = await fetchLatestOptionQuotes(
    pending.map((order) => order.contract),
    account.id,
  );
  for (const order of pending) {
    const quote = quotes[order.contractId];
    if (!quote) continue;
    const fillPrice = getFillPrice(order, quote);
    if (fillPrice === null) continue;
    const rejectionReason = validateFill(account, order, fillPrice);
    if (rejectionReason) {
      order.status = "REJECTED";
      order.rejectionReason = rejectionReason;
      continue;
    }
    fillOrder(account, order, fillPrice, quote);
    account.notifications = [
      {
        id: `note-${crypto.randomUUID()}`,
        type: "SUCCESS" as const,
        message: `Limit order filled: ${order.side} ${order.quantity} ${order.symbol} at $${fillPrice.toFixed(2)}.`,
        createdAt: new Date().toISOString(),
      },
      ...account.notifications,
    ].slice(0, 20);
  }

  return finalizeAccount(account);
}

export function cancelOrder(account: SimulationAccount, orderId: string) {
  const order = account.orders.find((item) => item.id === orderId);
  if (!order || order.status !== "PENDING") return null;
  order.status = "CANCELLED";
  account.notifications = [
    {
      id: `note-${crypto.randomUUID()}`,
      type: "INFO" as const,
      message: `Cancelled ${order.symbol} ${order.optionType} limit order.`,
      createdAt: new Date().toISOString(),
    },
    ...account.notifications,
  ].slice(0, 20);
  return finalizeAccount(account);
}

function buildOrder(payload: PlaceOrderPayload): SimulationOrder {
  const quantity = ensurePositiveInteger(payload.quantity);
  return {
    id: `ord-${crypto.randomUUID()}`,
    accountId: payload.accountId,
    symbol: payload.symbol.toUpperCase(),
    contractId: payload.contract.contractId,
    contract: payload.contract,
    optionType: payload.contract.optionType,
    side: payload.side,
    orderType: payload.orderType,
    quantity,
    limitPrice: payload.limitPrice ?? null,
    fillPrice: null,
    status: "PENDING",
    createdAt: new Date().toISOString(),
    filledAt: null,
    stopLoss: payload.stopLoss ?? null,
    takeProfit: payload.takeProfit ?? null,
    triggerReason: null,
    strategy: payload.strategy ?? null,
  };
}

function getFillPrice(order: SimulationOrder, quote: OptionQuote) {
  const marketPrice = executionPrice(quote, order.side);
  if (marketPrice.lte(0)) return null;

  if (order.orderType === "MARKET") return premium(marketPrice);

  if (order.limitPrice === null || order.limitPrice <= 0) return null;
  if (order.side === "BUY") {
    const ask = quote.ask === null ? marketPrice : toDecimal(quote.ask);
    return ask.lte(order.limitPrice) ? premium(ask) : null;
  }
  const bid = quote.bid === null ? marketPrice : toDecimal(quote.bid);
  return bid.gte(order.limitPrice) ? premium(bid) : null;
}

function validateFill(account: SimulationAccount, order: SimulationOrder, fillPrice: number) {
  const quantity = toDecimal(order.quantity);
  const gross = optionNotional(fillPrice, quantity);

  if (order.side === "BUY") {
    const closingShort = account.openPositions.find(
      (position) => position.contractId === order.contractId && position.positionSide === "SHORT",
    );
    if (!closingShort && toDecimal(account.cashBalance).lt(gross)) {
      return "Insufficient cash for the simulated long option purchase.";
    }
    if (closingShort && toDecimal(account.cashBalance).lt(gross)) {
      return "Insufficient cash to buy back the simulated short option.";
    }
  }

  if (order.side === "SELL") {
    const closingLong = account.openPositions.find(
      (position) => position.contractId === order.contractId && position.positionSide === "LONG",
    );
    if (!closingLong) {
      const margin = shortMarginRequirement(order.contract, order.quantity);
      if (toDecimal(account.buyingPower).lt(margin)) {
        return "Insufficient buying power for the simulated short option margin reserve.";
      }
    }
  }

  return null;
}

function fillOrder(
  account: SimulationAccount,
  order: SimulationOrder,
  fillPrice: number,
  quote: OptionQuote,
) {
  order.status = "FILLED";
  order.fillPrice = fillPrice;
  order.filledAt = new Date().toISOString();

  let remainingQuantity = order.quantity;
  if (order.side === "SELL") {
    remainingQuantity = closePosition(account, order, "LONG", fillPrice, remainingQuantity);
    if (remainingQuantity > 0) openOrAddPosition(account, order, "SHORT", fillPrice, remainingQuantity, quote);
  } else {
    remainingQuantity = closePosition(account, order, "SHORT", fillPrice, remainingQuantity);
    if (remainingQuantity > 0) openOrAddPosition(account, order, "LONG", fillPrice, remainingQuantity, quote);
  }
}

function openOrAddPosition(
  account: SimulationAccount,
  order: SimulationOrder,
  positionSide: "LONG" | "SHORT",
  fillPrice: number,
  quantity: number,
  quote: OptionQuote,
) {
  const existing = account.openPositions.find(
    (position) => position.contractId === order.contractId && position.positionSide === positionSide,
  );
  const fillValue = optionNotional(fillPrice, quantity);
  account.cashBalance =
    positionSide === "LONG"
      ? money(toDecimal(account.cashBalance).minus(fillValue))
      : money(toDecimal(account.cashBalance).plus(fillValue));

  if (existing) {
    const totalQuantity = existing.quantity + quantity;
    const weightedEntry = toDecimal(existing.averageEntryPrice)
      .mul(existing.quantity)
      .plus(toDecimal(fillPrice).mul(quantity))
      .div(totalQuantity);
    existing.quantity = totalQuantity;
    existing.averageEntryPrice = premium(weightedEntry);
    existing.stopLoss = order.stopLoss ?? existing.stopLoss;
    existing.takeProfit = order.takeProfit ?? existing.takeProfit;
    return;
  }

  const mark = optionMarkPrice(quote, positionSide);
  account.openPositions = [
    {
      id: `pos-${crypto.randomUUID()}`,
      accountId: account.id,
      symbol: order.symbol,
      contractId: order.contractId,
      contract: {
        ...order.contract,
        bid: quote.bid,
        ask: quote.ask,
        mid: quote.mid,
        lastPrice: quote.lastPrice,
        source: quote.source,
      },
      optionType: order.optionType,
      positionSide,
      strike: order.contract.strike,
      expiration: order.contract.expiration,
      quantity,
      averageEntryPrice: fillPrice,
      entryUnderlyingPrice: order.contract.underlyingPrice ?? null,
      currentBid: quote.bid,
      currentAsk: quote.ask,
      currentMid: quote.mid,
      currentMarkPrice: premium(mark),
      currentMarketValue: money(optionNotional(mark, quantity)),
      costBasis: money(optionNotional(fillPrice, quantity)),
      unrealizedPnl: 0,
      unrealizedPnlPercent: 0,
      realizedPnl: 0,
      stopLoss: order.stopLoss,
      takeProfit: order.takeProfit,
      status: "OPEN",
      strategy: order.strategy ?? null,
      closeReason: null,
      openedAt: new Date().toISOString(),
      closedAt: null,
      closedPrice: null,
      lastQuoteAt: quote.timestamp,
    },
    ...account.openPositions,
  ];
}

function closePosition(
  account: SimulationAccount,
  order: SimulationOrder,
  closingSide: "LONG" | "SHORT",
  fillPrice: number,
  quantity: number,
) {
  const position = account.openPositions.find(
    (item) => item.contractId === order.contractId && item.positionSide === closingSide,
  );
  if (!position || quantity <= 0) return quantity;

  const closeQuantity = Math.min(position.quantity, quantity);
  const closeValue = optionNotional(fillPrice, closeQuantity);
  const basis = optionNotional(position.averageEntryPrice, closeQuantity);
  const realized = closingSide === "LONG" ? closeValue.minus(basis) : basis.minus(closeValue);

  account.cashBalance =
    closingSide === "LONG"
      ? money(toDecimal(account.cashBalance).plus(closeValue))
      : money(toDecimal(account.cashBalance).minus(closeValue));

  position.realizedPnl = money(toDecimal(position.realizedPnl).plus(realized));
  position.quantity -= closeQuantity;

  if (position.quantity <= 0) {
    const closed: SimulationPosition = {
      ...position,
      quantity: closeQuantity,
      status: "CLOSED",
      closeReason: "MANUAL",
      closedAt: new Date().toISOString(),
      closedPrice: fillPrice,
      currentMarkPrice: fillPrice,
      currentMarketValue: money(closeValue),
      unrealizedPnl: 0,
      unrealizedPnlPercent: 0,
    };
    account.openPositions = account.openPositions.filter((item) => item.id !== position.id);
    account.closedPositions = [closed, ...account.closedPositions];
  }

  return quantity - closeQuantity;
}
