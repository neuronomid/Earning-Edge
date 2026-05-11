"use client";

import { type DataMode, type OptionQuoteResult } from "@/lib/marketData/MarketDataProvider";

function DataModeBadge({ mode }: { mode: DataMode }) {
  const cfg = {
    STREAMING: { label: "Streaming", cls: "bg-[#238636]/15 text-[#3fb950] border-[#238636]/30" },
    FALLBACK_REST: { label: "REST fallback", cls: "bg-[#d29922]/15 text-[#e3b341] border-[#d29922]/30" },
    REAL_TIME: { label: "Live",      cls: "bg-[#238636]/15 text-[#3fb950] border-[#238636]/30" },
    DELAYED:   { label: "Delayed",   cls: "bg-[#d29922]/15 text-[#e3b341] border-[#d29922]/30" },
    ESTIMATED: { label: "Estimated", cls: "bg-[#f0883e]/15 text-[#f0883e] border-[#f0883e]/30" },
    MOCK:      { label: "Simulated", cls: "bg-[#58a6ff]/15 text-[#58a6ff] border-[#58a6ff]/30" },
    POLLING:   { label: "Polling",   cls: "bg-[#58a6ff]/15 text-[#58a6ff] border-[#58a6ff]/30" },
    ERROR:     { label: "Error",     cls: "bg-[#f85149]/15 text-[#f85149] border-[#f85149]/30" },
  }[mode] ?? { label: mode, cls: "bg-white/5 text-[#8b949e] border-white/10" };
  return (
    <span className={`rounded border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

function QuoteField({ label, value, sub }: { label: string; value: string | null; sub?: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-[10px] uppercase tracking-wider text-[#8b949e]">{label}</span>
      <span className={`text-sm font-semibold tabular-nums ${value == null ? "text-[#484f58]" : "text-white"}`}>
        {value ?? "—"}
      </span>
      {sub && <span className="text-[10px] text-[#8b949e]">{sub}</span>}
    </div>
  );
}

function greek(v: number | null, digits = 4): string | null {
  if (v == null) return null;
  return v.toFixed(digits);
}

function price(v: number | null): string | null {
  if (v == null) return null;
  return `$${v.toFixed(4)}`;
}

function pct(v: number | null): string | null {
  if (v == null) return null;
  const display = v <= 1.5 ? v * 100 : v;
  return `${display.toFixed(1)}%`;
}

export function LiveQuoteCard({
  quote,
  ticker,
  isLoading,
  error,
  lastUpdated,
}: {
  quote: OptionQuoteResult | null;
  ticker: string;
  isLoading?: boolean;
  error?: string | null;
  lastUpdated?: string | null;
}) {
  if (error) {
    return (
      <div className="rounded-xl border border-[#f85149]/25 bg-[#0d1624] p-4">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-widest text-[#58a6ff]">
          Live Quote — {ticker}
        </div>
        <div className="text-xs text-[#f85149]">{error}</div>
        <div className="mt-2 text-[11px] text-[#8b949e]">
          Option quote unavailable. Verify the backend is running and the contract exists.
        </div>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#0d1624] p-4">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-widest text-[#58a6ff]">
            Live Quote — {ticker}
          </span>
          {quote && <DataModeBadge mode={quote.dataMode} />}
          {isLoading && (
            <span className="h-2 w-2 animate-pulse rounded-full bg-[#58a6ff]" />
          )}
        </div>
        {lastUpdated && (
          <span className="text-[10px] text-[#8b949e]">Updated {lastUpdated}</span>
        )}
      </div>

      {quote == null ? (
        <div className="py-4 text-center text-xs text-[#8b949e]">
          {isLoading ? "Fetching quote..." : "No quote available."}
        </div>
      ) : (
        <>
          {quote.dataMode === "ESTIMATED" || quote.dataMode === "MOCK" ? (
            <div className="mb-3 rounded border border-[#d29922]/20 bg-[#d29922]/5 px-3 py-1.5 text-[11px] text-[#e3b341]">
              {quote.dataMode === "MOCK"
                ? "Simulated / mock quote — not real market data."
                : "Estimated quote — real-time data unavailable."}
            </div>
          ) : null}

          <div className="mb-4 grid grid-cols-3 gap-3 sm:grid-cols-6">
            <QuoteField label="Bid" value={price(quote.bid)} />
            <QuoteField label="Ask" value={price(quote.ask)} />
            <QuoteField label="Mid" value={price(quote.mid)} />
            <QuoteField label="Last" value={price(quote.last)} />
            <QuoteField label="IV" value={pct(quote.impliedVolatility)} />
            {quote.underlyingPrice != null && (
              <QuoteField label="Stock" value={`$${quote.underlyingPrice.toFixed(2)}`} sub="underlying" />
            )}
          </div>

          {(quote.delta != null || quote.gamma != null || quote.theta != null || quote.vega != null) && (
            <div className="border-t border-white/[0.06] pt-3">
              <div className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">Greeks</div>
              <div className="grid grid-cols-4 gap-3">
                <QuoteField label="Δ Delta" value={greek(quote.delta)} />
                <QuoteField label="Γ Gamma" value={greek(quote.gamma)} />
                <QuoteField label="Θ Theta" value={greek(quote.theta)} />
                <QuoteField label="V Vega" value={greek(quote.vega)} />
              </div>
            </div>
          )}

          {(quote.volume != null || quote.openInterest != null) && (
            <div className="mt-3 flex gap-4 border-t border-white/[0.06] pt-3">
              {quote.volume != null && (
                <div>
                  <span className="text-[10px] text-[#8b949e]">Volume </span>
                  <span className="text-xs text-white">{quote.volume.toLocaleString()}</span>
                </div>
              )}
              {quote.openInterest != null && (
                <div>
                  <span className="text-[10px] text-[#8b949e]">OI </span>
                  <span className="text-xs text-white">{quote.openInterest.toLocaleString()}</span>
                </div>
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}
