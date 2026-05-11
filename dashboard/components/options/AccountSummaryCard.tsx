"use client";

import { type SimulationAccount } from "@/types/simulation";

function Stat({
  label,
  value,
  tone,
  sub,
}: {
  label: string;
  value: string;
  tone?: "positive" | "negative" | "neutral";
  sub?: string;
}) {
  const valueColor =
    tone === "positive"
      ? "text-[#3fb950]"
      : tone === "negative"
        ? "text-[#f85149]"
        : "text-white";
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-[#8b949e]">{label}</span>
      <span className={`text-lg font-semibold tabular-nums leading-tight ${valueColor}`}>{value}</span>
      {sub && <span className="text-[10px] text-[#8b949e]">{sub}</span>}
    </div>
  );
}

function fmt(n: number, showSign = false) {
  const sign = showSign && n > 0 ? "+" : "";
  return `${sign}${new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n)}`;
}

function pnlTone(n: number): "positive" | "negative" | "neutral" {
  if (n > 0) return "positive";
  if (n < 0) return "negative";
  return "neutral";
}

export function AccountSummaryCard({ account }: { account: SimulationAccount }) {
  const totalPnL = account.realizedPnl + account.unrealizedPnl;
  const totalPnLPct =
    account.startingCash > 0 ? (totalPnL / account.startingCash) * 100 : 0;
  const openCount = account.openPositions.length;

  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#0d1624] p-4">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-[#58a6ff]">
          Simulation Account
        </span>
        <span className="text-[10px] text-[#8b949e]">
          {openCount} open {openCount === 1 ? "position" : "positions"}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-x-6 gap-y-4 sm:grid-cols-4">
        <Stat label="Equity" value={fmt(account.totalPortfolioValue)} sub="cash + positions" />
        <Stat label="Cash Balance" value={fmt(account.cashBalance)} />
        <Stat
          label="Buying Power"
          value={fmt(account.buyingPower)}
          sub={account.buyingPower < 500 ? "low" : undefined}
          tone={account.buyingPower < 500 ? "negative" : "neutral"}
        />
        <Stat
          label="Total P&L"
          value={fmt(totalPnL, true)}
          sub={`${totalPnLPct > 0 ? "+" : ""}${totalPnLPct.toFixed(2)}%`}
          tone={pnlTone(totalPnL)}
        />
      </div>

      <div className="mt-4 border-t border-white/[0.06] pt-4">
        <div className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Stat
            label="Unrealized P&L"
            value={fmt(account.unrealizedPnl, true)}
            tone={pnlTone(account.unrealizedPnl)}
          />
          <Stat
            label="Realized P&L"
            value={fmt(account.realizedPnl, true)}
            tone={pnlTone(account.realizedPnl)}
          />
          <Stat label="Starting Balance" value={fmt(account.startingCash)} />
          <Stat
            label="Open Value"
            value={fmt(
              account.openPositions.reduce((s, p) => s + p.currentMarketValue, 0),
            )}
          />
        </div>
      </div>

      {account.notifications.length > 0 && (
        <div className="mt-3 space-y-1">
          {account.notifications.slice(0, 2).map((n) => (
            <div
              key={n.id}
              className={`rounded px-2 py-1 text-[11px] ${
                n.type === "SUCCESS"
                  ? "bg-[#238636]/10 text-[#3fb950]"
                  : n.type === "WARNING"
                    ? "bg-[#d29922]/10 text-[#e3b341]"
                    : "bg-[#58a6ff]/10 text-[#58a6ff]"
              }`}
            >
              {n.message}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
