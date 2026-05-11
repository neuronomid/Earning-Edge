import Decimal from "decimal.js";
import { type OptionContract, type OptionQuote } from "@/types/option";
import { type OrderSide, type PositionSide } from "@/types/simulation";

export const CONTRACT_MULTIPLIER = new Decimal(100);
export const DEFAULT_COMMISSION_PER_CONTRACT = new Decimal(0);

type DecimalInput = Decimal | number | string;

export function toDecimal(value: DecimalInput | null | undefined) {
  if (value === null || value === undefined || value === "") {
    return new Decimal(0);
  }
  return new Decimal(value);
}

export function money(value: DecimalInput) {
  return new Decimal(value).toDecimalPlaces(2).toNumber();
}

export function premium(value: DecimalInput) {
  return new Decimal(value).toDecimalPlaces(4).toNumber();
}

export function optionMarkPrice(
  quote: Pick<OptionQuote, "bid" | "ask" | "mid" | "lastPrice">,
  side: PositionSide = "LONG",
) {
  if (quote.mid !== null && quote.mid > 0) return toDecimal(quote.mid);
  if (quote.bid !== null && quote.ask !== null && quote.bid > 0 && quote.ask > 0) {
    return toDecimal(quote.bid).plus(quote.ask).div(2);
  }
  if (quote.lastPrice !== null && quote.lastPrice > 0) return toDecimal(quote.lastPrice);
  if (side === "LONG" && quote.bid !== null && quote.bid > 0) return toDecimal(quote.bid);
  if (side === "SHORT" && quote.ask !== null && quote.ask > 0) return toDecimal(quote.ask);
  if (quote.ask !== null && quote.ask > 0) return toDecimal(quote.ask);
  if (quote.bid !== null && quote.bid > 0) return toDecimal(quote.bid);
  return new Decimal(0);
}

export function executionPrice(
  quote: Pick<OptionQuote, "bid" | "ask" | "mid" | "lastPrice">,
  side: OrderSide,
) {
  const preferred = side === "BUY" ? quote.ask : quote.bid;
  if (preferred !== null && preferred > 0) return toDecimal(preferred);
  return optionMarkPrice(quote, side === "BUY" ? "LONG" : "SHORT");
}

export function optionNotional(price: DecimalInput, quantity: DecimalInput) {
  return toDecimal(price).mul(CONTRACT_MULTIPLIER).mul(quantity);
}

export function commission(quantity: DecimalInput) {
  return DEFAULT_COMMISSION_PER_CONTRACT.mul(quantity);
}

export function normalizeQuote(contract: OptionContract): OptionQuote {
  const bid = contract.bid;
  const ask = contract.ask;
  const mid =
    contract.mid ??
    (bid !== null && ask !== null && bid > 0 && ask > 0
      ? premium(toDecimal(bid).plus(ask).div(2))
      : contract.lastPrice);

  return {
    ...contract,
    bid,
    ask,
    mid,
    timestamp: new Date().toISOString(),
  };
}

export function ensurePositiveInteger(value: unknown) {
  const quantity = Number(value);
  if (!Number.isInteger(quantity) || quantity <= 0) {
    throw new Error("Quantity must be a positive whole number.");
  }
  return quantity;
}

export function optionContractId(contract: {
  recommendationId?: string | null;
  symbol: string;
  optionType: string;
  strike: number;
  expiration: string;
}) {
  const prefix = contract.recommendationId ?? "manual";
  return [
    prefix,
    contract.symbol.toUpperCase(),
    contract.expiration,
    contract.optionType.toUpperCase(),
    Number(contract.strike).toFixed(2),
  ].join(":");
}
