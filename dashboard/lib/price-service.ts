import { type PaperPosition } from "@/lib/dashboard-data";

const API_BASE =
  process.env.NEXT_PUBLIC_EARNING_EDGE_API_BASE_URL?.replace(/\/$/, "") ??
  "http://127.0.0.1:8000";

export type LiveOptionPrice = {
  source: string;
  ticker: string;
  strike: number;
  expiry: string;
  option_type: string;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  last_trade_price: number | null;
  volume: number | null;
  open_interest: number | null;
  implied_volatility: number | null;
  delta: number | null;
  timestamp: string;
};

export async function fetchOptionPrice(position: PaperPosition): Promise<LiveOptionPrice | null> {
  try {
    const response = await fetch(`${API_BASE}/api/dashboard/option-price`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: position.ticker,
        strike: position.strike,
        expiry: position.expiry,
        option_type: position.optionType.toLowerCase(),
        position_side: position.positionSide.toLowerCase(),
      }),
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as LiveOptionPrice;
  } catch {
    return null;
  }
}

export async function fetchMultiplePrices(positions: PaperPosition[]): Promise<Record<string, LiveOptionPrice>> {
  const results: Record<string, LiveOptionPrice> = {};
  await Promise.all(
    positions.map(async (pos) => {
      const price = await fetchOptionPrice(pos);
      if (price) results[pos.id] = price;
    }),
  );
  return results;
}
