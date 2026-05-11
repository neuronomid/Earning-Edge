"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { type OptionQuote } from "@/types/option";
import {
  type SimulationAccount,
  type SimulationPosition,
} from "@/types/simulation";
import {
  type LiveMarketDataStatus,
  type LiveMarketUpdate,
} from "@/types/liveMarketData";

const API_BASE =
  (
    process.env.NEXT_PUBLIC_EARNING_EDGE_API_BASE_URL ??
    "http://127.0.0.1:8000"
  ).replace(/\/$/, "");

function websocketUrl() {
  return `${API_BASE.replace(/^http/, "ws")}/api/dashboard/live-market-data`;
}

export function useLiveMarketData({
  account,
  enabled = true,
  onAccountUpdated,
  onStatus,
}: {
  account: SimulationAccount;
  enabled?: boolean;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus?: (message: string) => void;
}) {
  const [status, setStatus] = useState<LiveMarketDataStatus>("DISCONNECTED");
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const [fallbackReason, setFallbackReason] = useState<string | null>(null);
  const [updates, setUpdates] = useState<Record<string, LiveMarketUpdate>>({});
  const socketRef = useRef<WebSocket | null>(null);
  const accountRef = useRef(account);
  const triggeredRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    accountRef.current = account;
  }, [account]);

  const positionsKey = useMemo(
    () =>
      account.openPositions
        .map((position) =>
          [
            position.id,
            position.contractId,
            position.quantity,
            position.averageEntryPrice,
            position.stopLoss ?? "",
            position.takeProfit ?? "",
          ].join(":"),
        )
        .join("|"),
    [account.openPositions],
  );

  const sendSubscription = useCallback((socket: WebSocket) => {
    const positions = accountRef.current.openPositions;
    if (positions.length === 0 || socket.readyState !== WebSocket.OPEN) return;
    socket.send(
      JSON.stringify({
        type: "subscribe",
        dashboardUserId: accountRef.current.id,
        stockFeed: "iex",
        optionFeed: "indicative",
        symbols: Array.from(new Set(positions.map((position) => position.symbol))),
        optionContracts: positions.map((position) => position.contractId),
        positionIds: positions.map((position) => position.id),
        positions: positions.map((position) => ({
          positionId: position.id,
          contractId: position.contractId,
          optionSymbol: position.contractId,
          underlyingSymbol: position.symbol,
          optionType: position.optionType,
          positionSide: position.positionSide,
          quantity: position.quantity,
          entryOptionPrice: position.averageEntryPrice,
          entryUnderlyingPrice: position.entryUnderlyingPrice,
          strike: position.strike,
          expiration: position.expiration,
          stopLoss: position.stopLoss,
          takeProfit: position.takeProfit,
          currentBid: position.currentBid,
          currentAsk: position.currentAsk,
          currentMid: position.currentMid,
          currentMarkPrice: position.currentMarkPrice,
          lastPrice: position.contract.lastPrice,
        })),
      }),
    );
  }, []);

  const closeTriggeredPosition = useCallback(
    async (update: LiveMarketUpdate) => {
      if (!update.triggerReason || triggeredRef.current.has(update.positionId)) return;
      triggeredRef.current.add(update.positionId);
      const account = accountRef.current;
      const position = account.openPositions.find((item) => item.id === update.positionId);
      if (!position) return;

      const quote: Partial<OptionQuote> = {
        ...position.contract,
        bid: update.optionBid,
        ask: update.optionAsk,
        mid: update.optionMid ?? update.estimatedOptionPrice,
        lastPrice: update.optionLast,
        underlyingPrice: update.underlyingPrice,
        source: update.optionSource,
        timestamp: update.lastUpdated,
      };

      try {
        const response = await fetch(
          `/api/simulation/positions/${encodeURIComponent(update.positionId)}/close`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              reason: update.triggerReason,
              quote,
            }),
          },
        );
        if (!response.ok) {
          const body = (await response.json().catch(() => ({}))) as { detail?: string };
          throw new Error(body.detail ?? `HTTP ${response.status}`);
        }
        const next = (await response.json()) as SimulationAccount;
        onAccountUpdated(next);
        onStatus?.(
          `${position.symbol} ${update.triggerReason === "STOP_LOSS" ? "stop loss" : "take profit"} triggered.`,
        );
      } catch (error) {
        triggeredRef.current.delete(update.positionId);
        onStatus?.(error instanceof Error ? error.message : "Failed to close triggered position.");
      }
    },
    [onAccountUpdated, onStatus],
  );

  const applyUpdate = useCallback(
    (update: LiveMarketUpdate) => {
      setUpdates((current) => ({ ...current, [update.positionId]: update }));
      setLastUpdated(new Date().toLocaleTimeString());
      setFallbackReason(update.fallbackReason ?? null);
      setStatus(update.dataMode === "STREAMING" ? "STREAMING" : "FALLBACK_REST");

      const current = accountRef.current;
      const openPositions = current.openPositions.map((position) =>
        position.id === update.positionId ? applyMarketUpdateToPosition(position, update) : position,
      );
      const next = finalizeLiveAccount({ ...current, openPositions });
      onAccountUpdated(next);

      if (update.triggerReason) {
        void closeTriggeredPosition(update);
      }
    },
    [closeTriggeredPosition, onAccountUpdated],
  );

  useEffect(() => {
    if (!enabled || account.openPositions.length === 0) {
      socketRef.current?.close();
      socketRef.current = null;
      setStatus("DISCONNECTED");
      return;
    }

    let closed = false;
    const socket = new WebSocket(websocketUrl());
    socketRef.current = socket;
    setStatus("CONNECTING");

    socket.onopen = () => {
      sendSubscription(socket);
    };
    socket.onmessage = (message) => {
      const payload = JSON.parse(message.data as string) as
        | LiveMarketUpdate
        | { type: string; message?: string };
      if (isMarketUpdate(payload)) {
        applyUpdate(payload);
      } else if (payload.type === "error") {
        setStatus("ERROR");
        onStatus?.(payload.message ?? "Live market-data stream error.");
      }
    };
    socket.onerror = () => {
      setStatus("ERROR");
      onStatus?.("Live market-data stream error. REST fallback remains available.");
    };
    socket.onclose = () => {
      if (!closed) setStatus("DISCONNECTED");
    };

    return () => {
      closed = true;
      socket.close();
    };
  }, [applyUpdate, enabled, onStatus, positionsKey, sendSubscription, account.openPositions.length]);

  return { status, lastUpdated, fallbackReason, updates };
}

function applyMarketUpdateToPosition(
  position: SimulationPosition,
  update: LiveMarketUpdate,
): SimulationPosition {
  const mark = update.estimatedOptionPrice ?? position.currentMarkPrice;
  const marketValue = roundMoney(mark * position.quantity * 100);
  return {
    ...position,
    contract: {
      ...position.contract,
      bid: update.optionBid ?? position.contract.bid,
      ask: update.optionAsk ?? position.contract.ask,
      mid: update.optionMid ?? update.estimatedOptionPrice ?? position.contract.mid,
      lastPrice: update.optionLast ?? position.contract.lastPrice,
      underlyingPrice: update.underlyingPrice ?? position.contract.underlyingPrice,
      source: update.optionSource ?? position.contract.source,
    },
    currentBid: update.optionBid ?? position.currentBid,
    currentAsk: update.optionAsk ?? position.currentAsk,
    currentMid: update.optionMid ?? update.estimatedOptionPrice ?? position.currentMid,
    currentMarkPrice: roundPremium(mark),
    currentMarketValue: marketValue,
    unrealizedPnl: update.unrealizedPnl ?? position.unrealizedPnl,
    unrealizedPnlPercent: update.unrealizedPnlPercent ?? position.unrealizedPnlPercent,
    lastQuoteAt: update.lastUpdated,
    currentUnderlyingPrice: update.underlyingPrice ?? position.currentUnderlyingPrice ?? null,
    underlyingBid: update.underlyingBid,
    underlyingAsk: update.underlyingAsk,
    stockSource: update.stockSource,
    optionSource: update.optionSource,
    dataMode: update.dataMode,
    fallbackReason: update.fallbackReason ?? null,
    liveStatus:
      update.positionStatus === "STOP_LOSS_TRIGGERED" ||
      update.positionStatus === "TAKE_PROFIT_TRIGGERED"
        ? update.positionStatus
        : update.dataMode,
  };
}

function finalizeLiveAccount(account: SimulationAccount): SimulationAccount {
  const unrealizedPnl = roundMoney(
    account.openPositions.reduce((sum, position) => sum + position.unrealizedPnl, 0),
  );
  const longValue = account.openPositions
    .filter((position) => position.positionSide === "LONG")
    .reduce((sum, position) => sum + position.currentMarketValue, 0);
  const shortLiability = account.openPositions
    .filter((position) => position.positionSide === "SHORT")
    .reduce((sum, position) => sum + position.currentMarketValue, 0);

  return {
    ...account,
    unrealizedPnl,
    totalPortfolioValue: roundMoney(account.cashBalance + longValue - shortLiability),
    updatedAt: new Date().toISOString(),
  };
}

function roundMoney(value: number) {
  return Number(value.toFixed(2));
}

function roundPremium(value: number) {
  return Number(value.toFixed(4));
}

function isMarketUpdate(
  payload: LiveMarketUpdate | { type: string; message?: string },
): payload is LiveMarketUpdate {
  return payload.type === "market_update" && "positionId" in payload;
}
