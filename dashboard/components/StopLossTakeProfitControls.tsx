"use client";

import { useState } from "react";
import { updateSimulationPositionRisk } from "@/lib/api";
import { type SimulationAccount, type SimulationPosition } from "@/types/simulation";

export function StopLossTakeProfitControls({
  position,
  onAccountUpdated,
}: {
  position: SimulationPosition;
  onAccountUpdated: (account: SimulationAccount) => void;
}) {
  const [stopLoss, setStopLoss] = useState(position.stopLoss?.toString() ?? "");
  const [takeProfit, setTakeProfit] = useState(position.takeProfit?.toString() ?? "");
  const [isSaving, setIsSaving] = useState(false);

  async function save() {
    setIsSaving(true);
    try {
      onAccountUpdated(
        await updateSimulationPositionRisk(position.id, {
          stopLoss: stopLoss ? Number(stopLoss) : null,
          takeProfit: takeProfit ? Number(takeProfit) : null,
        }),
      );
    } finally {
      setIsSaving(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      <input
        type="number"
        step="0.01"
        value={stopLoss}
        onChange={(event) => setStopLoss(event.target.value)}
        placeholder="Stop"
        className="w-20 rounded-md border border-white/[0.08] bg-[#060a12] px-2 py-1.5 text-xs text-white placeholder:text-[#484f58]"
      />
      <input
        type="number"
        step="0.01"
        value={takeProfit}
        onChange={(event) => setTakeProfit(event.target.value)}
        placeholder="Target"
        className="w-20 rounded-md border border-white/[0.08] bg-[#060a12] px-2 py-1.5 text-xs text-white placeholder:text-[#484f58]"
      />
      <button
        onClick={() => void save()}
        disabled={isSaving}
        className="rounded-md border border-white/[0.08] bg-[#21262d] px-2.5 py-1.5 text-xs font-semibold text-[#c9d1d9] transition hover:bg-[#30363d] hover:text-white disabled:opacity-50"
      >
        {isSaving ? "Saving" : "Save"}
      </button>
    </div>
  );
}
