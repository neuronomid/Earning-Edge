import { type DataMode } from "@/lib/marketData/MarketDataProvider";

export type LiveMarketDataStatus =
  | "CONNECTING"
  | "STREAMING"
  | "FALLBACK_REST"
  | "DISCONNECTED"
  | "ERROR";

export type LiveMarketUpdate = {
  type: "market_update";
  positionId: string;
  contractId?: string;
  underlyingSymbol: string;
  underlyingPrice: number | null;
  underlyingBid: number | null;
  underlyingAsk: number | null;
  optionSymbol: string;
  optionBid: number | null;
  optionAsk: number | null;
  optionMid: number | null;
  optionLast: number | null;
  estimatedOptionPrice: number | null;
  unrealizedPnl: number | null;
  unrealizedPnlPercent: number | null;
  dataMode: Extract<DataMode, "STREAMING" | "FALLBACK_REST">;
  stockSource: string;
  optionSource: string;
  lastUpdated: string;
  fallbackReason?: string | null;
  positionStatus?: "OPEN" | "STOP_LOSS_TRIGGERED" | "TAKE_PROFIT_TRIGGERED";
  triggerReason?: "STOP_LOSS" | "TAKE_PROFIT" | null;
};
