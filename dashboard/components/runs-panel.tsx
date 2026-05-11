"use client";

import { type WorkflowRunCard } from "@/lib/dashboard-data";
import { formatDateTime } from "@/lib/formatters";

function LlmBadge({ run }: { run: WorkflowRunCard }) {
  if (run.decisionEngine == null) return null;
  if (run.llmTriggered) {
    const model = run.modelUsed ? run.modelUsed.split("/").pop() : "LLM";
    return (
      <span
        title={`OpenRouter called — model: ${run.modelUsed ?? "unknown"}`}
        className="text-[10px] px-1.5 py-0.5 rounded bg-[#238636]/10 text-[#3fb950] font-medium border border-[#238636]/20"
      >
        OpenRouter ✓ {model}
      </span>
    );
  }
  const label =
    run.decisionEngine === "llm_blocked"
      ? "OpenRouter blocked (key error)"
      : run.decisionEngine === "heuristic_fallback"
        ? "OpenRouter failed → heuristic"
        : run.finalistsSentToLlm === 0
          ? "No candidates — OpenRouter skipped"
          : "Heuristic (no LLM)";
  return (
    <span
      title={label}
      className="text-[10px] px-1.5 py-0.5 rounded bg-[#d29922]/10 text-[#e3b341] font-medium border border-[#d29922]/20"
    >
      {label}
    </span>
  );
}

export function RunsPanel({ runs }: { runs: WorkflowRunCard[] }) {
  return (
    <div className="flex flex-col gap-5">
      <h2 className="text-base font-semibold text-white">Run History</h2>
      <div className="flex flex-col gap-2">
        {runs.map((run) => (
          <div key={run.id} className="rounded-md border border-white/[0.06] bg-[#161b22] p-4">
            <div className="flex items-center justify-between mb-2">
              <div className="font-semibold text-sm text-white">
                {run.selectedTicker ? `${run.selectedTicker} signal` : "No-trade run"}
              </div>
              <div className="flex items-center gap-1.5">
                <LlmBadge run={run} />
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-[#21262d] text-[#8b949e] font-medium">
                  {run.triggerType}
                </span>
              </div>
            </div>
            <div className="text-xs text-[#8b949e] mb-2">
              {formatDateTime(run.startedAt)} · {run.contractsConsidered} contracts · {run.finalistsSentToLlm} candidates
            </div>
            {run.warningText && (
              <div className="text-xs text-[#e3b341] mb-2">{run.warningText}</div>
            )}
            <div className="text-xs text-[#8b949e]">{run.summary}</div>
            {run.watchlist.length > 0 && (
              <div className="text-[11px] text-[#484f58] mt-2">
                Watchlist: {run.watchlist.join(", ")}
              </div>
            )}
          </div>
        ))}
        {runs.length === 0 && (
          <div className="text-sm text-[#8b949e] text-center py-8">No runs yet.</div>
        )}
      </div>
    </div>
  );
}
