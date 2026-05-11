export type { MarketDataProvider, OptionQuoteRequest, OptionQuoteResult, DataMode } from "./MarketDataProvider";
export { MockProvider } from "./MockProvider";
export { BackendProvider } from "./BackendProvider";

import { BackendProvider } from "./BackendProvider";
import { MockProvider } from "./MockProvider";
import type { MarketDataProvider } from "./MarketDataProvider";

let _provider: MarketDataProvider | null = null;

export function getMarketDataProvider(): MarketDataProvider {
  if (_provider) return _provider;
  const name = process.env.MARKET_DATA_PROVIDER ?? "backend";
  _provider = name === "mock" ? new MockProvider() : new BackendProvider();
  return _provider;
}
