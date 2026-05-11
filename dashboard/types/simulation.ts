import { type OptionContract, type OptionQuote, type OptionType } from "@/types/option";

export type OrderSide = "BUY" | "SELL";
export type OrderType = "MARKET" | "LIMIT";
export type OrderStatus =
  | "PENDING"
  | "FILLED"
  | "PARTIALLY_FILLED"
  | "CANCELLED"
  | "REJECTED"
  | "EXPIRED";
export type PositionStatus = "OPEN" | "CLOSED" | "EXPIRED";
export type LivePositionStatus =
  | "OPEN"
  | "STREAMING"
  | "FALLBACK_REST"
  | "STOP_LOSS_TRIGGERED"
  | "TAKE_PROFIT_TRIGGERED";
export type PositionSide = "LONG" | "SHORT";
export type OptionStrategy = "BUY_CALL" | "BUY_PUT" | "SHORT_CALL" | "SHORT_PUT";
export type CloseReason = "MANUAL" | "STOP_LOSS" | "TAKE_PROFIT" | "EXPIRED";

export type SimulationOrder = {
  id: string;
  accountId: string;
  symbol: string;
  contractId: string;
  contract: OptionContract;
  optionType: OptionType;
  side: OrderSide;
  orderType: OrderType;
  quantity: number;
  limitPrice: number | null;
  fillPrice: number | null;
  status: OrderStatus;
  createdAt: string;
  filledAt: string | null;
  stopLoss: number | null;
  takeProfit: number | null;
  rejectionReason?: string | null;
  triggerReason?: "STOP_LOSS" | "TAKE_PROFIT" | null;
  strategy?: OptionStrategy | null;
};

export type SimulationPosition = {
  id: string;
  accountId: string;
  symbol: string;
  contractId: string;
  contract: OptionContract;
  optionType: OptionType;
  positionSide: PositionSide;
  strike: number;
  expiration: string;
  quantity: number;
  averageEntryPrice: number;
  entryUnderlyingPrice: number | null;
  currentBid: number | null;
  currentAsk: number | null;
  currentMid: number | null;
  currentMarkPrice: number;
  currentMarketValue: number;
  costBasis: number;
  unrealizedPnl: number;
  unrealizedPnlPercent: number;
  realizedPnl: number;
  stopLoss: number | null;
  takeProfit: number | null;
  status: PositionStatus;
  strategy: OptionStrategy | null;
  closeReason: CloseReason | null;
  openedAt: string;
  closedAt: string | null;
  closedPrice: number | null;
  lastQuoteAt: string | null;
  currentUnderlyingPrice?: number | null;
  underlyingBid?: number | null;
  underlyingAsk?: number | null;
  stockSource?: string | null;
  optionSource?: string | null;
  dataMode?: "STREAMING" | "FALLBACK_REST" | string | null;
  fallbackReason?: string | null;
  liveStatus?: LivePositionStatus | null;
};

export type SimulationNotification = {
  id: string;
  type: "INFO" | "WARNING" | "SUCCESS";
  message: string;
  createdAt: string;
};

export type SimulationAccount = {
  id: string;
  startingCash: number;
  cashBalance: number;
  openPositions: SimulationPosition[];
  closedPositions: SimulationPosition[];
  orders: SimulationOrder[];
  realizedPnl: number;
  unrealizedPnl: number;
  totalPortfolioValue: number;
  buyingPower: number;
  notifications: SimulationNotification[];
  updatedAt: string;
};

export type PlaceOrderPayload = {
  accountId: string;
  startingCash?: number;
  symbol: string;
  contract: OptionContract;
  side: OrderSide;
  orderType: OrderType;
  quantity: number;
  limitPrice?: number | null;
  stopLoss?: number | null;
  takeProfit?: number | null;
  strategy?: OptionStrategy | null;
};

export type PlaceOrderResponse = {
  account: SimulationAccount;
  order: SimulationOrder;
};

export type RiskUpdatePayload = {
  stopLoss?: number | null;
  takeProfit?: number | null;
};

export type QuoteMap = Record<string, OptionQuote>;
