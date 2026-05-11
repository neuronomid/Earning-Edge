"use client";

import { formatCurrency, formatDate } from "@/lib/formatters";
import { placeSimulationOrder } from "@/lib/api";
import { StopLossTakeProfitControls } from "@/components/StopLossTakeProfitControls";
import {
  type OptionStrategy,
  type SimulationAccount,
  type SimulationPosition,
} from "@/types/simulation";

function strategyLabel(
  strategy: OptionStrategy | null | undefined,
  positionSide: string,
  optionType: string,
): string {
  if (strategy) {
    switch (strategy) {
      case "BUY_CALL":
        return "Long Call";
      case "BUY_PUT":
        return "Long Put";
      case "SHORT_CALL":
        return "Short Call";
      case "SHORT_PUT":
        return "Short Put";
    }
  }
  return `${positionSide === "LONG" ? "Long" : "Short"} ${optionType}`;
}

function sourceLabel(position: SimulationPosition): { text: string; color: string } {
  if (position.dataMode === "STREAMING") {
    return { text: "STREAMING", color: "text-[#3fb950]" };
  }
  if (position.dataMode === "FALLBACK_REST") {
    return { text: "FALLBACK REST", color: "text-[#e3b341]" };
  }
  if (position.optionSource) {
    return { text: position.optionSource.toUpperCase(), color: "text-[#58a6ff]" };
  }
  return { text: "LAST QUOTE", color: "text-[#8b949e]" };
}

export function OpenPositionsTable({
  account,
  onAccountUpdated,
  onStatus,
}: {
  account: SimulationAccount;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
}) {
  const hasShortPositions = account.openPositions.some(
    (position) => position.positionSide === "SHORT",
  );

  if (account.openPositions.length === 0) {
    return (
      <EmptyState message="No open simulated option positions yet. Select a recommendation and use the strategy selector to simulate opening a position." />
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-[#121821]">
      <div className="flex items-center justify-between border-b border-white/[0.06] px-4 py-3">
        <span className="text-sm font-semibold text-white">Open Option Positions</span>
        <span className="text-[10px] text-[#8b949e]">
          {account.openPositions.length}{" "}
          {account.openPositions.length === 1 ? "position" : "positions"}
        </span>
      </div>

      {hasShortPositions && (
        <div className="border-b border-[#f85149]/20 bg-[#f85149]/5 px-4 py-2 text-[11px] text-[#ffb3ad]">
          Short options involve high or unlimited risk. Buying power is reserved as a margin
          approximation. This is a simulation only; no real orders are sent.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-[#0b111a] text-[10px] uppercase tracking-[0.18em] text-[#8b949e]">
            <tr>
              <th className="px-4 py-3">Contract</th>
              <th className="px-4 py-3">Strategy</th>
              <th className="px-4 py-3">Contracts</th>
              <th className="px-4 py-3">Entry Premium</th>
              <th className="px-4 py-3">Live Premium</th>
              <th className="px-4 py-3">Underlying</th>
              <th className="px-4 py-3">Market Value</th>
              <th className="px-4 py-3">Unrealized P&amp;L</th>
              <th className="px-4 py-3">Stop / Target</th>
              <th className="px-4 py-3 text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {account.openPositions.map((position) => (
              <PositionRow
                key={position.id}
                position={position}
                account={account}
                onAccountUpdated={onAccountUpdated}
                onStatus={onStatus}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function PositionRow({
  position,
  account,
  onAccountUpdated,
  onStatus,
}: {
  position: SimulationPosition;
  account: SimulationAccount;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
}) {
  const isLong = position.positionSide === "LONG";
  const label = strategyLabel(position.strategy, position.positionSide, position.optionType);
  const src = sourceLabel(position);

  const displayPnl = position.unrealizedPnl;
  const displayPnlPct = position.unrealizedPnlPercent;
  const displayValue = position.currentMarketValue;
  const estimatedOptionPrice = position.currentMarkPrice > 0 ? position.currentMarkPrice : null;
  const liveUnderlyingPrice =
    position.currentUnderlyingPrice ??
    position.contract.underlyingPrice ??
    position.entryUnderlyingPrice;
  const underlyingChange =
    liveUnderlyingPrice !== null && position.entryUnderlyingPrice !== null
      ? liveUnderlyingPrice - position.entryUnderlyingPrice
      : null;
  const underlyingChangePercent =
    underlyingChange !== null &&
    position.entryUnderlyingPrice !== null &&
    position.entryUnderlyingPrice !== 0
      ? (underlyingChange / position.entryUnderlyingPrice) * 100
      : null;

  const pnlSign = displayPnl >= 0 ? "+" : "";
  const pnlColor = displayPnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]";
  const underlyingChangeSign = (underlyingChange ?? 0) >= 0 ? "+" : "";
  const underlyingColor = (underlyingChange ?? 0) >= 0 ? "text-[#3fb950]" : "text-[#f85149]";
  const stopLossTriggered = position.liveStatus === "STOP_LOSS_TRIGGERED";
  const takeProfitTriggered = position.liveStatus === "TAKE_PROFIT_TRIGGERED";
  const rowHighlight = stopLossTriggered
    ? "bg-[#f85149]/5"
    : takeProfitTriggered
      ? "bg-[#238636]/5"
      : "";

  async function closePosition() {
    try {
      const response = await placeSimulationOrder({
        accountId: account.id,
        startingCash: account.startingCash,
        symbol: position.symbol,
        contract: position.contract,
        side: isLong ? "SELL" : "BUY",
        orderType: "MARKET",
        quantity: position.quantity,
        limitPrice: null,
        stopLoss: null,
        takeProfit: null,
      });
      onAccountUpdated(response.account);
      onStatus(
        `Closed ${position.symbol} ${position.optionType} at ${formatCurrency(response.order.fillPrice ?? position.currentMarkPrice)}.`,
      );
    } catch (error) {
      onStatus(error instanceof Error ? error.message : "Failed to close position.");
    }
  }

  return (
    <tr className={`border-t border-white/[0.04] text-[#c9d1d9] ${rowHighlight}`}>
      <td className="px-4 py-3">
        <div className="font-semibold text-white">
          {position.symbol} {position.optionType} {formatCurrency(position.strike)}
        </div>
        <div className="text-[11px] text-[#8b949e]">exp {formatDate(position.expiration)}</div>
        <div className="text-[11px] text-[#484f58]">{position.contractId.slice(0, 18)}...</div>
        {(stopLossTriggered || takeProfitTriggered) && (
          <div
            className={`mt-1 text-[10px] font-bold ${
              stopLossTriggered ? "text-[#f85149]" : "text-[#3fb950]"
            }`}
          >
            {stopLossTriggered ? "STOP LOSS" : "TAKE PROFIT"}
          </div>
        )}
      </td>

      <td className="px-4 py-3">
        <span
          className={`inline-block rounded px-1.5 py-0.5 text-[10px] font-semibold ${
            isLong
              ? "bg-[#238636]/10 text-[#3fb950]"
              : "bg-[#f85149]/10 text-[#f85149]"
          }`}
        >
          {label}
        </span>
        <div className="mt-1 text-[10px] text-[#484f58]">
          {isLong ? "Buy to Open" : "Sell to Open"}
        </div>
      </td>

      <td className="px-4 py-3 tabular-nums">
        <span className="font-semibold text-white">{position.quantity}</span>
        <div className="text-[10px] text-[#8b949e]">x 100 shares</div>
      </td>

      <td className="px-4 py-3 tabular-nums">
        <div className="font-semibold text-white">
          {formatCurrency(position.averageEntryPrice)}
        </div>
        <div className="text-[10px] text-[#8b949e]">per contract</div>
        <div className="text-[10px] text-[#484f58]">
          Cost: {formatCurrency(position.costBasis)}
        </div>
      </td>

      <td className="px-4 py-3 tabular-nums">
        {estimatedOptionPrice !== null ? (
          <>
            <div className="font-semibold text-white">
              {formatCurrency(estimatedOptionPrice)}
            </div>
            <div className={`text-[10px] font-semibold ${src.color}`}>{src.text}</div>
            {position.optionSource && (
              <div className="text-[10px] text-[#484f58]">{position.optionSource}</div>
            )}
            {position.fallbackReason && (
              <div className="max-w-36 truncate text-[10px] text-[#e3b341]">
                {position.fallbackReason}
              </div>
            )}
          </>
        ) : (
          <span className="text-[#484f58]">Unavailable</span>
        )}
      </td>

      <td className="px-4 py-3 tabular-nums">
        {liveUnderlyingPrice !== null ? (
          <>
            <div className="font-semibold text-white">
              {formatCurrency(liveUnderlyingPrice)}
            </div>
            {underlyingChange !== null && (
              <div className={`text-[11px] tabular-nums ${underlyingColor}`}>
                {underlyingChangeSign}
                {formatCurrency(Math.abs(underlyingChange))}
              </div>
            )}
            {underlyingChangePercent !== null && (
              <div className={`text-[10px] ${underlyingColor}`}>
                {underlyingChangeSign}
                {underlyingChangePercent.toFixed(2)}%
              </div>
            )}
            {position.entryUnderlyingPrice !== null && (
              <div className="text-[10px] text-[#484f58]">
                Entry: {formatCurrency(position.entryUnderlyingPrice)}
              </div>
            )}
            {position.stockSource && (
              <div className="text-[10px] text-[#484f58]">{position.stockSource}</div>
            )}
          </>
        ) : (
          <span className="text-[#484f58]">-</span>
        )}
      </td>

      <td className="px-4 py-3 tabular-nums">
        <div className="font-semibold text-white">{formatCurrency(displayValue)}</div>
        <div className="text-[10px] text-[#8b949e]">
          {isLong ? "position value" : "liability"}
        </div>
      </td>

      <td className="px-4 py-3 tabular-nums">
        <div className={`font-semibold ${pnlColor}`}>
          {pnlSign}
          {formatCurrency(displayPnl)}
        </div>
        <div className={`text-[11px] ${pnlColor}`}>
          {pnlSign}
          {displayPnlPct.toFixed(2)}%
        </div>
        {position.dataMode && (
          <div className="text-[10px] text-[#8b949e]">{position.dataMode}</div>
        )}
        {!isLong && <div className="mt-0.5 text-[10px] text-[#f85149]">short</div>}
      </td>

      <td className="px-4 py-3">
        <div
          className={`text-[10px] ${
            stopLossTriggered ? "font-bold text-[#f85149]" : "text-[#8b949e]"
          }`}
        >
          SL: {position.stopLoss !== null ? formatCurrency(position.stopLoss) : "-"}
        </div>
        <div
          className={`text-[10px] ${
            takeProfitTriggered ? "font-bold text-[#3fb950]" : "text-[#8b949e]"
          }`}
        >
          TP: {position.takeProfit !== null ? formatCurrency(position.takeProfit) : "-"}
        </div>
      </td>

      <td className="px-4 py-3">
        <div className="flex flex-col items-end gap-2">
          <StopLossTakeProfitControls
            position={position}
            onAccountUpdated={onAccountUpdated}
          />
          <button
            onClick={() => void closePosition()}
            className="rounded-md bg-[#f85149]/10 px-2.5 py-1.5 text-xs font-semibold text-[#ffb3ad] transition hover:bg-[#f85149]/20"
          >
            {isLong ? "Sell to Close" : "Buy to Close"}
          </button>
        </div>
      </td>
    </tr>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/[0.12] bg-[#121821] px-4 py-8 text-center text-sm text-[#8b949e]">
      {message}
    </div>
  );
}
