import { type OptionContract, type OptionQuote } from "@/types/option";
import { normalizeQuote, premium } from "@/lib/simulation/pricingUtils";

const API_BASE =
  (process.env.EARNING_EDGE_API_BASE_URL ?? process.env.NEXT_PUBLIC_EARNING_EDGE_API_BASE_URL ?? "http://127.0.0.1:8000").replace(
    /\/$/,
    "",
  );

type BackendOptionPrice = {
  source?: string;
  ticker?: string;
  strike?: number;
  expiry?: string;
  option_type?: string;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  last_trade_price?: number | null;
  timestamp?: string;
};

type BackendStockPrice = {
  price?: number;
};

export async function fetchLatestOptionQuote(
  contract: OptionContract,
  accountId?: string,
): Promise<OptionQuote> {
  try {
    const userSuffix = accountId ? `?user_id=${encodeURIComponent(accountId)}` : "";
    const response = await fetch(`${API_BASE}/api/dashboard/option-price${userSuffix}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: contract.symbol,
        strike: contract.strike,
        expiry: contract.expiration,
        option_type: contract.optionType.toLowerCase(),
        position_side: "long",
      }),
      cache: "no-store",
    });

    if (!response.ok) return normalizeQuote(contract);
    const payload = (await response.json()) as BackendOptionPrice;
    const underlyingPrice = await fetchLatestUnderlyingPrice(contract.symbol, accountId);
    const bid = payload.bid ?? contract.bid;
    const ask = payload.ask ?? contract.ask;
    const mid =
      payload.mid ??
      contract.mid ??
      (bid !== null && ask !== null ? premium((bid + ask) / 2) : null);

    return {
      ...contract,
      source: payload.source ?? contract.source,
      bid,
      ask,
      mid,
      lastPrice: payload.last_trade_price ?? contract.lastPrice,
      underlyingPrice: underlyingPrice ?? contract.underlyingPrice ?? null,
      timestamp: payload.timestamp ?? new Date().toISOString(),
    };
  } catch {
    return normalizeQuote(contract);
  }
}

export async function fetchLatestOptionQuotes(contracts: OptionContract[], accountId?: string) {
  const pairs = await Promise.all(
    contracts.map(
      async (contract) =>
        [contract.contractId, await fetchLatestOptionQuote(contract, accountId)] as const,
    ),
  );
  return Object.fromEntries(pairs);
}

async function fetchLatestUnderlyingPrice(symbol: string, accountId?: string) {
  try {
    const params = new URLSearchParams({ ticker: symbol.toUpperCase() });
    if (accountId) params.set("user_id", accountId);
    const response = await fetch(`${API_BASE}/api/dashboard/stock-price?${params.toString()}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    const payload = (await response.json()) as BackendStockPrice;
    return payload.price ?? null;
  } catch {
    return null;
  }
}
