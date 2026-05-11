import Decimal from "decimal.js";
import { type OptionContract } from "@/types/option";
import { type OrderSide } from "@/types/simulation";
import {
  CONTRACT_MULTIPLIER,
  commission,
  executionPrice,
  money,
  optionNotional,
  toDecimal,
} from "@/lib/simulation/pricingUtils";

export type OrderRiskPreview = {
  estimatedCost: number;
  fees: number;
  totalDebit: number;
  totalCredit: number;
  maxLoss: string;
  maxProfit: string;
  breakeven: number | null;
  buyingPowerAfterOrder: number;
  warning: string | null;
};

export function calculateOrderRisk(params: {
  contract: OptionContract;
  side: OrderSide;
  quantity: number;
  availableCash: number;
  limitPrice?: number | null;
}) {
  const price =
    params.limitPrice && params.limitPrice > 0
      ? toDecimal(params.limitPrice)
      : executionPrice(params.contract, params.side);
  const quantity = toDecimal(params.quantity);
  const gross = optionNotional(price, quantity);
  const fees = commission(quantity);
  const debit = params.side === "BUY" ? gross.plus(fees) : new Decimal(0);
  const credit = params.side === "SELL" ? gross.minus(fees) : new Decimal(0);
  const risk = optionRiskText(params.contract, params.side, price, quantity);
  const buyingPowerAfterOrder =
    params.side === "BUY"
      ? toDecimal(params.availableCash).minus(debit)
      : toDecimal(params.availableCash).plus(credit).minus(shortMarginRequirement(params.contract, params.quantity));

  return {
    estimatedCost: money(gross),
    fees: money(fees),
    totalDebit: money(debit),
    totalCredit: money(credit),
    maxLoss: risk.maxLoss,
    maxProfit: risk.maxProfit,
    breakeven: risk.breakeven === null ? null : money(risk.breakeven),
    buyingPowerAfterOrder: money(buyingPowerAfterOrder),
    warning: risk.warning,
  } satisfies OrderRiskPreview;
}

export function shortMarginRequirement(contract: OptionContract, quantity: number) {
  const strikeRequirement = toDecimal(contract.strike).mul(CONTRACT_MULTIPLIER).mul(quantity).mul("0.2");
  const premiumRequirement = optionNotional(
    contract.mid ?? contract.lastPrice ?? contract.bid ?? contract.ask ?? 0,
    quantity,
  );
  return Decimal.max(strikeRequirement, premiumRequirement.mul(2));
}

function optionRiskText(
  contract: OptionContract,
  side: OrderSide,
  price: Decimal,
  quantity: Decimal,
) {
  const strike = toDecimal(contract.strike);
  if (side === "BUY" && contract.optionType === "CALL") {
    return {
      maxLoss: formatMoney(optionNotional(price, quantity)),
      maxProfit: "Unlimited",
      breakeven: strike.plus(price),
      warning: null,
    };
  }
  if (side === "BUY" && contract.optionType === "PUT") {
    return {
      maxLoss: formatMoney(optionNotional(price, quantity)),
      maxProfit: formatMoney(strike.minus(price).mul(CONTRACT_MULTIPLIER).mul(quantity)),
      breakeven: strike.minus(price),
      warning: null,
    };
  }
  if (side === "SELL" && contract.optionType === "CALL") {
    return {
      maxLoss: "Unlimited",
      maxProfit: formatMoney(optionNotional(price, quantity)),
      breakeven: strike.plus(price),
      warning: "Short calls can have unlimited max loss. Simulator margin is only an approximation.",
    };
  }
  return {
    maxLoss: formatMoney(strike.minus(price).mul(CONTRACT_MULTIPLIER).mul(quantity)),
    maxProfit: formatMoney(optionNotional(price, quantity)),
    breakeven: strike.minus(price),
    warning: "Short puts can lose a large amount if the stock falls toward zero.",
  };
}

function formatMoney(value: Decimal | number | string) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(money(value));
}
