"use client";

import { calculateBreakeven } from "@/utils/options/calculateBreakeven";
import { calculateMaxLoss, maxLossText } from "@/utils/options/calculateMaxLoss";
import { calculateMaxProfit, maxProfitText } from "@/utils/options/calculateMaxProfit";
import type { OptionSide, OptionType } from "@/utils/options/calculateOptionPnL";

function Row({ label, value, tone }: { label: string; value: string; tone?: "warn" | "ok" | "neutral" }) {
  const valColor =
    tone === "warn"
      ? "text-[#f85149]"
      : tone === "ok"
        ? "text-[#3fb950]"
        : "text-white";
  return (
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-xs text-[#8b949e]">{label}</span>
      <span className={`text-xs font-semibold tabular-nums ${valColor}`}>{value}</span>
    </div>
  );
}

export function RiskRewardCard({
  optionType,
  side,
  strike,
  premium,
  quantity = 1,
  multiplier = 100,
  currentOptionPrice,
}: {
  optionType: OptionType;
  side: OptionSide;
  strike: number;
  premium: number;
  quantity?: number;
  multiplier?: number;
  currentOptionPrice?: number | null;
}) {
  const maxLoss = calculateMaxLoss(optionType, side, strike, premium, quantity, multiplier);
  const maxProfit = calculateMaxProfit(optionType, side, strike, premium, quantity, multiplier);
  const breakeven = calculateBreakeven(optionType, side, strike, premium);

  const isShort = side === "SHORT";
  const optionLabel = `${side === "LONG" ? "Buy" : "Short"} ${optionType === "CALL" ? "Call" : "Put"}`;

  return (
    <div className="rounded-xl border border-white/[0.06] bg-[#0d1624] p-4">
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <span className="text-[11px] font-semibold uppercase tracking-widest text-[#58a6ff]">
          Risk / Reward
        </span>
        <span
          className={`rounded border px-1.5 py-0.5 text-[10px] font-semibold ${
            side === "LONG"
              ? "border-[#238636]/30 bg-[#238636]/10 text-[#3fb950]"
              : "border-[#f85149]/30 bg-[#f85149]/10 text-[#f85149]"
          }`}
        >
          {optionLabel}
        </span>
      </div>

      <div className="divide-y divide-white/[0.04]">
        <Row label="Breakeven" value={`$${breakeven.toFixed(2)}`} />
        <Row
          label="Max Loss"
          value={maxLossText(maxLoss)}
          tone={maxLoss.isUnlimited ? "warn" : "neutral"}
        />
        <Row
          label="Max Profit"
          value={maxProfitText(maxProfit)}
          tone={maxProfit.isUnlimited ? "ok" : "neutral"}
        />
        <Row
          label="Entry Premium"
          value={`$${premium.toFixed(4)} × ${quantity} × ${multiplier}`}
        />
        <Row
          label="Entry Cost / Credit"
          value={`$${(premium * quantity * multiplier).toFixed(2)}`}
          tone={side === "SHORT" ? "ok" : "neutral"}
        />
        {currentOptionPrice != null && (
          <Row
            label="Current Mark"
            value={`$${currentOptionPrice.toFixed(4)}`}
          />
        )}
      </div>

      {isShort && (
        <div className="mt-3 rounded border border-[#f85149]/20 bg-[#f85149]/5 px-3 py-2 text-[11px] text-[#f85149]">
          Short options carry {optionType === "CALL" ? "unlimited" : "large"} downside risk. This is simulation only.
        </div>
      )}
    </div>
  );
}
