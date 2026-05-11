"use client";

import { useEffect, useRef, useState } from "react";
import { useLiveStockPrice } from "@/hooks/useLiveStockPrice";
import type { LivePriceStatus } from "@/hooks/useLiveStockPrice";
import type { DataMode } from "@/lib/marketData/MarketDataProvider";

const TEST_SYMBOL = "GOOGL";
const TICK_HISTORY_MAX = 10;

interface TickEntry {
  time: string;
  price: number;
  change: number | null;
}

function dataModeLabel(mode: DataMode): { text: string; color: string } {
  switch (mode) {
    case "REAL_TIME": return { text: "REAL_TIME", color: "text-[#3fb950]" };
    case "DELAYED":   return { text: "DELAYED DATA", color: "text-[#e3b341]" };
    case "POLLING":   return { text: "POLLING", color: "text-[#58a6ff]" };
    case "MOCK":      return { text: "MOCK DATA", color: "text-[#f0883e]" };
    case "ESTIMATED": return { text: "ESTIMATED", color: "text-[#d29922]" };
    case "ERROR":     return { text: "ERROR", color: "text-[#f85149]" };
    default:          return { text: String(mode), color: "text-[#8b949e]" };
  }
}

function statusLabel(s: LivePriceStatus): { text: string; dot: string } {
  switch (s) {
    case "CONNECTED":    return { text: "Connected", dot: "bg-[#3fb950]" };
    case "POLLING":      return { text: "Polling…", dot: "bg-[#58a6ff] animate-pulse" };
    case "DISCONNECTED": return { text: "Disconnected", dot: "bg-[#484f58]" };
    case "ERROR":        return { text: "Error", dot: "bg-[#f85149]" };
  }
}

export function LiveMarketDataTest() {
  const [testEnabled, setTestEnabled] = useState(false);
  const [ticks, setTicks] = useState<TickEntry[]>([]);
  const tickCountRef = useRef(0);
  const failCountRef = useRef(0);

  const live = useLiveStockPrice({
    symbol: TEST_SYMBOL,
    intervalMs: 5000,
    enabled: testEnabled,
  });

  // Accumulate tick history whenever price updates
  useEffect(() => {
    if (!testEnabled || live.currentPrice === null || live.status !== "CONNECTED") return;
    tickCountRef.current += 1;
    setTicks((prev) => {
      const entry: TickEntry = {
        time: live.lastUpdated ?? new Date().toLocaleTimeString(),
        price: live.currentPrice!,
        change: live.change,
      };
      return [entry, ...prev].slice(0, TICK_HISTORY_MAX);
    });
  }, [live.currentPrice, live.lastUpdated, testEnabled, live.status, live.change]);

  useEffect(() => {
    if (live.status === "ERROR") failCountRef.current += 1;
  }, [live.status]);

  const dm = dataModeLabel(live.dataMode);
  const sl = statusLabel(live.status);
  const priceUp = live.change !== null && live.change > 0;
  const priceDown = live.change !== null && live.change < 0;
  const priceColor = priceUp ? "text-[#3fb950]" : priceDown ? "text-[#f85149]" : "text-white";
  const changeSign = priceUp ? "+" : "";

  const isDev = process.env.NODE_ENV === "development";

  return (
    <section className="rounded-xl border border-[#2f81f7]/25 bg-[#0b1220] p-5">
      {/* Header */}
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#58a6ff]">
            Live Market Data Test
          </div>
          <h3 className="mt-1 text-lg font-semibold text-white">
            {TEST_SYMBOL}{" "}
            <span className="text-sm font-normal text-[#8b949e]">Google / Alphabet</span>
          </h3>
        </div>
        <div className="flex gap-2">
          {!testEnabled ? (
            <button
              onClick={() => {
                tickCountRef.current = 0;
                failCountRef.current = 0;
                setTicks([]);
                setTestEnabled(true);
              }}
              className="rounded-md bg-[#2f81f7] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#58a6ff]"
            >
              Test Live GOOGL Price
            </button>
          ) : (
            <button
              onClick={() => setTestEnabled(false)}
              className="rounded-md border border-[#f85149]/30 bg-[#f85149]/10 px-4 py-2 text-sm font-semibold text-[#ffb3ad] transition hover:bg-[#f85149]/20"
            >
              Stop Test
            </button>
          )}
        </div>
      </div>

      {/* Data mode + status badges */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className={`rounded px-2 py-0.5 text-[10px] font-bold uppercase tracking-wide ring-1 ring-inset ${
          live.dataMode === "MOCK"
            ? "bg-[#f0883e]/10 text-[#f0883e] ring-[#f0883e]/30"
            : live.dataMode === "DELAYED"
              ? "bg-[#d29922]/10 text-[#e3b341] ring-[#d29922]/30"
              : live.dataMode === "ERROR"
                ? "bg-[#f85149]/10 text-[#f85149] ring-[#f85149]/30"
                : "bg-[#238636]/10 text-[#3fb950] ring-[#238636]/30"
        }`}>
          {dm.text}
        </span>
        <span className="flex items-center gap-1.5 text-[11px] text-[#8b949e]">
          <span className={`h-2 w-2 rounded-full ${sl.dot}`} />
          {sl.text}
        </span>
        {!testEnabled && (
          <span className="text-[10px] text-[#484f58]">Press button to start live tracking</span>
        )}
      </div>

      {/* Price display grid */}
      {testEnabled && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <PriceStat
            label="Current Price"
            value={live.currentPrice !== null ? `$${live.currentPrice.toFixed(2)}` : "—"}
            valueClass={priceColor}
          />
          <PriceStat
            label="Previous Price"
            value={live.previousPrice !== null ? `$${live.previousPrice.toFixed(2)}` : "—"}
          />
          <PriceStat
            label="Price Move"
            value={
              live.change !== null && live.changePercent !== null
                ? `${changeSign}$${live.change.toFixed(4)} / ${changeSign}${live.changePercent.toFixed(4)}%`
                : "—"
            }
            valueClass={priceColor}
          />
          <PriceStat
            label="Last Updated"
            value={live.lastUpdated ?? "Waiting…"}
          />
          <PriceStat
            label="Data Source"
            value={live.provider !== "unknown" ? live.provider : "—"}
          />
          <PriceStat
            label="Mode"
            value={dm.text}
            valueClass={dm.color}
          />
        </div>
      )}

      {/* Error banner */}
      {live.error && (
        <div className="mt-3 rounded-md border border-[#f85149]/25 bg-[#f85149]/10 px-3 py-2 text-xs text-[#ffb3ad]">
          {live.error}
        </div>
      )}

      {/* Tick history */}
      {testEnabled && ticks.length > 0 && (
        <div className="mt-4">
          <div className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8b949e]">
            Recent ticks
          </div>
          <div className="flex flex-col gap-1">
            {ticks.map((tick, i) => {
              const up = tick.change !== null && tick.change > 0;
              const down = tick.change !== null && tick.change < 0;
              return (
                <div key={i} className="flex items-center justify-between rounded bg-[#0d1016] px-3 py-1.5 text-xs">
                  <span className="tabular-nums text-[#484f58]">{tick.time}</span>
                  <span className={`font-mono font-semibold ${i === 0 ? "text-white" : "text-[#8b949e]"}`}>
                    ${tick.price.toFixed(2)}
                  </span>
                  {tick.change !== null ? (
                    <span className={`tabular-nums text-[10px] ${up ? "text-[#3fb950]" : down ? "text-[#f85149]" : "text-[#484f58]"}`}>
                      {up ? "▲" : down ? "▼" : "–"} {Math.abs(tick.change).toFixed(4)}
                    </span>
                  ) : (
                    <span className="text-[10px] text-[#484f58]">first tick</span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Debug panel — dev only */}
      {isDev && testEnabled && (
        <details className="mt-4">
          <summary className="cursor-pointer text-[10px] font-semibold uppercase tracking-wide text-[#484f58] hover:text-[#8b949e]">
            Debug panel
          </summary>
          <div className="mt-2 rounded-lg border border-white/[0.06] bg-[#0b0f17] p-3 font-mono text-[10px] text-[#8b949e]">
            <div>Symbol: {live.symbol}</div>
            <div>Status: {live.status}</div>
            <div>Mode: {live.dataMode}</div>
            <div>Provider: {live.provider}</div>
            <div>API route: /api/market-data/stock-quote?symbol={TEST_SYMBOL}</div>
            <div>Poll interval: 5000 ms</div>
            <div>Successful ticks: {tickCountRef.current}</div>
            <div>Failed ticks: {failCountRef.current}</div>
            <div>Last price: {live.currentPrice}</div>
            <div>Prev price: {live.previousPrice}</div>
            <div>Change: {live.change}</div>
            <div>Change%: {live.changePercent}</div>
            <div>Error: {live.error ?? "none"}</div>
          </div>
        </details>
      )}
    </section>
  );
}

function PriceStat({
  label,
  value,
  valueClass,
}: {
  label: string;
  value: string;
  valueClass?: string;
}) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-[#0d1016] px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wide text-[#8b949e]">{label}</div>
      <div className={`mt-0.5 font-semibold ${valueClass ?? "text-white"}`}>{value}</div>
    </div>
  );
}
