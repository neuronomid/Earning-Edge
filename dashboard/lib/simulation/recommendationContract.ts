import { type DashboardRecommendation } from "@/lib/dashboard-data";
import { type OptionContract } from "@/types/option";
import { optionContractId } from "@/lib/simulation/pricingUtils";

export function recommendationToContract(rec: DashboardRecommendation): OptionContract {
  const optionType = rec.optionType.toUpperCase() === "PUT" ? "PUT" : "CALL";
  const fallbackId = optionContractId({
    recommendationId: rec.id,
    symbol: rec.ticker,
    optionType,
    strike: rec.strike,
    expiration: rec.expiry,
  });

  return {
    contractId: rec.contractId || fallbackId,
    symbol: rec.ticker.toUpperCase(),
    optionType,
    strike: rec.strike,
    expiration: rec.expiry,
    bid: rec.bidPrice ?? null,
    ask: rec.askPrice ?? null,
    mid: rec.midPrice ?? rec.markPremium ?? rec.suggestedEntry ?? null,
    lastPrice: rec.lastPrice ?? null,
    source: rec.contractSource || "backend_recommendation",
    underlyingPrice: rec.currentPrice,
    recommendationId: rec.id,
  };
}
