"use client";

import { useState } from "react";
import { type DashboardRecommendation, type DashboardSnapshot } from "@/lib/dashboard-data";
import { formatCurrency, formatDate, formatPercent } from "@/lib/formatters";
import { OptionOrderTicket } from "@/components/OptionOrderTicket";
import { type SimulationAccount } from "@/types/simulation";

export function SignalPanel({
  snapshot,
  selectedId,
  onSelect,
  onWhy,
  onRisk,
  onSaveNote,
  onAlternative,
  onFeedback,
  account,
  onAccountUpdated,
  onStatus,
  busy,
}: {
  snapshot: DashboardSnapshot;
  selectedId: string | null;
  account: SimulationAccount;
  onSelect: (id: string) => void;
  onWhy: (rec: DashboardRecommendation) => void;
  onRisk: (rec: DashboardRecommendation) => void;
  onSaveNote: (rec: DashboardRecommendation) => void;
  onAlternative: (rec: DashboardRecommendation) => void;
  onFeedback: (rec: DashboardRecommendation, action: "bought" | "skipped") => void;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
  busy: string | null;
}) {
  const selected =
    snapshot.recommendations.find((r) => r.id === selectedId) ?? snapshot.recommendations[0] ?? null;

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#58a6ff]">
            Signal Workspace
          </div>
          <h2 className="mt-1 text-xl font-semibold tracking-tight text-white">Recommendation desk</h2>
        </div>
        <span className="w-fit rounded-md border border-white/[0.08] bg-[#0d1016] px-3 py-1.5 text-xs text-[#8b949e]">
          {snapshot.recommendations.length} setups loaded
        </span>
      </div>

      {snapshot.warningText && (
        <div className="rounded-md border border-[#d29922]/20 bg-[#d29922]/10 px-3 py-2 text-xs text-[#e3b341]">
          {snapshot.warningText}
        </div>
      )}

      <div className="grid gap-5 2xl:grid-cols-[300px_minmax(0,1fr)]">
        <div className="grid w-full shrink-0 gap-2 md:grid-cols-2 2xl:sticky 2xl:top-20 2xl:flex 2xl:max-h-[calc(100vh-96px)] 2xl:flex-col 2xl:overflow-y-auto">
          {snapshot.recommendations.map((rec) => (
            <button
              key={rec.id}
              onClick={() => onSelect(rec.id)}
              className={`rounded-lg border px-3 py-3 text-left transition-colors ${
                rec.id === selected?.id
                  ? "border-[#2f81f7]/50 bg-[#13233a]"
                  : "border-white/[0.06] bg-[#121821] hover:border-white/[0.12] hover:bg-[#161d27]"
              }`}
            >
              <div className="mb-1 flex items-center justify-between gap-3">
                <span className="text-sm font-semibold text-white">
                  {rec.rank}. {rec.ticker}
                </span>
                <span
                  className={`rounded px-1.5 py-0.5 text-[10px] font-medium ${
                    rec.status === "recommend"
                      ? "bg-[#238636]/10 text-[#3fb950]"
                      : "bg-[#d29922]/10 text-[#e3b341]"
                  }`}
                >
                  {rec.status === "recommend" ? "Recommended" : "Watchlist"}
                </span>
              </div>
              <div className="text-xs text-[#8b949e]">{rec.companyName}</div>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <span className="text-[10px] text-[#8b949e]">Score {rec.finalScore}</span>
                <span className="text-[10px] text-[#8b949e]">
                  {rec.positionSide} {rec.optionType}
                </span>
                <span className={rec.direction === "Bullish" ? "text-[10px] text-[#3fb950]" : "text-[10px] text-[#f85149]"}>
                  {rec.direction}
                </span>
                {rec.feedbackAction && (
                  <span className={`text-[10px] ${rec.feedbackAction === "bought" ? "text-[#3fb950]" : "text-[#8b949e]"}`}>
                    {rec.feedbackAction === "bought" ? "Bought" : "Skipped"}
                  </span>
                )}
              </div>
            </button>
          ))}
          {snapshot.recommendations.length === 0 && (
            <div className="py-8 text-center text-sm text-[#8b949e]">No recommendations yet.</div>
          )}
        </div>

        <div className="min-w-0">
          {selected ? (
            <RecommendationCard
              rec={selected}
              onWhy={() => onWhy(selected)}
              onRisk={() => onRisk(selected)}
              onSaveNote={() => onSaveNote(selected)}
              onAlternative={() => onAlternative(selected)}
              onFeedback={(action) => onFeedback(selected, action)}
              account={account}
              onAccountUpdated={onAccountUpdated}
              onStatus={onStatus}
              busy={busy}
            />
          ) : (
            <div className="rounded-lg border border-white/[0.06] bg-[#161b22] p-8 text-center">
              {snapshot.telegramMessageText ? (
                <div
                  className="mx-auto max-w-2xl text-left text-sm leading-7 text-[#c9d1d9]"
                  dangerouslySetInnerHTML={{ __html: toDisplayHtml(snapshot.telegramMessageText) }}
                />
              ) : (
                <div className="text-sm text-[#8b949e]">No recommendations yet.</div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RecommendationCard({
  rec,
  onWhy,
  onRisk,
  onSaveNote,
  onAlternative,
  onFeedback,
  account,
  onAccountUpdated,
  onStatus,
  busy,
}: {
  rec: DashboardRecommendation;
  onWhy: () => void;
  onRisk: () => void;
  onSaveNote: () => void;
  onAlternative: () => void;
  onFeedback: (action: "bought" | "skipped") => void;
  account: SimulationAccount;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
  busy: string | null;
}) {
  const [detailHtml, setDetailHtml] = useState<string | null>(null);
  const [detailTitle, setDetailTitle] = useState("");

  async function handleWhy() {
    setDetailTitle(`Why ${rec.ticker}`);
    setDetailHtml("Loading...");
    onWhy();
    try {
      const { html } = await (await import("@/lib/api")).fetchRecommendationAction(rec.id, "why");
      setDetailHtml(html);
    } catch {
      setDetailHtml(buildWhyHtml(rec));
    }
  }

  async function handleRisk() {
    setDetailTitle(`Risk / Sizing for ${rec.ticker}`);
    setDetailHtml("Loading...");
    onRisk();
    try {
      const { html } = await (await import("@/lib/api")).fetchRecommendationAction(rec.id, "risk");
      setDetailHtml(html);
    } catch {
      setDetailHtml(buildRiskHtml(rec));
    }
  }

  async function handleSaveNote() {
    setDetailTitle(`Saved Note for ${rec.ticker}`);
    setDetailHtml("Loading...");
    onSaveNote();
    try {
      const { html } = await (await import("@/lib/api")).fetchRecommendationAction(rec.id, "save-note");
      setDetailHtml(html);
    } catch {
      setDetailHtml(buildNoteHtml(rec));
    }
  }

  return (
    <div className="grid gap-4 min-[1180px]:grid-cols-[minmax(0,1fr)_360px]">
      <section className="order-2 rounded-lg border border-white/[0.06] bg-[#121821] p-5 min-[1180px]:order-1">
        <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-[#8b949e]">
              {rec.setupLabel}
            </div>
            <h3 className="text-2xl font-semibold tracking-tight text-white">
              {rec.ticker}{" "}
              <span className="text-base font-normal text-[#8b949e]">
                {rec.positionSide} {rec.optionType}
              </span>
            </h3>
            <p className="mt-1 max-w-2xl text-sm leading-6 text-[#9ca6b3]">{rec.reasonSummary}</p>
          </div>
          <span
            className={`w-fit rounded-md px-2 py-1 text-xs font-medium ${
              rec.direction === "Bullish"
                ? "bg-[#238636]/10 text-[#3fb950]"
                : "bg-[#f85149]/10 text-[#f85149]"
            }`}
          >
            {rec.direction}
          </span>
        </div>

        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
          <Fact label="Strike" value={formatCurrency(rec.strike)} />
          <Fact label="Expiry" value={formatDate(rec.expiry)} />
          <Fact label="Entry" value={formatCurrency(rec.suggestedEntry * 100)} />
          <Fact label="Breakeven" value={formatCurrency(rec.breakeven)} />
          <Fact label="Expected Move" value={rec.expectedMove} />
          <Fact label="Confidence" value={`${rec.confidenceScore}/100`} />
        </div>

        <div className="mt-4 grid gap-2 sm:grid-cols-4">
          <Score label="Final" value={rec.finalScore} />
          <Score label="Direction" value={rec.directionScore} />
          <Score label="Contract" value={rec.contractScore} />
          <Score label="Data" value={rec.dataConfidence} />
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-2">
          <EvidenceList title="Key evidence" items={rec.keyEvidence.slice(0, 3)} tone="good" />
          <EvidenceList title="Main concerns" items={rec.keyConcerns.slice(0, 3)} tone="warning" />
        </div>

        <div className="mt-4 rounded-lg border border-white/[0.06] bg-[#0d1016] p-3">
          <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <div className="flex flex-wrap gap-2">
              <ActionBtn label="Why this?" busy={busy === "why"} onClick={handleWhy} />
              <ActionBtn label="Risk / Sizing" busy={busy === "risk"} onClick={handleRisk} />
              <ActionBtn label="Save Note" busy={busy === "save-note"} onClick={handleSaveNote} />
              <ActionBtn label="Alternatives" busy={busy === "alternative"} onClick={onAlternative} />
            </div>
            <div className="grid grid-cols-2 gap-2 lg:w-64">
              <button
                onClick={() => onFeedback("bought")}
                disabled={busy === "bought"}
                className={`rounded-md py-2 text-sm font-medium transition-colors ${
                  rec.feedbackAction === "bought"
                    ? "bg-[#238636] text-white"
                    : "border border-[#238636]/20 bg-[#238636]/10 text-[#3fb950] hover:bg-[#238636]/20"
                }`}
              >
                {busy === "bought" ? "Saving..." : "I bought it"}
              </button>
              <button
                onClick={() => onFeedback("skipped")}
                disabled={busy === "skipped"}
                className={`rounded-md py-2 text-sm font-medium transition-colors ${
                  rec.feedbackAction === "skipped"
                    ? "bg-[#30363d] text-white"
                    : "border border-white/[0.06] bg-[#21262d] text-[#8b949e] hover:bg-[#30363d] hover:text-white"
                }`}
              >
                {busy === "skipped" ? "Saving..." : "I skipped it"}
              </button>
            </div>
          </div>
        </div>

        {detailHtml && (
          <div className="mt-4 rounded-lg border border-white/[0.06] bg-[#0d1016] p-4">
            <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-[#2f81f7]">
              {detailTitle}
            </div>
            <div
              className="text-sm leading-7 text-[#c9d1d9]"
              dangerouslySetInnerHTML={{ __html: toDisplayHtml(detailHtml) }}
            />
          </div>
        )}
      </section>

      <div className="order-1 min-[1180px]:order-2 min-[1180px]:sticky min-[1180px]:top-20 min-[1180px]:self-start">
        <OptionOrderTicket
          recommendation={rec}
          account={account}
          onAccountUpdated={onAccountUpdated}
          onStatus={onStatus}
        />
      </div>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-[#0d1016] px-3 py-2">
      <div className="text-[10px] text-[#8b949e]">{label}</div>
      <div className="text-xs font-medium text-white">{value}</div>
    </div>
  );
}

function Score({ label, value }: { label: string; value: number }) {
  const normalized = Math.max(0, Math.min(100, value));

  return (
    <div className="rounded-md border border-white/[0.06] bg-[#0d1016] px-3 py-2">
      <div className="text-[10px] text-[#8b949e]">{label}</div>
      <div className="mt-1 flex items-center gap-2">
        <div className="h-1.5 flex-1 rounded-full bg-white/[0.06]">
          <div className="h-full rounded-full bg-[#2f81f7]" style={{ width: `${normalized}%` }} />
        </div>
        <div className="w-7 text-right text-sm font-semibold text-white">{value}</div>
      </div>
    </div>
  );
}

function EvidenceList({
  title,
  items,
  tone,
}: {
  title: string;
  items: string[];
  tone: "good" | "warning";
}) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#0d1016] p-3">
      <div
        className={
          tone === "good"
            ? "text-[11px] font-semibold uppercase tracking-wide text-[#3fb950]"
            : "text-[11px] font-semibold uppercase tracking-wide text-[#e3b341]"
        }
      >
        {title}
      </div>
      <div className="mt-2 flex flex-col gap-2">
        {items.map((item) => (
          <div key={item} className="text-sm leading-5 text-[#c9d1d9]">
            {item}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActionBtn({ label, busy, onClick }: { label: string; busy?: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      disabled={busy}
      className="rounded-md border border-white/[0.06] bg-[#21262d] px-3 py-2 text-xs font-medium text-[#c9d1d9] transition-colors hover:bg-[#30363d] hover:text-white disabled:opacity-50"
    >
      {busy ? "Loading..." : label}
    </button>
  );
}

function toDisplayHtml(value: string) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<b>", "__B_OPEN__")
    .replaceAll("</b>", "__B_CLOSE__")
    .replaceAll("<br>", "__BR__")
    .replaceAll("<br />", "__BR__")
    .replaceAll("<br/>", "__BR__")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll("__B_OPEN__", "<b>")
    .replaceAll("__B_CLOSE__", "</b>")
    .replaceAll("__BR__", "<br />")
    .replaceAll("\n", "<br />")
    .replaceAll("- ", "&bull; ");
}

function buildWhyHtml(rec: DashboardRecommendation) {
  return [
    `<b>Why ${rec.ticker}</b>`,
    ``,
    rec.reasonSummary,
    ``,
    `<b>Key evidence</b>`,
    ...rec.keyEvidence.slice(0, 4).map((item) => `- ${item}`),
    ``,
    `<b>Main concerns</b>`,
    ...rec.keyConcerns.slice(0, 3).map((item) => `- ${item}`),
  ].join("\n");
}

function buildRiskHtml(rec: DashboardRecommendation) {
  return [
    `<b>Risk / Sizing for ${rec.ticker}</b>`,
    ``,
    `Recommended strategy: ${rec.positionSide} ${rec.optionType}`,
    `Strike: ${formatCurrency(rec.strike)}`,
    `Expiry: ${formatDate(rec.expiry)}`,
    `Suggested quantity: ${rec.suggestedQuantity || 0} contract(s)`,
    `Stored sizing note: ${rec.estimatedMaxLoss}`,
    `Account risk: ${formatPercent(rec.accountRiskPercent)}`,
    `Spread: ${rec.spreadPercent.toFixed(1)}%`,
    `Open interest: ${rec.openInterest}`,
  ].join("\n");
}

function buildNoteHtml(rec: DashboardRecommendation) {
  return [
    `<b>Saved Note for ${rec.ticker}</b>`,
    ``,
    rec.reasonSummary,
    ``,
    `Confidence: ${rec.confidenceScore}/100`,
  ].join("\n");
}
