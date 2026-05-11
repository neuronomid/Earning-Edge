import { type MarketDataProvider, type OptionQuoteRequest, type OptionQuoteResult, type StockQuote } from "./MarketDataProvider";

function seedRandom(seed: number) {
  let s = seed;
  return function () {
    s = (s * 16807 + 0) % 2147483647;
    return (s - 1) / 2147483646;
  };
}

function mockMid(strike: number, expiry: string, optionType: "call" | "put"): number {
  const days = Math.max(1, (new Date(expiry).getTime() - Date.now()) / 86400000);
  const rng = seedRandom(Math.round(strike * 100 + days));
  const base = strike * 0.01 * Math.sqrt(days / 30);
  return Math.max(0.01, parseFloat((base * (0.8 + rng() * 0.4)).toFixed(2)));
}

function mockUnderlyingPrice(ticker: string, strike: number): number {
  const rng = seedRandom(ticker.split("").reduce((a, c) => a + c.charCodeAt(0), 0));
  return parseFloat((strike * (0.9 + rng() * 0.2)).toFixed(2));
}

// Base prices for well-known tickers so mock prices are realistic
const BASE_PRICES: Record<string, number> = {
  GOOGL: 175, GOOG: 175, AAPL: 195, MSFT: 415, AMZN: 185,
  AMD: 115, NVDA: 870, TSLA: 175, SPY: 525, QQQ: 445,
  META: 510, NFLX: 640, CRM: 290, UBER: 72, COIN: 220,
};

export class MockProvider implements MarketDataProvider {
  readonly name = "mock";

  isAvailable() {
    return true;
  }

  async fetchOptionQuote(request: OptionQuoteRequest): Promise<OptionQuoteResult> {
    const mid = mockMid(request.strike, request.expiry, request.optionType);
    const spread = parseFloat((mid * 0.05).toFixed(4));
    const bid = parseFloat((mid - spread).toFixed(4));
    const ask = parseFloat((mid + spread).toFixed(4));
    const underlying = mockUnderlyingPrice(request.ticker, request.strike);

    return {
      symbol: `${request.ticker}${request.expiry.replace(/-/g, "")}${request.optionType === "call" ? "C" : "P"}${Math.round(request.strike * 1000)}`,
      underlyingTicker: request.ticker,
      underlyingPrice: underlying,
      bid,
      ask,
      mid,
      last: mid,
      impliedVolatility: 0.35 + (Math.random() * 0.2 - 0.1),
      delta: request.optionType === "call" ? 0.4 + Math.random() * 0.2 : -(0.4 + Math.random() * 0.2),
      gamma: 0.02 + Math.random() * 0.01,
      theta: -(0.01 + Math.random() * 0.005),
      vega: 0.05 + Math.random() * 0.03,
      volume: Math.floor(100 + Math.random() * 500),
      openInterest: Math.floor(500 + Math.random() * 2000),
      timestamp: new Date().toISOString(),
      dataMode: "MOCK",
      source: "mock",
    };
  }

  async fetchStockQuote(symbol: string): Promise<StockQuote> {
    const sym = symbol.toUpperCase();
    const basePrice = BASE_PRICES[sym] ?? 100;

    // Price changes every 5-second bucket using time-seeded random so it varies over time
    const bucket = Math.floor(Date.now() / 5000);
    const symbolSeed = sym.split("").reduce((a, c) => a + c.charCodeAt(0), 0);

    const rngCurrent = seedRandom(symbolSeed + bucket);
    const rngPrev = seedRandom(symbolSeed + bucket - 1);

    // Small random walk: ±0.3% per tick
    const currentMultiplier = 1 + (rngCurrent() - 0.5) * 0.006;
    const prevMultiplier = 1 + (rngPrev() - 0.5) * 0.006;

    const price = parseFloat((basePrice * currentMultiplier).toFixed(2));
    const previousClose = parseFloat((basePrice * prevMultiplier).toFixed(2));
    const change = parseFloat((price - previousClose).toFixed(2));
    const changePercent = parseFloat(((change / previousClose) * 100).toFixed(4));

    return {
      symbol: sym,
      price,
      previousClose,
      change,
      changePercent,
      timestamp: new Date().toISOString(),
      provider: "mock",
      dataMode: "MOCK",
    };
  }
}
