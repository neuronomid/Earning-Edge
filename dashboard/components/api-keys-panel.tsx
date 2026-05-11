"use client";

import { useEffect, useState } from "react";
import { type DashboardSystem } from "@/lib/dashboard-data";
import {
  removeAlpacaCredentials,
  removeOpenRouterKey,
  removeAlphaVantageKey,
  updateAlpacaCredentials,
  updateAlphaVantageKey,
  updateOpenRouterKey,
} from "@/lib/api";

function maskApiKey(value: string): string {
  const cleaned = value.trim();
  if (!cleaned) return "";
  const suffix = cleaned.length > 4 ? cleaned.slice(-4) : cleaned;
  const prefix = cleaned.startsWith("sk-")
    ? cleaned.slice(0, 8)
    : cleaned.length > 8
      ? cleaned.slice(0, 4)
      : "";
  return `${prefix}...${suffix}`;
}

export function ApiKeysPanel({
  system,
  userId,
  onStatus,
  onRefresh,
}: {
  system: DashboardSystem;
  userId?: string;
  onStatus?: (message: string) => void;
  onRefresh?: () => Promise<unknown>;
}) {
  const [keys, setKeys] = useState({
    openrouter: "",
    alpacaKey: "",
    alpacaSecret: "",
    alphaVantage: "",
  });
  const [busy, setBusy] = useState<string | null>(null);

  // Saved displays: initialise from backend, then update locally on save/remove
  const [savedDisplays, setSavedDisplays] = useState({
    openrouter: system.openRouterKeyDisplay ?? (system.openRouterStatus === "Configured" ? "key configured" : null),
    alpacaKey: system.alpacaKeyDisplay ?? (system.alpacaStatus === "Connected" ? "key on file" : null),
    alpacaSecret: system.alpacaSecretDisplay ?? (system.alpacaStatus === "Connected" ? "secret on file" : null),
    alpacaConnected: system.alpacaStatus === "Connected",
    alphaVantage: system.alphaVantageKeyDisplay ?? (system.alphaVantageStatus === "Connected" ? "key on file" : null),
  });

  // Sync whenever the parent refreshes the snapshot
  useEffect(() => {
    setSavedDisplays({
      openrouter: system.openRouterKeyDisplay ?? (system.openRouterStatus === "Configured" ? "key configured" : null),
      alpacaKey: system.alpacaKeyDisplay ?? (system.alpacaStatus === "Connected" ? "key on file" : null),
      alpacaSecret: system.alpacaSecretDisplay ?? (system.alpacaStatus === "Connected" ? "secret on file" : null),
      alpacaConnected: system.alpacaStatus === "Connected",
      alphaVantage: system.alphaVantageKeyDisplay ?? (system.alphaVantageStatus === "Connected" ? "key on file" : null),
    });
  }, [system]);

  async function handleOpenRouterSave() {
    if (!keys.openrouter.trim()) {
      onStatus?.("Enter an OpenRouter key before saving.");
      return;
    }
    setBusy("openrouter");
    try {
      const result = await updateOpenRouterKey(keys.openrouter.trim(), userId);
      const masked = maskApiKey(keys.openrouter.trim());
      setSavedDisplays((prev) => ({ ...prev, openrouter: masked }));
      setKeys((current) => ({ ...current, openrouter: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to update the OpenRouter key.");
    } finally {
      setBusy(null);
    }
  }

  async function handleAlpacaSave() {
    if (!keys.alpacaKey.trim() || !keys.alpacaSecret.trim()) {
      onStatus?.("Enter both the Alpaca key and secret before saving.");
      return;
    }
    setBusy("alpaca");
    try {
      const result = await updateAlpacaCredentials(
        keys.alpacaKey.trim(),
        keys.alpacaSecret.trim(),
        userId,
      );
      const maskedKey = maskApiKey(keys.alpacaKey.trim());
      const maskedSecret = maskApiKey(keys.alpacaSecret.trim());
      setSavedDisplays((prev) => ({ ...prev, alpacaKey: maskedKey, alpacaSecret: maskedSecret, alpacaConnected: true }));
      setKeys((current) => ({ ...current, alpacaKey: "", alpacaSecret: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to update Alpaca credentials.");
    } finally {
      setBusy(null);
    }
  }

  async function handleOpenRouterRemove() {
    setBusy("openrouter-remove");
    try {
      const result = await removeOpenRouterKey(userId);
      setSavedDisplays((prev) => ({ ...prev, openrouter: null }));
      setKeys((current) => ({ ...current, openrouter: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to remove the OpenRouter key.");
    } finally {
      setBusy(null);
    }
  }

  async function handleAlpacaRemove() {
    setBusy("alpaca-remove");
    try {
      const result = await removeAlpacaCredentials(userId);
      setSavedDisplays((prev) => ({ ...prev, alpacaKey: null, alpacaSecret: null, alpacaConnected: false }));
      setKeys((current) => ({ ...current, alpacaKey: "", alpacaSecret: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to remove Alpaca credentials.");
    } finally {
      setBusy(null);
    }
  }

  async function handleAlphaVantageSave() {
    if (!keys.alphaVantage.trim()) {
      onStatus?.("Enter an Alpha Vantage key before saving.");
      return;
    }
    setBusy("alpha-vantage");
    try {
      const result = await updateAlphaVantageKey(keys.alphaVantage.trim(), userId);
      const masked = maskApiKey(keys.alphaVantage.trim());
      setSavedDisplays((prev) => ({ ...prev, alphaVantage: masked }));
      setKeys((current) => ({ ...current, alphaVantage: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to update the Alpha Vantage key.");
    } finally {
      setBusy(null);
    }
  }

  async function handleAlphaVantageRemove() {
    setBusy("alpha-vantage-remove");
    try {
      const result = await removeAlphaVantageKey(userId);
      setSavedDisplays((prev) => ({ ...prev, alphaVantage: null }));
      setKeys((current) => ({ ...current, alphaVantage: "" }));
      await onRefresh?.();
      onStatus?.(result.message);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to remove the Alpha Vantage key.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <h2 className="text-base font-semibold text-white">API Keys</h2>

      {/* OpenRouter */}
      <div className="rounded-md border border-white/[0.06] bg-[#161b22] p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-medium text-white">OpenRouter</div>
            <div className="text-xs text-[#8b949e]">Required for LLM analysis</div>
          </div>
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-medium ${
              savedDisplays.openrouter
                ? "bg-[#238636]/10 text-[#3fb950]"
                : "bg-[#d29922]/10 text-[#e3b341]"
            }`}
          >
            {savedDisplays.openrouter ? "Set" : "Missing"}
          </span>
        </div>
        {savedDisplays.openrouter && !keys.openrouter && (
          <div className="mb-2 flex items-center gap-2 rounded bg-[#238636]/10 border border-[#238636]/20 px-3 py-1.5">
            <span className="text-[10px] text-[#3fb950] font-semibold uppercase tracking-wide">Saved</span>
            <span className="text-xs font-mono text-[#c9d1d9]">{savedDisplays.openrouter}</span>
          </div>
        )}
        <input
          type="password"
          placeholder="sk-or-..."
          className="w-full bg-[#0d1016] border border-white/[0.06] rounded px-3 py-2 text-sm text-white mb-2"
          value={keys.openrouter}
          disabled={busy !== null}
          onChange={(e) => setKeys((k) => ({ ...k, openrouter: e.target.value }))}
        />
        <div className="flex gap-2">
          <button
            onClick={() => void handleOpenRouterSave()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#238636]/10 text-[#3fb950] text-xs font-medium border border-[#238636]/20 hover:bg-[#238636]/20 transition-colors disabled:opacity-50"
          >
            {busy === "openrouter" ? "Saving..." : "Update OpenRouter Key"}
          </button>
          <button
            onClick={() => void handleOpenRouterRemove()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#21262d] text-[#8b949e] text-xs font-medium border border-white/[0.06] hover:bg-[#30363d] hover:text-white transition-colors disabled:opacity-50"
          >
            {busy === "openrouter-remove" ? "Removing..." : "Remove"}
          </button>
        </div>
      </div>

      {/* Alpaca */}
      <div className="rounded-md border border-white/[0.06] bg-[#161b22] p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-medium text-white">Alpaca</div>
            <div className="text-xs text-[#8b949e]">Option chain data</div>
          </div>
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-medium ${
              savedDisplays.alpacaConnected
                ? "bg-[#238636]/10 text-[#3fb950]"
                : "bg-[#d29922]/10 text-[#e3b341]"
            }`}
          >
            {savedDisplays.alpacaConnected ? "Connected" : "Not set"}
          </span>
        </div>
        {savedDisplays.alpacaConnected && !keys.alpacaKey && (
          <div className="mb-2 flex items-center gap-2 rounded bg-[#238636]/10 border border-[#238636]/20 px-3 py-1.5">
            <span className="text-[10px] text-[#3fb950] font-semibold uppercase tracking-wide">Saved</span>
            <span className="text-xs font-mono text-[#c9d1d9]">
              {savedDisplays.alpacaKey ?? "key + secret on file"}
            </span>
          </div>
        )}
        <input
          type="password"
          placeholder="Alpaca API Key"
          className="w-full bg-[#0d1016] border border-white/[0.06] rounded px-3 py-2 text-sm text-white mb-2"
          value={keys.alpacaKey}
          disabled={busy !== null}
          onChange={(e) => setKeys((k) => ({ ...k, alpacaKey: e.target.value }))}
        />
        {savedDisplays.alpacaSecret && !keys.alpacaSecret && (
          <div className="mb-2 flex items-center gap-2 rounded bg-[#238636]/10 border border-[#238636]/20 px-3 py-1.5">
            <span className="text-[10px] text-[#3fb950] font-semibold uppercase tracking-wide">Saved secret</span>
            <span className="text-xs font-mono text-[#c9d1d9]">{savedDisplays.alpacaSecret}</span>
          </div>
        )}
        <input
          type="password"
          placeholder="Alpaca API Secret"
          className="w-full bg-[#0d1016] border border-white/[0.06] rounded px-3 py-2 text-sm text-white mb-2"
          value={keys.alpacaSecret}
          disabled={busy !== null}
          onChange={(e) => setKeys((k) => ({ ...k, alpacaSecret: e.target.value }))}
        />
        <div className="flex gap-2">
          <button
            onClick={() => void handleAlpacaSave()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#238636]/10 text-[#3fb950] text-xs font-medium border border-[#238636]/20 hover:bg-[#238636]/20 transition-colors disabled:opacity-50"
          >
            {busy === "alpaca" ? "Saving..." : "Update Alpaca"}
          </button>
          <button
            onClick={() => void handleAlpacaRemove()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#21262d] text-[#8b949e] text-xs font-medium border border-white/[0.06] hover:bg-[#30363d] hover:text-white transition-colors disabled:opacity-50"
          >
            {busy === "alpaca-remove" ? "Removing..." : "Remove"}
          </button>
        </div>
      </div>

      {/* Alpha Vantage */}
      <div className="rounded-md border border-white/[0.06] bg-[#161b22] p-4">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-sm font-medium text-white">Alpha Vantage</div>
            <div className="text-xs text-[#8b949e]">Market data</div>
          </div>
          <span
            className={`text-[10px] px-2 py-0.5 rounded font-medium ${
              savedDisplays.alphaVantage
                ? "bg-[#238636]/10 text-[#3fb950]"
                : "bg-[#d29922]/10 text-[#e3b341]"
            }`}
          >
            {savedDisplays.alphaVantage ? "Connected" : "Not set"}
          </span>
        </div>
        {savedDisplays.alphaVantage && !keys.alphaVantage && (
          <div className="mb-2 flex items-center gap-2 rounded bg-[#238636]/10 border border-[#238636]/20 px-3 py-1.5">
            <span className="text-[10px] text-[#3fb950] font-semibold uppercase tracking-wide">Saved</span>
            <span className="text-xs font-mono text-[#c9d1d9]">{savedDisplays.alphaVantage}</span>
          </div>
        )}
        <input
          type="password"
          placeholder="Alpha Vantage API Key"
          className="w-full bg-[#0d1016] border border-white/[0.06] rounded px-3 py-2 text-sm text-white mb-2"
          value={keys.alphaVantage}
          disabled={busy !== null}
          onChange={(e) => setKeys((k) => ({ ...k, alphaVantage: e.target.value }))}
        />
        <div className="flex gap-2">
          <button
            onClick={() => void handleAlphaVantageSave()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#238636]/10 text-[#3fb950] text-xs font-medium border border-[#238636]/20 hover:bg-[#238636]/20 transition-colors disabled:opacity-50"
          >
            {busy === "alpha-vantage" ? "Saving..." : "Update Alpha Vantage"}
          </button>
          <button
            onClick={() => void handleAlphaVantageRemove()}
            disabled={busy !== null}
            className="px-4 py-2 rounded bg-[#21262d] text-[#8b949e] text-xs font-medium border border-white/[0.06] hover:bg-[#30363d] hover:text-white transition-colors disabled:opacity-50"
          >
            {busy === "alpha-vantage-remove" ? "Removing..." : "Remove"}
          </button>
        </div>
      </div>

      <div className="text-xs text-[#484f58]">
        API keys are validated against each provider before saving and stored encrypted.
      </div>
    </div>
  );
}
