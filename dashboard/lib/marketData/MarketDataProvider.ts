export type DataMode =
  | "STREAMING"
  | "FALLBACK_REST"
  | "REAL_TIME"
  | "DELAYED"
  | "ESTIMATED"
  | "POLLING"
  | "MOCK"
  | "ERROR";

export type StockQuote = {
  symbol: string;
  price: number;
  bid?: number | null;
  ask?: number | null;
  previousClose?: number | null;
  change?: number | null;
  changePercent?: number | null;
  timestamp: string;
  provider: string;
  dataMode: DataMode;
};

export type OptionQuoteResult = {
  symbol: string;
  underlyingTicker: string;
  underlyingPrice: number | null;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  last: number | null;
  impliedVolatility: number | null;
  delta: number | null;
  gamma: number | null;
  theta: number | null;
  vega: number | null;
  volume: number | null;
  openInterest: number | null;
  timestamp: string;
  dataMode: DataMode;
  source: string;
};

export type OptionQuoteRequest = {
  ticker: string;
  strike: number;
  expiry: string;
  optionType: "call" | "put";
  userId?: string;
};

export interface MarketDataProvider {
  readonly name: string;
  fetchOptionQuote(request: OptionQuoteRequest): Promise<OptionQuoteResult>;
  fetchStockQuote(symbol: string, userId?: string): Promise<StockQuote>;
  isAvailable(): boolean;
}
