"use client";

import { type NavId } from "@/lib/types";

const navItems: Array<{ id: NavId; label: string }> = [
  { id: "signal", label: "Signal" },
  { id: "paper", label: "Simulator" },
  { id: "runs", label: "Run History" },
  { id: "schedule", label: "Schedule" },
  { id: "settings", label: "Settings" },
  { id: "api-keys", label: "API Keys" },
  { id: "logs", label: "Logs" },
];

export function Sidebar({
  active,
  onNavigate,
  equity,
  availableCapital,
  unrealizedPnl,
  openCount,
  mode,
}: {
  active: NavId;
  onNavigate: (id: NavId) => void;
  equity: number;
  availableCapital: number;
  unrealizedPnl: number;
  openCount: number;
  mode: "live" | "demo";
}) {
  return (
    <aside className="sticky top-14 flex h-[calc(100vh-56px)] w-[260px] shrink-0 flex-col overflow-y-auto border-r border-white/[0.06] bg-[#0d1016]">
      {/* Paper Account */}
      <div className="p-4 border-b border-white/[0.06]">
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-medium text-[#8b949e] uppercase tracking-wide">
            Paper Account
          </span>
          <span
            className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
              mode === "live"
                ? "bg-[#238636]/10 text-[#3fb950]"
                : "bg-[#d29922]/10 text-[#e3b341]"
            }`}
          >
            {mode === "live" ? "LIVE" : "DEMO"}
          </span>
        </div>
        <div className="text-2xl font-semibold text-white tracking-tight mb-3">
          {fmt(equity)}
        </div>
        <div className="grid grid-cols-2 gap-2">
          <div>
            <div className="text-[10px] text-[#8b949e]">Available</div>
            <div className="text-xs font-medium text-white">{fmt(availableCapital)}</div>
          </div>
          <div>
            <div className="text-[10px] text-[#8b949e]">Unrealized</div>
            <div className={`text-xs font-medium ${unrealizedPnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}`}>
              {fmt(unrealizedPnl)}
            </div>
          </div>
          <div>
            <div className="text-[10px] text-[#8b949e]">Open</div>
            <div className="text-xs font-medium text-white">{openCount}</div>
          </div>
          <div>
            <div className="text-[10px] text-[#8b949e]">Mode</div>
            <div className="text-xs font-medium text-white">Paper</div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex flex-col py-2 flex-1">
        {navItems.map((item) => {
          const isActive = active === item.id;
          return (
            <button
              key={item.id}
              onClick={() => onNavigate(item.id)}
              className={`relative mx-2 px-3 py-2 rounded-md text-left text-sm transition-colors ${
                isActive
                  ? "bg-white/[0.06] text-white font-medium"
                  : "text-[#8b949e] hover:text-white hover:bg-white/[0.04]"
              }`}
            >
              {isActive && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 rounded-r bg-[#2f81f7]" />
              )}
              {item.label}
            </button>
          );
        })}
      </nav>

      {/* Footer */}
      <div className="p-4 border-t border-white/[0.06]">
        <div className="text-[10px] text-[#484f58]">
          Simulated orders only
        </div>
      </div>
    </aside>
  );
}

function fmt(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0,
  }).format(value);
}
