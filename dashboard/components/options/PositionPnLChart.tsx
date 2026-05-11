"use client";

import { useEffect, useRef, useState } from "react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

export type PnLSnapshot = {
  timestamp: string;
  equity: number;
  unrealizedPnL: number;
  realizedPnL: number;
};

export type OptionPriceSnapshot = {
  timestamp: string;
  optionPrice: number;
  underlyingPrice?: number;
};

const PALETTE = {
  equity: "#58a6ff",
  unrealized: "#3fb950",
  realized: "#a371f7",
  option: "#f0883e",
  underlying: "#e3b341",
  gridLine: "rgba(255,255,255,0.06)",
  tick: "#8b949e",
};

function formatTime(ts: string) {
  const d = new Date(ts);
  return `${d.getHours().toString().padStart(2, "0")}:${d.getMinutes().toString().padStart(2, "0")}`;
}

function formatUSD(n: number) {
  const sign = n >= 0 ? "+" : "";
  return `${sign}$${Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function formatDollar(n: number) {
  return `$${n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function EmptyChart({ label }: { label: string }) {
  return (
    <div className="flex h-32 items-center justify-center text-xs text-[#8b949e]">
      {label}
    </div>
  );
}

export function EquityChart({ snapshots }: { snapshots: PnLSnapshot[] }) {
  if (snapshots.length < 2) {
    return <EmptyChart label="Account equity chart — opens after trades." />;
  }

  const data = snapshots.map((s) => ({
    t: formatTime(s.timestamp),
    equity: s.equity,
    pnl: s.unrealizedPnL + s.realizedPnL,
  }));

  const minEquity = Math.min(...data.map((d) => d.equity));
  const maxEquity = Math.max(...data.map((d) => d.equity));
  const padding = Math.max(10, (maxEquity - minEquity) * 0.1);

  return (
    <div className="h-48">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <defs>
            <linearGradient id="equityGrad" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor={PALETTE.equity} stopOpacity={0.15} />
              <stop offset="95%" stopColor={PALETTE.equity} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid stroke={PALETTE.gridLine} vertical={false} />
          <XAxis
            dataKey="t"
            tick={{ fontSize: 10, fill: PALETTE.tick }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            domain={[minEquity - padding, maxEquity + padding]}
            tick={{ fontSize: 10, fill: PALETTE.tick }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}k`}
            width={44}
          />
          <Tooltip
            contentStyle={{ background: "#0d1624", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6 }}
            labelStyle={{ color: PALETTE.tick, fontSize: 11 }}
            itemStyle={{ color: PALETTE.equity, fontSize: 11 }}
            formatter={(v) => [formatDollar(Number(v)), "Equity"]}
          />
          <Area
            type="monotone"
            dataKey="equity"
            stroke={PALETTE.equity}
            strokeWidth={1.5}
            fill="url(#equityGrad)"
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export function OptionPriceChart({ snapshots, ticker }: { snapshots: OptionPriceSnapshot[]; ticker: string }) {
  if (snapshots.length < 2) {
    return <EmptyChart label={`${ticker} option price chart — opens after position is opened.`} />;
  }

  const data = snapshots.map((s) => ({
    t: formatTime(s.timestamp),
    option: s.optionPrice,
    stock: s.underlyingPrice,
  }));

  return (
    <div className="h-40">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke={PALETTE.gridLine} vertical={false} />
          <XAxis
            dataKey="t"
            tick={{ fontSize: 10, fill: PALETTE.tick }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            yAxisId="option"
            orientation="left"
            tick={{ fontSize: 10, fill: PALETTE.option }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => `$${v.toFixed(2)}`}
            width={44}
          />
          {data[0]?.stock != null && (
            <YAxis
              yAxisId="stock"
              orientation="right"
              tick={{ fontSize: 10, fill: PALETTE.underlying }}
              tickLine={false}
              axisLine={false}
              tickFormatter={(v: number) => `$${v.toFixed(0)}`}
              width={40}
            />
          )}
          <Tooltip
            contentStyle={{ background: "#0d1624", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6 }}
            labelStyle={{ color: PALETTE.tick, fontSize: 11 }}
            formatter={(v, name) => [
              formatDollar(Number(v)),
              name === "option" ? "Option Price" : "Stock Price",
            ]}
          />
          <Line
            yAxisId="option"
            type="monotone"
            dataKey="option"
            stroke={PALETTE.option}
            strokeWidth={1.5}
            dot={false}
          />
          {data[0]?.stock != null && (
            <Line
              yAxisId="stock"
              type="monotone"
              dataKey="stock"
              stroke={PALETTE.underlying}
              strokeWidth={1}
              strokeDasharray="3 2"
              dot={false}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function PnLBarChart({ snapshots }: { snapshots: PnLSnapshot[] }) {
  if (snapshots.length < 2) {
    return <EmptyChart label="P&L chart — opens after trades." />;
  }

  const data = snapshots.map((s) => ({
    t: formatTime(s.timestamp),
    unrealized: s.unrealizedPnL,
    realized: s.realizedPnL,
  }));

  return (
    <div className="h-32">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: 8 }}>
          <CartesianGrid stroke={PALETTE.gridLine} vertical={false} />
          <XAxis
            dataKey="t"
            tick={{ fontSize: 10, fill: PALETTE.tick }}
            tickLine={false}
            axisLine={false}
            interval="preserveStartEnd"
          />
          <YAxis
            tick={{ fontSize: 10, fill: PALETTE.tick }}
            tickLine={false}
            axisLine={false}
            tickFormatter={(v: number) => formatUSD(v)}
            width={56}
          />
          <Tooltip
            contentStyle={{ background: "#0d1624", border: "1px solid rgba(255,255,255,0.1)", borderRadius: 6 }}
            labelStyle={{ color: PALETTE.tick, fontSize: 11 }}
            formatter={(v, name) => [
              formatUSD(Number(v)),
              name === "unrealized" ? "Unrealized P&L" : "Realized P&L",
            ]}
          />
          <Line type="monotone" dataKey="unrealized" stroke={PALETTE.unrealized} strokeWidth={1.5} dot={false} />
          <Line type="monotone" dataKey="realized" stroke={PALETTE.realized} strokeWidth={1.5} dot={false} strokeDasharray="4 2" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
