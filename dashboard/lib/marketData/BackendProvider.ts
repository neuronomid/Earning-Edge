import { type MarketDataProvider, type OptionQuoteRequest, type OptionQuoteResult, type StockQuote } from "./MarketDataProvider";

const API_BASE = (
  process.env.EARNING_EDGE_API_BASE_URL ??
  process.env.NEXT_PUBLIC_EARNING_EDGE_API_BASE_URL ??
  "http://127.0.0.1:8000"
).replace(/\/$/, "");

type BackendPriceResponse = {
  source?: string;
  ticker?: string;
  strike?: number;
  expiry?: string;
  option_type?: string;
  bid?: number | null;
  ask?: number | null;
  mid?: number | null;
  last_trade_price?: number | null;
  implied_volatility?: number | null;
  delta?: number | null;
  gamma?: number | null;
  theta?: number | null;
  vega?: number | null;
  volume?: number | null;
  open_interest?: number | null;
  timestamp?: string;
};

type BackendStockPriceResponse = {
  ticker?: string;
  price?: number;
  bid?: number | null;
  ask?: number | null;
  previousClose?: number | null;
  change?: number | null;
  changePercent?: number | null;
  timestamp?: string;
  source?: string;
  dataMode?: string;
};

export class BackendProvider implements MarketDataProvider {
  readonly name = "backend";

  isAvailable() {
    return true;
  }

  async fetchOptionQuote(request: OptionQuoteRequest): Promise<OptionQuoteResult> {
    const userSuffix = request.userId ? `?user_id=${encodeURIComponent(request.userId)}` : "";
    const response = await fetch(`${API_BASE}/api/dashboard/option-price${userSuffix}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ticker: request.ticker,
        strike: request.strike,
        expiry: request.expiry,
        option_type: request.optionType,
        position_side: "long",
      }),
      cache: "no-store",
    });

    if (!response.ok) {
      throw new Error(`Backend option-price returned ${response.status}`);
    }

    const data = (await response.json()) as BackendPriceResponse;
    let underlyingPrice: number | null = null;
    try {
      const stock = await this.fetchStockQuote(request.ticker, request.userId);
      underlyingPrice = stock.price;
    } catch {
      underlyingPrice = null;
    }
    const source = data.source ?? "backend";
    const dataMode = source === "alpaca" ? "REAL_TIME" : "DELAYED";
    const bid = data.bid ?? null;
    const ask = data.ask ?? null;
    const mid =
      data.mid ??
      (bid !== null && ask !== null && bid > 0 && ask > 0 ? (bid + ask) / 2 : null) ??
      data.last_trade_price ??
      null;

    const symbol = `${request.ticker.toUpperCase()}${request.expiry.replace(/-/g, "")}${request.optionType === "call" ? "C" : "P"}${Math.round(request.strike * 1000)}`;

    return {
      symbol,
      underlyingTicker: request.ticker.toUpperCase(),
      underlyingPrice,
      bid,
      ask,
      mid,
      last: data.last_trade_price ?? null,
      impliedVolatility: data.implied_volatility ?? null,
      delta: data.delta ?? null,
      gamma: data.gamma ?? null,
      theta: data.theta ?? null,
      vega: data.vega ?? null,
      volume: data.volume ?? null,
      openInterest: data.open_interest ?? null,
      timestamp: data.timestamp ?? new Date().toISOString(),
      dataMode,
      source,
    };
  }

  async fetchStockQuote(symbol: string, userId?: string): Promise<StockQuote> {
    const params = new URLSearchParams({ ticker: symbol.toUpperCase() });
    if (userId) params.set("user_id", userId);
    const response = await fetch(
      `${API_BASE}/api/dashboard/stock-price?${params.toString()}`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      throw new Error(`Backend stock-price returned ${response.status}`);
    }

    const data = (await response.json()) as BackendStockPriceResponse;

    return {
      symbol: data.ticker ?? symbol.toUpperCase(),
      price: data.price!,
      bid: data.bid ?? null,
      ask: data.ask ?? null,
      previousClose: data.previousClose ?? null,
      change: data.change ?? null,
      changePercent: data.changePercent ?? null,
      timestamp: data.timestamp ?? new Date().toISOString(),
      provider: data.source ?? "yfinance",
      dataMode: (data.dataMode as StockQuote["dataMode"]) ?? "DELAYED",
    };
  }
}
