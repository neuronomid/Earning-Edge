"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  demoSnapshot,
  type DashboardUser,
  type DashboardRecommendation,
  type DashboardSnapshot,
} from "@/lib/dashboard-data";
import { type NavId } from "@/lib/types";
import {
  type DashboardAuthResponse,
  fetchDashboardSnapshot,
  fetchNextAlternative,
  runScan,
  submitRecommendationFeedback,
} from "@/lib/api";
import { usePortfolioPolling } from "@/hooks/usePortfolioPolling";
import { useSimulationStore } from "@/stores/useSimulationStore";
import { type SimulationAccount } from "@/types/simulation";
import { Sidebar } from "@/components/sidebar";
import { SignalPanel } from "@/components/signal-panel";
import { PaperPanel } from "@/components/paper-panel";
import { RunsPanel } from "@/components/runs-panel";
import { SchedulePanel } from "@/components/schedule-panel";
import { SettingsPanel } from "@/components/settings-panel";
import { ApiKeysPanel } from "@/components/api-keys-panel";
import { LogsPanel } from "@/components/logs-panel";
import { PipelineViz, type ScanPayloadPreview } from "@/components/pipeline-viz";
import { AuthPanel } from "@/components/auth-panel";

export { type NavId };

const DASHBOARD_SESSION_KEY = "earning-edge-dashboard-session";

type DashboardSession = {
  userId: string;
  username: string | null;
  name: string;
};

export function Dashboard() {
  const [snapshot, setSnapshot] = useState<DashboardSnapshot>(demoSnapshot);
  const [selectedId, setSelectedId] = useState<string | null>(demoSnapshot.selectedRecommendationId);
  const [activeNav, setActiveNav] = useState<NavId>("signal");
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState("Sign in to load your dashboard.");
  const [showPipeline, setShowPipeline] = useState(false);
  const [scanPayload, setScanPayload] = useState<ScanPayloadPreview | null>(null);
  const [session, setSession] = useState<DashboardSession | null>(null);
  const [authReady, setAuthReady] = useState(false);

  const accountId = snapshot.user.id || "demo-user";
  const startingCash = snapshot.user.accountSize || demoSnapshot.user.accountSize;
  const portfolio = usePortfolioPolling(accountId, startingCash);

  // When account size changes, immediately clear stale portfolio state so the
  // UI doesn't show the old balance while the re-poll is in-flight.
  const prevStartingCash = useRef(startingCash);
  useEffect(() => {
    if (prevStartingCash.current !== startingCash) {
      const cashDelta = startingCash - prevStartingCash.current;
      prevStartingCash.current = startingCash;
      const current = portfolio.account;
      if (current) {
        portfolio.setAccount({
          ...current,
          startingCash,
          cashBalance: roundMoney(current.cashBalance + cashDelta),
          totalPortfolioValue: roundMoney(current.totalPortfolioValue + cashDelta),
          buyingPower: roundMoney(current.buyingPower + cashDelta),
          updatedAt: new Date().toISOString(),
        });
      }
    }
  }, [startingCash, portfolio]);
  const { setAccount: storeAccount } = useSimulationStore();
  const account = useMemo(
    () => portfolio.account ?? emptyAccount(accountId, startingCash),
    [accountId, portfolio.account, startingCash],
  );

  useEffect(() => {
    try {
      const raw = window.localStorage.getItem(DASHBOARD_SESSION_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as DashboardSession;
        if (parsed.userId) setSession(parsed);
      }
    } catch {
      window.localStorage.removeItem(DASHBOARD_SESSION_KEY);
    } finally {
      setAuthReady(true);
    }
  }, []);

  const rememberSession = useCallback((user: DashboardUser) => {
    const nextSession: DashboardSession = {
      userId: user.id,
      username: user.username ?? null,
      name: user.name,
    };
    window.localStorage.setItem(DASHBOARD_SESSION_KEY, JSON.stringify(nextSession));
    setSession(nextSession);
  }, []);

  const handleAuthenticated = useCallback(
    (response: DashboardAuthResponse) => {
      rememberSession(response.user);
      setSnapshot((current) => ({ ...current, user: response.user, mode: "live" }));
      setStatus(response.message);
    },
    [rememberSession],
  );

  const handleLogout = useCallback(() => {
    window.localStorage.removeItem(DASHBOARD_SESSION_KEY);
    setSession(null);
    setSnapshot(demoSnapshot);
    setSelectedId(demoSnapshot.selectedRecommendationId);
    setScanPayload(null);
    setStatus("Signed out.");
  }, []);

  const selectedRecommendation = useMemo(
    () => snapshot.recommendations.find((r) => r.id === selectedId) ?? null,
    [snapshot.recommendations, selectedId],
  );

  const handleAccountUpdated = useCallback(
    (updated: SimulationAccount) => {
      portfolio.setAccount(updated);
      storeAccount(updated);
    },
    [portfolio, storeAccount],
  );

  const applySnapshot = useCallback((live: DashboardSnapshot) => {
    setSnapshot(live);
    setSelectedId((current) => {
      if (current && live.recommendations.some((item) => item.id === current)) {
        return current;
      }
      return live.selectedRecommendationId ?? live.recommendations[0]?.id ?? null;
    });
    setStatus(live.mode === "live" ? "Live recommendations loaded." : "Live API unavailable; using demo fallback.");
  }, []);

  const refreshSnapshot = useCallback(async () => {
    if (!session?.userId) throw new Error("Login required.");
    const live = await fetchDashboardSnapshot(session.userId);
    applySnapshot(live);
    return live;
  }, [applySnapshot, session?.userId]);

  useEffect(() => {
    if (!session?.userId) return;
    let cancelled = false;
    void (async () => {
      try {
        const live = await fetchDashboardSnapshot(session.userId);
        if (cancelled) return;
        applySnapshot(live);
      } catch {
        if (!cancelled) setStatus("Live API unavailable; using demo fallback.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [applySnapshot, session?.userId]);

  const handleAlternative = useCallback(
    async (rec: DashboardRecommendation) => {
      setBusy("alternative");
      try {
        if (snapshot.mode === "live") {
          const result = await fetchNextAlternative(rec.id);
          if (result.status === "empty" || !result.recommendation) {
            setStatus(result.message);
            return;
          }
          const next = result.recommendation;
          setSnapshot((cur) => ({
            ...cur,
            recommendations: cur.recommendations.some((item) => item.id === next.id)
              ? cur.recommendations
              : [...cur.recommendations, next],
          }));
          setSelectedId(next.id);
          setStatus(`Loaded next backend alternative: ${next.ticker}.`);
        } else {
          const idx = snapshot.recommendations.findIndex((item) => item.id === rec.id);
          const next = snapshot.recommendations[idx + 1];
          setStatus(next ? `Switched to demo alternative: ${next.ticker}.` : "No more demo alternatives.");
          if (next) setSelectedId(next.id);
        }
      } finally {
        setBusy(null);
      }
    },
    [snapshot.mode, snapshot.recommendations],
  );

  const handleFeedback = useCallback(
    async (rec: DashboardRecommendation, action: "bought" | "skipped") => {
      setBusy(action);
      setSnapshot((cur) => ({
        ...cur,
        recommendations: cur.recommendations.map((item) =>
          item.id === rec.id ? { ...item, feedbackAction: action } : item,
        ),
      }));
      try {
        if (snapshot.mode === "live") await submitRecommendationFeedback(rec.id, action);
        setStatus(action === "bought" ? `${rec.ticker} feedback saved.` : `${rec.ticker} marked as skipped.`);
      } finally {
        setBusy(null);
      }
    },
    [snapshot.mode],
  );

  const configIssues = useMemo(() => {
    if (snapshot.mode !== "live") return [];
    const issues: { key: string; label: string }[] = [];
    if (snapshot.system.openRouterStatus !== "Configured")
      issues.push({ key: "openrouter", label: "OpenRouter key" });
    if (snapshot.system.alpacaStatus !== "Connected")
      issues.push({ key: "alpaca", label: "Alpaca key + secret" });
    return issues;
  }, [snapshot.mode, snapshot.system]);

  const handleRunScan = useCallback(async () => {
    if (!session?.userId) {
      setStatus("Login required.");
      return;
    }

    // Client-side preflight — only reliable when snapshot is live
    if (snapshot.mode === "live" && configIssues.length > 0) {
      const labels = configIssues.map((i) => i.label).join(", ");
      setStatus(`Scan blocked — missing: ${labels}. Add them in API Keys.`);
      setActiveNav("api-keys");
      return;
    }

    setScanPayload(buildScanPayloadPreview(snapshot, session.userId));
    setShowPipeline(true);
    const acctLabel = `$${snapshot.user.accountSize.toLocaleString()} account`;
    const riskLabel = snapshot.user.riskProfile;
    setStatus(`Starting scan — using ${acctLabel}, ${riskLabel} risk, ${snapshot.user.maxContracts} max contracts...`);
    try {
      const result = await runScan(session.userId);
      if (result.outcome === "success") {
        const live = await fetchDashboardSnapshot(session.userId);
        setSnapshot(live);
        setSelectedId(live.selectedRecommendationId ?? live.recommendations[0]?.id ?? null);
        setStatus(
          live.recommendations.length > 0
            ? `Scan complete — recommendations sized for ${acctLabel}.`
            : "Scan complete. No trade cleared the filters.",
        );
      } else if (result.outcome === "missing_config") {
        setStatus(result.error_message || "Missing configuration. Check API Keys.");
        setActiveNav("api-keys");
      } else if (result.outcome === "already_running") {
        setStatus("A scan is already running.");
      } else {
        setStatus(`Scan failed: ${result.error_message || "unknown error"}`);
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Failed to start scan.");
    }
  }, [session?.userId, snapshot, configIssues]);

  if (!authReady) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[#070a0f] text-sm text-[#8b949e]">
        Loading...
      </div>
    );
  }

  if (!session) {
    return <AuthPanel onAuthenticated={handleAuthenticated} />;
  }

  return (
    <div className="min-h-screen bg-[#070a0f] text-[#e2e4e9]">
      <header className="sticky top-0 z-40 border-b border-white/[0.06] bg-[#0b1018]/95 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-[1440px] items-center justify-between px-6">
          <div className="flex items-center gap-8">
            <div className="flex items-center gap-2.5">
              <div className="flex h-7 w-7 items-center justify-center rounded-md bg-[#2f81f7] text-xs font-bold text-white">
                EE
              </div>
              <span className="text-sm font-semibold tracking-tight">Earning Edge</span>
            </div>
            <div className="hidden items-center gap-6 text-xs md:flex">
              <TopStat label="Portfolio" value={formatCurrency(account.totalPortfolioValue)} highlight />
              <TopStat label="Buying Power" value={formatCurrency(account.buyingPower)} />
              <TopStat
                label="Unrealized"
                value={formatCurrency(account.unrealizedPnl)}
                valueClass={account.unrealizedPnl >= 0 ? "text-[#3fb950]" : "text-[#f85149]"}
              />
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="hidden text-xs font-medium text-[#c9d1d9] md:inline">
              {snapshot.user.name || session.name}
            </span>
            {portfolio.isPolling && <span className="text-[10px] text-[#8b949e]">Polling prices...</span>}
            {portfolio.lastUpdate && (
              <span className="hidden text-[10px] text-[#484f58] sm:inline">Last update: {portfolio.lastUpdate}</span>
            )}
            <button
              onClick={() => void portfolio.refresh()}
              className="rounded-md border border-white/[0.06] bg-[#21262d] px-3 py-1.5 text-xs font-medium text-[#c9d1d9] transition hover:bg-[#30363d] hover:text-white"
            >
              Refresh Prices
            </button>
            <div className="relative">
              {configIssues.length > 0 && (
                <span className="absolute -right-1 -top-1 h-2.5 w-2.5 rounded-full border-2 border-[#0b1018] bg-[#d29922]" />
              )}
              <button
                onClick={() => void handleRunScan()}
                title={
                  configIssues.length > 0
                    ? `Missing: ${configIssues.map((i) => i.label).join(", ")}`
                    : `Run scan — $${snapshot.user.accountSize.toLocaleString()} account, ${snapshot.user.riskProfile} risk`
                }
                className={`rounded-md px-4 py-1.5 text-sm font-medium text-white transition ${
                  configIssues.length > 0
                    ? "bg-[#9e6a03] hover:bg-[#b08800]"
                    : "bg-[#238636] hover:bg-[#2ea043]"
                }`}
              >
                Run Scan
              </button>
            </div>
            <button
              onClick={handleLogout}
              className="rounded-md border border-white/[0.06] bg-[#21262d] px-3 py-1.5 text-xs font-medium text-[#8b949e] transition hover:bg-[#30363d] hover:text-white"
            >
              Logout
            </button>
          </div>
        </div>
      </header>

      {snapshot.mode === "demo" && (
        <div className="mx-auto max-w-[1440px] px-6 pt-4">
          <div className="rounded-lg border border-[#f85149]/30 bg-[#f85149]/10 px-4 py-2.5 text-sm text-[#ff7b72]">
            <span className="font-semibold">Demo mode</span> — backend unavailable. These are sample recommendations, not real signals. Check your API key in Settings → API Keys, then click{" "}
            <span className="font-semibold">Run Scan</span>.
          </div>
        </div>
      )}

      {snapshot.mode === "live" && configIssues.length > 0 && (
        <div className="mx-auto max-w-[1440px] px-6 pt-4">
          <div className="flex items-center justify-between rounded-lg border border-[#d29922]/30 bg-[#d29922]/10 px-4 py-2.5 text-sm text-[#e3b341]">
            <span>
              <span className="font-semibold">API keys incomplete</span> — scan will be blocked until configured.{" "}
              Missing: <span className="font-semibold">{configIssues.map((i) => i.label).join(", ")}</span>.{" "}
              These are required for Alpaca option chain data and LLM analysis, same as the Telegram bot.
            </span>
            <button
              onClick={() => setActiveNav("api-keys")}
              className="ml-4 shrink-0 rounded border border-[#d29922]/30 bg-[#d29922]/10 px-3 py-1 text-xs font-medium text-[#e3b341] transition hover:bg-[#d29922]/20"
            >
              Configure API Keys
            </button>
          </div>
        </div>
      )}

      {account.notifications.length > 0 && (
        <div className="mx-auto flex max-w-[1440px] flex-col gap-2 px-6 pt-4">
          {account.notifications.slice(0, 3).map((notification) => (
            <div
              key={notification.id}
              className={`rounded-lg border px-4 py-2.5 text-sm ${
                notification.type === "SUCCESS"
                  ? "border-[#238636]/20 bg-[#238636]/10 text-[#b7f7c2]"
                  : notification.type === "WARNING"
                    ? "border-[#f85149]/20 bg-[#f85149]/10 text-[#ffb3ad]"
                    : "border-[#2f81f7]/20 bg-[#2f81f7]/10 text-[#b6dcff]"
              }`}
            >
              {notification.message}
            </div>
          ))}
        </div>
      )}

      <div className="mx-auto flex max-w-[1440px]">
        <Sidebar
          active={activeNav}
          onNavigate={setActiveNav}
          equity={account.totalPortfolioValue}
          availableCapital={account.buyingPower}
          unrealizedPnl={account.unrealizedPnl}
          openCount={account.openPositions.length}
          mode={snapshot.mode}
        />

        <main className="min-w-0 flex-1 p-6">
          {(status || portfolio.error) && (
            <div className="mb-5 flex items-center gap-2 text-xs text-[#8b949e]">
              <div className="h-1.5 w-1.5 rounded-full bg-[#3fb950]" />
              {portfolio.error ?? status}
            </div>
          )}

          {activeNav === "signal" && (
            <SignalPanel
              snapshot={snapshot}
              selectedId={selectedId}
              account={account}
              onSelect={setSelectedId}
              onWhy={() => setBusy("why")}
              onRisk={() => setBusy("risk")}
              onSaveNote={() => setBusy("save-note")}
              onAlternative={handleAlternative}
              onFeedback={handleFeedback}
              onAccountUpdated={handleAccountUpdated}
              onStatus={setStatus}
              busy={busy}
            />
          )}
          {activeNav === "paper" && (
            <PaperPanel
              account={account}
              selectedRecommendation={selectedRecommendation}
              onAccountUpdated={handleAccountUpdated}
              onStatus={setStatus}
            />
          )}
          {activeNav === "runs" && <RunsPanel runs={snapshot.recentRuns} />}
          {activeNav === "schedule" && <SchedulePanel schedules={snapshot.schedules} />}
          {activeNav === "settings" && (
            <SettingsPanel
              snapshot={snapshot}
              userId={session.userId}
              onStatus={setStatus}
              onRefresh={refreshSnapshot}
            />
          )}
          {activeNav === "api-keys" && (
            <ApiKeysPanel
              system={snapshot.system}
              userId={session.userId}
              onStatus={setStatus}
              onRefresh={refreshSnapshot}
            />
          )}
          {activeNav === "logs" && <LogsPanel />}
        </main>
      </div>

      <PipelineViz
        isOpen={showPipeline}
        onClose={() => setShowPipeline(false)}
        recommendations={snapshot.recommendations}
        scanPayload={scanPayload}
        onSelectRecommendation={(id) => {
          setSelectedId(id);
          setActiveNav("signal");
        }}
      />
    </div>
  );
}

function TopStat({
  label,
  value,
  valueClass,
  highlight,
}: {
  label: string;
  value: string;
  valueClass?: string;
  highlight?: boolean;
}) {
  return (
    <div>
      <div className="text-[10px] font-semibold uppercase tracking-wider text-[#8b949e]">{label}</div>
      <div className={`text-sm font-semibold ${valueClass ?? ""} ${highlight ? "text-[#58a6ff]" : ""}`}>
        {value}
      </div>
    </div>
  );
}

function buildScanPayloadPreview(
  snapshot: DashboardSnapshot,
  userId: string,
): ScanPayloadPreview {
  return {
    requestedAt: new Date().toISOString(),
    apiRequest: {
      method: "POST",
      endpoint: "/api/dashboard/run-scan",
      query: { user_id: userId },
      body: null,
    },
    userCriteria: {
      userId,
      accountSize: snapshot.user.accountSize,
      riskProfile: snapshot.user.riskProfile,
      timezone: snapshot.user.timezone,
      timezoneLabel: snapshot.user.timezoneLabel,
      broker: snapshot.user.broker,
      strategyPermission: snapshot.user.strategyPermission,
      maxContracts: snapshot.user.maxContracts,
    },
    screenerCriteria: {
      provider: "Finviz",
      url: "https://finviz.com/screener?v=111&f=earningsdate_nextweek,geo_usa&o=-marketcap",
      filters: [
        "Upcoming earnings date = Next week",
        "Country = USA",
        "Sort = market cap descending",
        "Use top five visible rows",
      ],
      sort: "marketcap descending",
      visibleRows: 5,
      retryPolicy: [
        "Retry Finviz page once",
        "Retry with a clean browser context",
        "Use backup earnings data if Finviz remains unavailable",
      ],
    },
    providerCriteria: {
      openRouter: `${snapshot.system.openRouterStatus}${
        snapshot.system.openRouterKeyDisplay ? ` (${snapshot.system.openRouterKeyDisplay})` : ""
      }`,
      alpaca: `${snapshot.system.alpacaStatus}${
        snapshot.system.alpacaKeyDisplay ? ` (${snapshot.system.alpacaKeyDisplay})` : ""
      }`,
      alphaVantage: `${snapshot.system.alphaVantageStatus}${
        snapshot.system.alphaVantageKeyDisplay ? ` (${snapshot.system.alphaVantageKeyDisplay})` : ""
      }`,
      heavyModel: snapshot.system.heavyModel,
      lightModel: snapshot.system.lightModel,
      marketDataFallback: "Yahoo Finance fallback is available for market/options data.",
      pipelineReports: "Generated after the run finishes in the dashboard snapshot.",
    },
    decisionCriteria: {
      actionBands: "Recommend >= 68; watchlist 60-67; no trade < 60.",
      watchlistSizing: "Watchlist decisions persist the setup with suggested quantity 0.",
      sizingInputs: `Account size ${snapshot.user.accountSize}, risk profile ${snapshot.user.riskProfile}, max contracts ${snapshot.user.maxContracts}.`,
      strategyPermission: snapshot.user.strategyPermission,
      finalSelection: "Pick exactly one ticker and one matching option contract, or no trade.",
    },
  };
}

function emptyAccount(id: string, startingCash: number): SimulationAccount {
  return {
    id,
    startingCash,
    cashBalance: startingCash,
    openPositions: [],
    closedPositions: [],
    orders: [],
    realizedPnl: 0,
    unrealizedPnl: 0,
    totalPortfolioValue: startingCash,
    buyingPower: startingCash,
    notifications: [],
    updatedAt: new Date().toISOString(),
  };
}

function roundMoney(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function formatCurrency(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}
