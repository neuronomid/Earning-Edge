"use client";

import { formatCurrency } from "@/lib/formatters";
import { type SimulationAccount } from "@/types/simulation";

export function PortfolioSummary({ account }: { account: SimulationAccount }) {
  return (
    <section className="grid grid-cols-2 gap-3 lg:grid-cols-5">
      <SummaryCard label="Cash Balance" value={formatCurrency(account.cashBalance)} />
      <SummaryCard label="Buying Power" value={formatCurrency(account.buyingPower)} />
      <SummaryCard label="Portfolio Value" value={formatCurrency(account.totalPortfolioValue)} />
      <SummaryCard
        label="Realized P&L"
        value={formatCurrency(account.realizedPnl)}
        tone={account.realizedPnl >= 0 ? "good" : "bad"}
      />
      <SummaryCard
        label="Unrealized P&L"
        value={formatCurrency(account.unrealizedPnl)}
        tone={account.unrealizedPnl >= 0 ? "good" : "bad"}
      />
    </section>
  );
}

function SummaryCard({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#121821] p-4">
      <div className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8b949e]">
        {label}
      </div>
      <div className={`mt-2 text-lg font-semibold ${tone === "good" ? "text-[#3fb950]" : tone === "bad" ? "text-[#f85149]" : "text-white"}`}>
        {value}
      </div>
    </div>
  );
}
