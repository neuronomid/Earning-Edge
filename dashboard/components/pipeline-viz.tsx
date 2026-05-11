"use client";

import { useEffect, useState } from "react";
import { type DashboardRecommendation } from "@/lib/dashboard-data";

export type PipelineStepStatus = "pending" | "running" | "complete" | "error";

export type PipelineStepViz = {
  id: string;
  label: string;
  description: string;
  status: PipelineStepStatus;
};

export type ScanPayloadPreview = {
  requestedAt: string;
  apiRequest: {
    method: string;
    endpoint: string;
    query: Record<string, string>;
    body: null;
  };
  userCriteria: Record<string, string | number>;
  screenerCriteria: {
    provider: string;
    url: string;
    filters: string[];
    sort: string;
    visibleRows: number;
    retryPolicy: string[];
  };
  providerCriteria: Record<string, string>;
  decisionCriteria: Record<string, string>;
};

const defaultSteps: PipelineStepViz[] = [
  { id: "screener", label: "Screener", description: "Scanning Finviz earnings calendar", status: "pending" },
  { id: "candidates", label: "Candidates", description: "Validating top candidates", status: "pending" },
  { id: "market-data", label: "Market Data", description: "Fetching price & volume data", status: "pending" },
  { id: "news", label: "News Analysis", description: "Analyzing news sentiment", status: "pending" },
  { id: "options", label: "Options Chain", description: "Scanning option chains", status: "pending" },
  { id: "scoring", label: "Scoring", description: "Scoring opportunities", status: "pending" },
  { id: "decision", label: "AI Decision", description: "LLM decision layer", status: "pending" },
  { id: "finalize", label: "Finalize", description: "Building recommendation", status: "pending" },
];

export function PipelineViz({
  isOpen,
  onClose,
  recommendations,
  scanPayload,
  onSelectRecommendation,
}: {
  isOpen: boolean;
  onClose: () => void;
  recommendations: DashboardRecommendation[];
  scanPayload: ScanPayloadPreview | null;
  onSelectRecommendation: (id: string) => void;
}) {
  const [steps, setSteps] = useState<PipelineStepViz[]>(defaultSteps);
  const [phase, setPhase] = useState<"scanning" | "complete" | "error">("scanning");
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!isOpen) {
      setSteps(defaultSteps);
      setPhase("scanning");
      setProgress(0);
      return;
    }

    const timings = [0, 800, 1600, 2400, 3200, 4000, 4800, 5600];
    const timeouts: NodeJS.Timeout[] = [];

    timings.forEach((time, index) => {
      const t = setTimeout(() => {
        setSteps((prev) =>
          prev.map((step, i) => {
            if (i < index) return { ...step, status: "complete" };
            if (i === index) return { ...step, status: "running" };
            return step;
          }),
        );
        setProgress(((index + 1) / defaultSteps.length) * 100);
      }, time);
      timeouts.push(t);
    });

    const completeTimeout = setTimeout(() => {
      setSteps((prev) => prev.map((step) => ({ ...step, status: "complete" })));
      setProgress(100);
      setPhase("complete");
    }, 6400);
    timeouts.push(completeTimeout);

    return () => timeouts.forEach((t) => clearTimeout(t));
  }, [isOpen]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/60" onClick={phase === "complete" ? onClose : undefined} />
      <div className="relative w-full max-w-3xl max-h-[90vh] overflow-y-auto rounded-lg border border-white/[0.06] bg-[#161b22]">
        {/* Header */}
        <div className="p-5 border-b border-white/[0.06]">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-lg font-semibold text-white">
                {phase === "scanning" ? "Running Weekly Scan" : "Scan Complete"}
              </h2>
              <p className="text-sm text-[#8b949e] mt-0.5">
                {phase === "scanning"
                  ? "Analyzing earnings opportunities..."
                  : `${recommendations.length} recommendations generated`}
              </p>
            </div>
            {phase === "complete" && (
              <button
                onClick={onClose}
                className="w-8 h-8 rounded-md bg-[#21262d] border border-white/[0.06] flex items-center justify-center text-[#8b949e] hover:text-white hover:bg-[#30363d] transition-colors"
              >
                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            )}
          </div>
          <div className="mt-3 h-1 rounded-full bg-[#21262d] overflow-hidden">
            <div
              className="h-full rounded-full bg-[#238636] transition-all duration-500 ease-out"
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        {/* Content */}
        <div className="p-5">
          {scanPayload && <ScanCriteria payload={scanPayload} />}

          {phase === "scanning" && (
            <div className="mt-5 flex flex-col gap-0">
              {steps.map((step, index) => (
                <PipelineStepRow key={step.id} step={step} isLast={index === steps.length - 1} />
              ))}
            </div>
          )}

          {phase === "complete" && (
            <div className="mt-5 flex flex-col gap-4">
              <div className="rounded-md bg-[#238636]/5 border border-[#238636]/10 p-4 flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-[#238636]/10 flex items-center justify-center">
                  <svg className="w-4 h-4 text-[#3fb950]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                  </svg>
                </div>
                <div>
                  <div className="text-sm font-medium text-[#3fb950]">Scan Complete</div>
                  <div className="text-xs text-[#8b949e]">
                    {recommendations.length} setups found · Top pick ready
                  </div>
                </div>
              </div>

              {recommendations.length > 0 ? (
                <div className="flex flex-col gap-2">
                  <div className="text-xs font-medium text-[#8b949e] uppercase tracking-wide">
                    Recommendations
                  </div>
                  {recommendations.map((rec) => (
                    <button
                      key={rec.id}
                      onClick={() => {
                        onSelectRecommendation(rec.id);
                        onClose();
                      }}
                      className="text-left rounded-md border border-white/[0.06] bg-[#0d1016] p-4 hover:border-[#2f81f7]/30 hover:bg-[#2f81f7]/5 transition-colors"
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-3">
                          <div className="w-8 h-8 rounded bg-[#21262d] flex items-center justify-center font-semibold text-xs text-white">
                            {rec.ticker.slice(0, 2)}
                          </div>
                          <div>
                            <div className="font-medium text-sm text-white">{rec.ticker}</div>
                            <div className="text-xs text-[#8b949e]">{rec.companyName}</div>
                          </div>
                        </div>
                        <div className="text-right">
                          <span
                            className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${
                              rec.status === "recommend"
                                ? "bg-[#238636]/10 text-[#3fb950]"
                                : "bg-[#d29922]/10 text-[#e3b341]"
                            }`}
                          >
                            {rec.status === "recommend" ? "Recommended" : "Watchlist"}
                          </span>
                        </div>
                      </div>
                      <div className="text-xs text-[#8b949e] line-clamp-2">{rec.reasonSummary}</div>
                    </button>
                  ))}
                </div>
              ) : (
                <div className="rounded-md border border-white/[0.06] bg-[#0d1016] p-6 text-center">
                  <div className="text-sm text-[#8b949e]">No trade recommendations this week.</div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ScanCriteria({ payload }: { payload: ScanPayloadPreview }) {
  return (
    <section className="rounded-md border border-white/[0.06] bg-[#0d1016] p-4">
      <div className="mb-3 flex flex-col gap-1 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-xs font-medium uppercase tracking-wide text-[#58a6ff]">
            Scan API Payload
          </div>
          <div className="mt-1 font-mono text-xs text-[#c9d1d9]">
            {payload.apiRequest.method} {payload.apiRequest.endpoint}
          </div>
        </div>
        <div className="font-mono text-[10px] text-[#8b949e]">{payload.requestedAt}</div>
      </div>

      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        <PayloadFact label="Account" value={`$${Number(payload.userCriteria.accountSize).toLocaleString()}`} />
        <PayloadFact label="Risk" value={String(payload.userCriteria.riskProfile)} />
        <PayloadFact label="Strategy" value={String(payload.userCriteria.strategyPermission)} />
        <PayloadFact label="Max Contracts" value={String(payload.userCriteria.maxContracts)} />
        <PayloadFact label="Broker" value={String(payload.userCriteria.broker)} />
        <PayloadFact label="Timezone" value={String(payload.userCriteria.timezone)} />
      </div>

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <PayloadFact label="Screener" value={payload.screenerCriteria.provider} />
        <PayloadFact label="Visible Rows" value={String(payload.screenerCriteria.visibleRows)} />
        <PayloadFact label="OpenRouter" value={payload.providerCriteria.openRouter} />
        <PayloadFact label="Alpaca" value={payload.providerCriteria.alpaca} />
        <PayloadFact label="Alpha Vantage" value={payload.providerCriteria.alphaVantage} />
        <PayloadFact label="Decision Bands" value={payload.decisionCriteria.actionBands} />
      </div>

      <details className="mt-3 rounded-md border border-white/[0.06] bg-black/20">
        <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-[#c9d1d9]">
          Full sanitized payload
        </summary>
        <pre className="max-h-72 overflow-auto border-t border-white/[0.06] p-3 text-[11px] leading-5 text-[#c9d1d9]">
          {JSON.stringify(payload, null, 2)}
        </pre>
      </details>
    </section>
  );
}

function PayloadFact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-[#161b22] px-3 py-2">
      <div className="text-[10px] font-medium uppercase tracking-wide text-[#8b949e]">{label}</div>
      <div className="mt-0.5 break-words text-xs font-medium text-white">{value}</div>
    </div>
  );
}

function PipelineStepRow({ step, isLast }: { step: PipelineStepViz; isLast: boolean }) {
  return (
    <div className="flex gap-3">
      <div className="flex flex-col items-center">
        <div
          className={`w-6 h-6 rounded-full flex items-center justify-center border transition-all duration-500 ${
            step.status === "complete"
              ? "bg-[#238636]/10 border-[#238636] text-[#3fb950]"
              : step.status === "running"
                ? "bg-[#1f6feb]/10 border-[#1f6feb] text-[#58a6ff]"
                : "bg-[#21262d] border-white/[0.06] text-[#484f58]"
          }`}
        >
          {step.status === "complete" ? (
            <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
            </svg>
          ) : step.status === "running" ? (
            <div className="w-2 h-2 rounded-full bg-current animate-pulse" />
          ) : (
            <div className="w-1.5 h-1.5 rounded-full bg-current" />
          )}
        </div>
        {!isLast && (
          <div
            className={`w-px flex-1 min-h-[20px] transition-colors duration-500 ${
              step.status === "complete" ? "bg-[#238636]/20" : "bg-white/[0.04]"
            }`}
          />
        )}
      </div>
      <div className="pb-3 flex-1">
        <div
          className={`text-sm font-medium transition-colors duration-300 ${
            step.status === "complete"
              ? "text-[#3fb950]"
              : step.status === "running"
                ? "text-[#58a6ff]"
                : "text-[#484f58]"
          }`}
        >
          {step.label}
        </div>
        <div className={`text-xs ${step.status === "pending" ? "text-[#30363d]" : "text-[#8b949e]"}`}>
          {step.description}
        </div>
      </div>
    </div>
  );
}
