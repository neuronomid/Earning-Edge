export function formatOptionSymbol(
  ticker: string,
  expiry: string,
  optionType: "CALL" | "PUT" | "call" | "put",
  strike: number,
): string {
  const dateStr = expiry.replace(/-/g, "").slice(2);
  const typeChar = optionType.toUpperCase() === "CALL" ? "C" : "P";
  const strikePadded = Math.round(strike * 1000).toString().padStart(8, "0");
  return `${ticker.toUpperCase()}${dateStr}${typeChar}${strikePadded}`;
}

export function resolveOptionMidPrice(
  bid: number | null | undefined,
  ask: number | null | undefined,
  last: number | null | undefined,
  fallback: number | null | undefined,
): { price: number; mode: "bid_ask_mid" | "last" | "estimated" | "unavailable" } {
  if (bid != null && ask != null && bid > 0 && ask > 0) {
    return { price: (bid + ask) / 2, mode: "bid_ask_mid" };
  }
  if (last != null && last > 0) return { price: last, mode: "last" };
  if (fallback != null && fallback > 0) return { price: fallback, mode: "estimated" };
  return { price: 0, mode: "unavailable" };
}
