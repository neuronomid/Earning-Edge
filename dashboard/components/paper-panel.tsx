"use client";

import { useMemo, useState } from "react";
import { AccountSummaryCard } from "@/components/options/AccountSummaryCard";
import { LiveQuoteCard } from "@/components/options/LiveQuoteCard";
import { RiskRewardCard } from "@/components/options/RiskRewardCard";
import { EquityChart, OptionPriceChart, PnLBarChart } from "@/components/options/PositionPnLChart";
import { OpenPositionsTable } from "@/components/OpenPositionsTable";
import { OrderHistoryTable } from "@/components/OrderHistoryTable";
import { useLiveOptionQuote } from "@/hooks/useLiveOptionQuote";
import { useLiveMarketData } from "@/hooks/useLiveMarketData";
import { useSimulationStore } from "@/stores/useSimulationStore";
import { LiveMarketDataTest } from "@/components/LiveMarketDataTest";
import { formatCurrency, formatDate, formatDateTime } from "@/lib/formatters";
import { type DashboardRecommendation } from "@/lib/dashboard-data";
import type { OptionQuoteRequest } from "@/lib/marketData/MarketDataProvider";
import { type SimulationAccount, type SimulationPosition } from "@/types/simulation";
import type { OptionSide, OptionType } from "@/utils/options/calculateOptionPnL";

export function PaperPanel({
  account,
  selectedRecommendation,
  onAccountUpdated,
  onStatus,
}: {
  account: SimulationAccount;
  selectedRecommendation?: DashboardRecommendation | null;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
}) {
  const { equityHistory, optionPriceHistory } = useSimulationStore();
  const [chartTab, setChartTab] = useState<"equity" | "pnl" | "option">("equity");

  const focusedPosition: SimulationPosition | null =
    account.openPositions[0] ?? null;

  const liveRequest: OptionQuoteRequest | null = useMemo(() => {
    if (selectedRecommendation) {
      return {
        ticker: selectedRecommendation.ticker,
        strike: selectedRecommendation.strike,
        expiry: selectedRecommendation.expiry,
        optionType: selectedRecommendation.optionType.toLowerCase() as "call" | "put",
        userId: account.id,
      };
    }
    if (focusedPosition) {
      return {
        ticker: focusedPosition.symbol,
        strike: focusedPosition.strike,
        expiry: focusedPosition.expiration,
        optionType: focusedPosition.optionType.toLowerCase() as "call" | "put",
        userId: account.id,
      };
    }
    return null;
  }, [account.id, selectedRecommendation, focusedPosition]);

  const { quote, error: quoteError, isPolling, lastUpdated } = useLiveOptionQuote(liveRequest, 5000);
  const liveMarket = useLiveMarketData({
    account,
    enabled: account.openPositions.length > 0,
    onAccountUpdated,
    onStatus,
  });

  const focusedOptionHistory =
    focusedPosition ? (optionPriceHistory[focusedPosition.id] ?? []) : [];

  const recSide = selectedRecommendation?.positionSide?.toUpperCase() as OptionSide | undefined;
  const recType = selectedRecommendation?.optionType?.toUpperCase() as OptionType | undefined;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-end justify-between gap-2">
        <div>
          <h2 className="text-base font-semibold text-white">Option Trading Simulator</h2>
          <p className="mt-1 text-sm text-[#8b949e]">
            Paper-only simulation. Bid/ask fills, automatic stop loss and take profit. No real orders sent.
          </p>
        </div>
        <span className="rounded border border-[#f0883e]/30 bg-[#f0883e]/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#f0b72f]">
          Simulation only
        </span>
      </div>
      {account.openPositions.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[#8b949e]">
          <span
            className={`rounded border px-2 py-0.5 font-semibold uppercase tracking-wide ${
              liveMarket.status === "STREAMING"
                ? "border-[#238636]/30 bg-[#238636]/10 text-[#3fb950]"
                : liveMarket.status === "FALLBACK_REST"
                  ? "border-[#d29922]/30 bg-[#d29922]/10 text-[#e3b341]"
                  : liveMarket.status === "ERROR"
                    ? "border-[#f85149]/30 bg-[#f85149]/10 text-[#f85149]"
                    : "border-white/[0.08] bg-white/[0.03] text-[#8b949e]"
            }`}
          >
            {liveMarket.status}
          </span>
          <span>Stock: alpaca_iex_stream</span>
          <span>Option: alpaca_option_stream or fallback_rest</span>
          {liveMarket.lastUpdated && <span>Updated {liveMarket.lastUpdated}</span>}
          {liveMarket.fallbackReason && (
            <span className="text-[#e3b341]">{liveMarket.fallbackReason}</span>
          )}
        </div>
      )}

      {/* 1. Live market data test */}
      <LiveMarketDataTest />

      {/* 2. Account summary */}
      <AccountSummaryCard account={account} />

      {/* 3. Live option quote */}
      {liveRequest && (
        <LiveQuoteCard
          quote={quote}
          ticker={liveRequest.ticker}
          isLoading={isPolling}
          error={quoteError}
          lastUpdated={lastUpdated}
        />
      )}

      {/* 4. Risk/reward — only if recommendation selected */}
      {selectedRecommendation && recSide && recType && (
        <RiskRewardCard
          optionType={recType}
          side={recSide}
          strike={selectedRecommendation.strike}
          premium={
            quote?.mid ??
            selectedRecommendation.midPrice ??
            selectedRecommendation.suggestedEntry
          }
          quantity={Math.max(1, selectedRecommendation.suggestedQuantity || 1)}
          currentOptionPrice={quote?.mid ?? undefined}
        />
      )}

      {/* 5. Open positions */}
      <OpenPositionsTable
        account={account}
        onAccountUpdated={onAccountUpdated}
        onStatus={onStatus}
      />

      {/* 6. Charts */}
      {equityHistory.length >= 2 && (
        <div className="rounded-xl border border-white/[0.06] bg-[#0d1624] p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-widest text-[#58a6ff]">
              Performance Charts
            </span>
            <div className="flex gap-1">
              {(["equity", "pnl", "option"] as const).map((tab) => (
                <button
                  key={tab}
                  onClick={() => setChartTab(tab)}
                  className={`rounded px-2 py-0.5 text-[10px] font-medium transition ${
                    chartTab === tab
                      ? "bg-[#2f81f7] text-white"
                      : "text-[#8b949e] hover:text-white"
                  }`}
                >
                  {tab === "equity" ? "Equity" : tab === "pnl" ? "P&L" : "Option"}
                </button>
              ))}
            </div>
          </div>
          {chartTab === "equity" && <EquityChart snapshots={equityHistory} />}
          {chartTab === "pnl" && <PnLBarChart snapshots={equityHistory} />}
          {chartTab === "option" && (
            <OptionPriceChart
              snapshots={focusedOptionHistory}
              ticker={focusedPosition?.symbol ?? selectedRecommendation?.ticker ?? ""}
            />
          )}
        </div>
      )}

      {/* 7. Closed positions */}
      <ClosedPositions account={account} />

      {/* 8. Order history */}
      <OrderHistoryTable
        account={account}
        onAccountUpdated={onAccountUpdated}
        onStatus={onStatus}
      />
    </div>
  );
}

function ClosedPositions({ account }: { account: SimulationAccount }) {
  if (account.closedPositions.length === 0) return null;

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-[#121821]">
      <div className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
        Trade History
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-[#0b111a] text-[10px] uppercase tracking-[0.18em] text-[#8b949e]">
            <tr>
              <th className="px-4 py-3">Contract</th>
              <th className="px-4 py-3">Strategy</th>
              <th className="px-4 py-3">Qty</th>
              <th className="px-4 py-3">Entry Premium</th>
              <th className="px-4 py-3">Close Premium</th>
              <th className="px-4 py-3">Realized P&L</th>
              <th className="px-4 py-3">Close Reason</th>
              <th className="px-4 py-3">Closed</th>
            </tr>
          </thead>
          <tbody>
            {account.closedPositions.map((position) => (
              <ClosedPositionRow key={position.id} position={position} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function closeReasonLabel(reason: SimulationPosition["closeReason"]) {
  switch (reason) {
    case "STOP_LOSS": return { label: "Stop Loss", color: "bg-[#f85149]/10 text-[#ffb3ad]" };
    case "TAKE_PROFIT": return { label: "Take Profit", color: "bg-[#238636]/10 text-[#3fb950]" };
    case "EXPIRED": return { label: "Expired", color: "bg-[#d29922]/10 text-[#f0b72f]" };
    default: return { label: "Manual", color: "bg-[#30363d] text-[#8b949e]" };
  }
}

function strategyDisplayLabel(position: SimulationPosition) {
  if (position.strategy) {
    switch (position.strategy) {
      case "BUY_CALL": return "Long Call";
      case "BUY_PUT": return "Long Put";
      case "SHORT_CALL": return "Short Call";
      case "SHORT_PUT": return "Short Put";
    }
  }
  return `${position.positionSide === "LONG" ? "Long" : "Short"} ${position.optionType}`;
}

function ClosedPositionRow({ position }: { position: SimulationPosition }) {
  const pnlColor = position.realizedPnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]";
  const pnlSign = position.realizedPnl >= 0 ? "+" : "";
  const closeReason = closeReasonLabel(position.closeReason);

  return (
    <tr className="border-t border-white/[0.04] text-[#c9d1d9]">
      <td className="px-4 py-3">
        <div className="font-semibold text-white">
          {position.symbol} {position.optionType} {formatCurrency(position.strike)}
        </div>
        <div className="text-[11px] text-[#8b949e]">exp {formatDate(position.expiration)}</div>
      </td>
      <td className="px-4 py-3">
        <span
          className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
            position.positionSide === "LONG"
              ? "bg-[#238636]/10 text-[#3fb950]"
              : "bg-[#f85149]/10 text-[#f85149]"
          }`}
        >
          {strategyDisplayLabel(position)}
        </span>
      </td>
      <td className="px-4 py-3">{position.quantity}</td>
      <td className="px-4 py-3 tabular-nums">{formatCurrency(position.averageEntryPrice)}</td>
      <td className="px-4 py-3 tabular-nums">
        {position.closedPrice == null ? "—" : formatCurrency(position.closedPrice)}
      </td>
      <td className={`px-4 py-3 font-semibold tabular-nums ${pnlColor}`}>
        {pnlSign}{formatCurrency(position.realizedPnl)}
      </td>
      <td className="px-4 py-3">
        <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${closeReason.color}`}>
          {closeReason.label}
        </span>
      </td>
      <td className="px-4 py-3 text-[11px] text-[#8b949e]">
        {position.closedAt ? formatDateTime(position.closedAt) : "—"}
      </td>
    </tr>
  );
}
