export type OptionType = "CALL" | "PUT";

export type OptionContract = {
  contractId: string;
  symbol: string;
  optionType: OptionType;
  strike: number;
  expiration: string;
  bid: number | null;
  ask: number | null;
  mid: number | null;
  lastPrice: number | null;
  source: string;
  underlyingPrice?: number | null;
  recommendationId?: string | null;
};

export type OptionQuote = OptionContract & {
  timestamp: string;
};
