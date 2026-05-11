"use client";

import { useMemo, useState } from "react";
import { type DashboardRecommendation } from "@/lib/dashboard-data";
import { formatCurrency, formatDate } from "@/lib/formatters";
import { placeSimulationOrder } from "@/lib/api";
import { recommendationToContract } from "@/lib/simulation/recommendationContract";
import { calculateOrderRisk } from "@/lib/simulation/riskCalculationService";
import { optionContractId } from "@/lib/simulation/pricingUtils";
import {
  type OptionStrategy,
  type OrderSide,
  type OrderType,
  type SimulationAccount,
} from "@/types/simulation";
import { type OptionType } from "@/types/option";

type StrategyConfig = {
  side: OrderSide;
  optionType: OptionType;
  action: string;
  buttonLabel: string;
  isDebit: boolean;
  direction: string;
  riskNote: string;
  profitNote: string;
  shortWarning: string | null;
};

function strategyConfig(strategy: OptionStrategy): StrategyConfig {
  switch (strategy) {
    case "BUY_CALL":
      return {
        side: "BUY",
        optionType: "CALL",
        action: "Buy to Open",
        buttonLabel: "Simulate Buy Call",
        isDebit: true,
        direction: "Bullish",
        riskNote: "Risk limited to premium paid",
        profitNote: "Unlimited upside potential",
        shortWarning: null,
      };
    case "BUY_PUT":
      return {
        side: "BUY",
        optionType: "PUT",
        action: "Buy to Open",
        buttonLabel: "Simulate Buy Put",
        isDebit: true,
        direction: "Bearish",
        riskNote: "Risk limited to premium paid",
        profitNote: "Max profit = (strike − premium) × contracts × 100",
        shortWarning: null,
      };
    case "SHORT_CALL":
      return {
        side: "SELL",
        optionType: "CALL",
        action: "Sell to Open",
        buttonLabel: "Simulate Short Call",
        isDebit: false,
        direction: "Bearish / Neutral",
        riskNote: "Unlimited loss if underlying rises above strike",
        profitNote: "Max profit = premium received",
        shortWarning:
          "Short calls carry unlimited max loss. Buying power is reserved as margin approximation.",
      };
    case "SHORT_PUT":
      return {
        side: "SELL",
        optionType: "PUT",
        action: "Sell to Open",
        buttonLabel: "Simulate Short Put",
        isDebit: false,
        direction: "Bullish / Neutral",
        riskNote: "Large loss if underlying falls sharply toward zero",
        profitNote: "Max profit = premium received",
        shortWarning:
          "Short puts carry large downside risk. Buying power is reserved as margin approximation.",
      };
  }
}

function defaultStrategy(rec: DashboardRecommendation): OptionStrategy {
  const type = rec.optionType.toUpperCase();
  const side = rec.positionSide.toUpperCase();
  if (type === "CALL" && side === "LONG") return "BUY_CALL";
  if (type === "PUT" && side === "LONG") return "BUY_PUT";
  if (type === "CALL" && side === "SHORT") return "SHORT_CALL";
  if (type === "PUT" && side === "SHORT") return "SHORT_PUT";
  return "BUY_CALL";
}

const STRATEGY_BUTTONS: { label: string; value: OptionStrategy }[] = [
  { label: "Buy Call", value: "BUY_CALL" },
  { label: "Buy Put", value: "BUY_PUT" },
  { label: "Short Call", value: "SHORT_CALL" },
  { label: "Short Put", value: "SHORT_PUT" },
];

export function OptionOrderTicket({
  recommendation,
  account,
  onAccountUpdated,
  onStatus,
}: {
  recommendation: DashboardRecommendation;
  account: SimulationAccount;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
}) {
  const [strategy, setStrategy] = useState<OptionStrategy>(() =>
    defaultStrategy(recommendation),
  );
  const [orderType, setOrderType] = useState<OrderType>("MARKET");
  const [quantity, setQuantity] = useState(
    String(Math.max(1, recommendation.suggestedQuantity || 1)),
  );
  const [limitPrice, setLimitPrice] = useState("");
  const [stopLoss, setStopLoss] = useState("");
  const [takeProfit, setTakeProfit] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const cfg = strategyConfig(strategy);
  const baseContract = useMemo(
    () => recommendationToContract(recommendation),
    [recommendation],
  );

  const contract = useMemo(() => {
    if (cfg.optionType === baseContract.optionType) return baseContract;
    const newContractId = optionContractId({
      recommendationId: recommendation.id,
      symbol: recommendation.ticker,
      optionType: cfg.optionType,
      strike: recommendation.strike,
      expiration: recommendation.expiry,
    });
    return {
      ...baseContract,
      contractId: newContractId,
      optionType: cfg.optionType,
      bid: null,
      ask: null,
      mid: recommendation.midPrice ?? recommendation.markPremium ?? null,
      lastPrice: recommendation.lastPrice ?? null,
    };
  }, [baseContract, cfg.optionType, recommendation]);

  const parsedQuantity = Math.max(
    1,
    Number.parseInt(quantity || "1", 10) || 1,
  );
  const parsedLimit = limitPrice ? Number(limitPrice) : null;
  const risk = calculateOrderRisk({
    contract,
    side: cfg.side,
    quantity: parsedQuantity,
    availableCash: account.buyingPower,
    limitPrice: orderType === "LIMIT" ? parsedLimit : null,
  });
  const missingLimitPrice =
    orderType === "LIMIT" &&
    (parsedLimit === null || Number.isNaN(parsedLimit) || parsedLimit <= 0);
  const orderDisabled = isSubmitting || missingLimitPrice;

  async function submitOrder() {
    setIsSubmitting(true);
    try {
      const response = await placeSimulationOrder({
        accountId: account.id,
        startingCash: account.startingCash,
        symbol: contract.symbol,
        contract,
        side: cfg.side,
        orderType,
        quantity: parsedQuantity,
        limitPrice: orderType === "LIMIT" ? parsedLimit : null,
        stopLoss: stopLoss ? Number(stopLoss) : null,
        takeProfit: takeProfit ? Number(takeProfit) : null,
        strategy,
      });
      onAccountUpdated(response.account);
      onStatus(
        response.order.status === "FILLED"
          ? `${cfg.action}: filled at ${formatCurrency(response.order.fillPrice ?? 0)} — ${cfg.isDebit ? "debit" : "credit"}.`
          : `${cfg.action} ${response.order.orderType.toLowerCase()} order is ${response.order.status.toLowerCase()}.`,
      );
    } catch (error) {
      onStatus(
        error instanceof Error
          ? error.message
          : "Could not submit simulated order.",
      );
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <section className="rounded-lg border border-[#2f81f7]/25 bg-[#0d1624] p-4 shadow-[0_20px_80px_rgba(0,0,0,0.28)]">
      {/* Header */}
      <div className="mb-3 flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <div className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#58a6ff]">
            Simulated order — {cfg.action}
          </div>
          <h3 className="mt-1 text-lg font-semibold text-white">
            {contract.symbol}{" "}
            <span className="font-normal text-[#8b949e]">
              {contract.optionType}
            </span>{" "}
            {formatCurrency(contract.strike)}
          </h3>
        </div>
        <div className="flex items-center gap-2 sm:flex-col sm:items-end">
          <span className="rounded-md border border-[#f0883e]/30 bg-[#f0883e]/10 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-[#f0b72f]">
            Paper
          </span>
          <button
            onClick={() => void submitOrder()}
            disabled={orderDisabled}
            className="w-full whitespace-nowrap rounded-md bg-[#2f81f7] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#58a6ff] disabled:cursor-not-allowed disabled:opacity-50 sm:w-auto"
          >
            {isSubmitting ? "Simulating..." : cfg.buttonLabel}
          </button>
        </div>
      </div>

      {/* Quote bar */}
      <div className="rounded-lg border border-white/[0.06] bg-[#060a12] p-3">
        <div className="flex items-center justify-between gap-3 text-xs">
          <div>
            <div className="text-[10px] uppercase tracking-wide text-[#8b949e]">
              Expiration
            </div>
            <div className="font-semibold text-white">
              {formatDate(contract.expiration)}
            </div>
          </div>
          <div className="text-right">
            <div className="text-[10px] uppercase tracking-wide text-[#8b949e]">
              Buying power
            </div>
            <div className="font-semibold text-[#3fb950]">
              {formatCurrency(account.buyingPower)}
            </div>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-4 gap-2 text-xs">
          <Quote label="Bid" value={contract.bid} />
          <Quote label="Ask" value={contract.ask} />
          <Quote label="Mid" value={contract.mid} />
          <Quote label="Last" value={contract.lastPrice} />
        </div>
      </div>

      {/* Strategy selector */}
      <div className="mt-3 rounded-lg border border-white/[0.06] bg-[#101927] p-3">
        <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8b949e]">
          Strategy
        </div>
        <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4">
          {STRATEGY_BUTTONS.map(({ label, value }) => {
            const active = strategy === value;
            const isShort = value.startsWith("SHORT");
            return (
              <button
                key={value}
                onClick={() => setStrategy(value)}
                className={`rounded-md px-2 py-2 text-xs font-semibold transition ${
                  active
                    ? isShort
                      ? "bg-[#f85149] text-white"
                      : "bg-[#238636] text-white"
                    : "border border-white/[0.08] bg-[#060a12] text-[#8b949e] hover:bg-white/[0.05] hover:text-white"
                }`}
              >
                {label}
              </button>
            );
          })}
        </div>
      </div>

      {/* Strategy summary card */}
      <div
        className={`mt-2 rounded-lg border p-3 text-xs ${
          cfg.isDebit
            ? "border-[#238636]/25 bg-[#238636]/5"
            : "border-[#f85149]/25 bg-[#f85149]/5"
        }`}
      >
        <div className="mb-1.5 flex items-center justify-between gap-2">
          <span className="font-semibold text-white">
            {strategy.replace("_", " ")} — {cfg.direction}
          </span>
          <span
            className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${
              cfg.isDebit
                ? "bg-[#d29922]/10 text-[#f0b72f]"
                : "bg-[#238636]/10 text-[#3fb950]"
            }`}
          >
            {cfg.isDebit ? "Debit" : "Credit"}
          </span>
        </div>
        <div className="text-[#8b949e]">{cfg.riskNote}</div>
        <div className="mt-0.5 text-[#8b949e]">{cfg.profitNote}</div>
        {cfg.shortWarning && (
          <div className="mt-2 rounded border border-[#f85149]/30 bg-[#f85149]/10 px-2 py-1.5 text-[#ffb3ad]">
            {cfg.shortWarning}
          </div>
        )}
      </div>

      {/* Order controls */}
      <div className="mt-3 rounded-lg border border-white/[0.06] bg-[#101927] p-3">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8b949e]">
            Order
          </div>
          <div className="text-xs text-[#8b949e]">Qty {parsedQuantity}</div>
        </div>
        <div className="grid gap-3">
          <Segment
            label="Type"
            value={orderType}
            options={["MARKET", "LIMIT"]}
            onChange={(value) => setOrderType(value as OrderType)}
          />
          <div className="grid grid-cols-2 gap-3">
            <Field
              label="Quantity"
              value={quantity}
              onChange={setQuantity}
              type="number"
              min="1"
              step="1"
            />
            <Field
              label="Limit"
              value={limitPrice}
              onChange={setLimitPrice}
              type="number"
              step="0.01"
              disabled={orderType !== "LIMIT"}
              placeholder={orderType === "LIMIT" ? "Required" : "Market"}
            />
          </div>
        </div>
        {risk.warning && (
          <div className="mt-3 rounded-md border border-[#f85149]/25 bg-[#f85149]/10 px-3 py-2 text-xs text-[#ffb3ad]">
            {risk.warning}
          </div>
        )}
      </div>

      {/* Risk metrics */}
      <div className="mt-3 grid grid-cols-2 gap-2 text-xs">
        <Metric
          label={cfg.isDebit ? "Total Debit" : "Total Credit"}
          value={formatCurrency(
            cfg.isDebit ? risk.totalDebit : risk.totalCredit,
          )}
        />
        <Metric
          label="BP After"
          value={formatCurrency(risk.buyingPowerAfterOrder)}
          tone={risk.buyingPowerAfterOrder >= 0 ? "good" : "bad"}
        />
        <Metric label="Max Loss" value={risk.maxLoss} />
        <Metric label="Max Profit" value={risk.maxProfit} />
        <Metric
          label="Breakeven"
          value={
            risk.breakeven === null ? "N/A" : formatCurrency(risk.breakeven)
          }
        />
        <Metric label="Est. Cost" value={formatCurrency(risk.estimatedCost)} />
      </div>

      {/* Auto-close guards */}
      <div className="mt-3 rounded-lg border border-white/[0.06] bg-[#060a12] p-3">
        <div className="mb-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8b949e]">
          Auto-Close Guards (option premium price)
        </div>
        <div className="mb-2 text-[10px] leading-relaxed text-[#484f58]">
          {cfg.isDebit
            ? "Long: stop triggers when premium falls to or below target; take-profit triggers when premium rises to or above target."
            : "Short: stop triggers when premium rises to or above target; take-profit triggers when premium falls to or below target."}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <Field
            label="Stop Loss"
            value={stopLoss}
            onChange={setStopLoss}
            type="number"
            step="0.01"
            placeholder="Optional"
          />
          <Field
            label="Take Profit"
            value={takeProfit}
            onChange={setTakeProfit}
            type="number"
            step="0.01"
            placeholder="Optional"
          />
        </div>
      </div>
    </section>
  );
}

function Quote({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-[#0d1016] px-2 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[#8b949e]">
        {label}
      </div>
      <div className="truncate font-semibold text-white">
        {value === null ? "N/A" : formatCurrency(value)}
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  disabled,
  type = "text",
  placeholder,
  min,
  step,
}: {
  label: string;
  value: string;
  onChange?: (value: string) => void;
  disabled?: boolean;
  type?: string;
  placeholder?: string;
  min?: string;
  step?: string;
}) {
  return (
    <label className="text-[11px] font-semibold uppercase tracking-wide text-[#8b949e]">
      {label}
      <input
        type={type}
        value={value}
        disabled={disabled}
        placeholder={placeholder}
        min={min}
        step={step}
        onChange={(event) => onChange?.(event.target.value)}
        className="mt-1 w-full rounded-md border border-white/[0.08] bg-[#060a12] px-3 py-2 text-sm font-medium normal-case tracking-normal text-white placeholder:text-[#484f58] disabled:opacity-50"
      />
    </label>
  );
}

function Segment({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: string[];
  onChange: (value: string) => void;
}) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-[#8b949e]">
        {label}
      </div>
      <div className="grid grid-cols-2 overflow-hidden rounded-md border border-white/[0.08] bg-[#060a12] p-1">
        {options.map((option) => {
          const active = option === value;
          return (
            <button
              key={option}
              onClick={() => onChange(option)}
              className={`rounded px-3 py-1.5 text-xs font-semibold transition ${
                active
                  ? "bg-[#2f81f7] text-white"
                  : "text-[#8b949e] hover:bg-white/[0.05] hover:text-white"
              }`}
            >
              {option}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "good" | "bad";
}) {
  return (
    <div className="rounded-md border border-white/[0.06] bg-[#060a12] px-3 py-2">
      <div className="text-[10px] uppercase tracking-wide text-[#8b949e]">
        {label}
      </div>
      <div
        className={`truncate font-semibold ${
          tone === "good"
            ? "text-[#3fb950]"
            : tone === "bad"
              ? "text-[#f85149]"
              : "text-white"
        }`}
      >
        {value}
      </div>
    </div>
  );
}
