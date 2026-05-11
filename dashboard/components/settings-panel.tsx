"use client";

import { useMemo, useState } from "react";
import { updateDashboardSettings, type DashboardSettingsUpdate } from "@/lib/api";
import { type DashboardSnapshot } from "@/lib/dashboard-data";

type FieldKey = keyof DashboardSettingsUpdate;

type FieldConfig = {
  key: FieldKey;
  label: string;
  displayValue: string;
  editValue: string;
  type: "number" | "text" | "select";
  options?: { label: string; value: string }[];
};

const TIMEZONE_OPTIONS = [
  { label: "Pacific (PT)", value: "PT" },
  { label: "Mountain (MT)", value: "MT" },
  { label: "Central (CT)", value: "CT" },
  { label: "Eastern (ET)", value: "ET" },
  { label: "Atlantic (AT)", value: "AT" },
  { label: "Newfoundland (NT)", value: "NT" },
];

export function SettingsPanel({
  snapshot,
  userId,
  onStatus,
  onRefresh,
}: {
  snapshot: DashboardSnapshot;
  userId?: string;
  onStatus?: (message: string) => void;
  onRefresh?: () => Promise<unknown>;
}) {
  const user = snapshot.user;
  const [editing, setEditing] = useState<FieldKey | null>(null);
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState<FieldKey | null>(null);

  const fields = useMemo<FieldConfig[]>(
    () => [
      {
        key: "accountSize",
        label: "Account Size",
        displayValue: `$${user.accountSize.toLocaleString()}`,
        editValue: String(user.accountSize),
        type: "number",
      },
      {
        key: "riskProfile",
        label: "Risk Profile",
        displayValue: user.riskProfile,
        editValue: user.riskProfile,
        type: "select",
        options: [
          { label: "Conservative", value: "Conservative" },
          { label: "Balanced", value: "Balanced" },
          { label: "Aggressive", value: "Aggressive" },
        ],
      },
      {
        key: "timezoneLabel",
        label: "Timezone",
        displayValue: user.timezone,
        editValue: user.timezoneLabel,
        type: "select",
        options: TIMEZONE_OPTIONS,
      },
      {
        key: "broker",
        label: "Broker",
        displayValue: user.broker,
        editValue: user.broker,
        type: "text",
      },
      {
        key: "strategyPermission",
        label: "Strategy Permission",
        displayValue: user.strategyPermission,
        editValue: user.strategyPermission,
        type: "select",
        options: [
          { label: "Long", value: "long" },
          { label: "Short", value: "short" },
          { label: "Long and short", value: "long_and_short" },
        ],
      },
      {
        key: "maxContracts",
        label: "Max Contracts",
        displayValue: String(user.maxContracts),
        editValue: String(user.maxContracts),
        type: "number",
      },
    ],
    [user],
  );

  async function handleSave(field: FieldConfig) {
    setBusy(field.key);
    try {
      const payload = buildPayload(field.key, value);
      await updateDashboardSettings(payload, userId);
      await onRefresh?.();
      if (field.key === "accountSize") {
        const parsed = Number(value);
        onStatus?.(
          `Account size saved — paper simulator will reset to $${parsed.toLocaleString()}. Run Scan to apply new position sizing.`,
        );
      } else {
        onStatus?.("Settings saved.");
      }
      setEditing(null);
    } catch (error) {
      onStatus?.(error instanceof Error ? error.message : "Failed to save settings.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-5">
      <h2 className="text-base font-semibold text-white">Settings</h2>
      <div className="flex max-w-xl flex-col gap-2">
        {fields.map((field) => (
          <div
            key={field.key}
            className="flex items-center justify-between rounded-md border border-white/[0.06] bg-[#161b22] p-4"
          >
            <div>
              <div className="text-[11px] font-medium uppercase tracking-wide text-[#8b949e]">
                {field.label}
              </div>
              {editing === field.key ? (
                field.type === "select" && field.options ? (
                  <select
                    className="mt-1 rounded border border-white/[0.06] bg-[#0d1016] px-2 py-1 text-sm text-white"
                    value={value}
                    disabled={busy !== null}
                    onChange={(event) => setValue(event.target.value)}
                  >
                    {field.options.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type={field.type}
                    className="mt-1 w-48 rounded border border-white/[0.06] bg-[#0d1016] px-2 py-1 text-sm text-white"
                    value={value}
                    min={field.key === "maxContracts" ? 1 : undefined}
                    step={field.key === "accountSize" ? 1000 : 1}
                    disabled={busy !== null}
                    onChange={(event) => setValue(event.target.value)}
                  />
                )
              ) : (
                <div className="mt-0.5 text-sm font-medium text-white">{field.displayValue}</div>
              )}
            </div>
            {editing === field.key ? (
              <div className="flex gap-2">
                <button
                  onClick={() => void handleSave(field)}
                  disabled={busy !== null}
                  className="rounded border border-[#238636]/20 bg-[#238636]/10 px-3 py-1.5 text-xs font-medium text-[#3fb950] transition-colors hover:bg-[#238636]/20 disabled:opacity-50"
                >
                  {busy === field.key ? "Saving..." : "Save"}
                </button>
                <button
                  onClick={() => setEditing(null)}
                  disabled={busy !== null}
                  className="rounded border border-white/[0.06] bg-[#21262d] px-3 py-1.5 text-xs font-medium text-[#8b949e] transition-colors hover:bg-[#30363d] disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <button
                onClick={() => {
                  setEditing(field.key);
                  setValue(field.editValue);
                }}
                className="rounded border border-white/[0.06] bg-[#21262d] px-3 py-1.5 text-xs font-medium text-[#8b949e] transition-colors hover:bg-[#30363d] hover:text-white"
              >
                Edit
              </button>
            )}
          </div>
        ))}
      </div>
      <div className="flex flex-col gap-1 text-xs text-[#484f58]">
        <span>Settings are saved instantly and used by the next Run Scan.</span>
        <span>
          <span className="text-[#8b949e]">Account Size</span> controls position sizing in recommendations and resets the paper simulator balance when no trades are open.
        </span>
      </div>
    </div>
  );
}

function buildPayload(key: FieldKey, rawValue: string): DashboardSettingsUpdate {
  if (key === "accountSize") {
    const accountSize = Number(rawValue);
    if (!Number.isFinite(accountSize) || accountSize <= 0) {
      throw new Error("Account size must be greater than zero.");
    }
    return { accountSize };
  }

  if (key === "maxContracts") {
    const maxContracts = Number.parseInt(rawValue, 10);
    if (!Number.isFinite(maxContracts) || maxContracts < 1) {
      throw new Error("Max contracts must be at least 1.");
    }
    return { maxContracts };
  }

  if (key === "broker") {
    const broker = rawValue.trim();
    if (!broker) throw new Error("Broker cannot be empty.");
    return { broker };
  }

  if (key === "riskProfile") return { riskProfile: rawValue };
  if (key === "timezoneLabel") return { timezoneLabel: rawValue };
  if (key === "strategyPermission") return { strategyPermission: rawValue };

  return {};
}
