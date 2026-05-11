"use client";

import { cancelSimulationOrder } from "@/lib/api";
import { formatCurrency, formatDateTime } from "@/lib/formatters";
import { type SimulationAccount, type SimulationOrder } from "@/types/simulation";

export function OrderHistoryTable({
  account,
  onAccountUpdated,
  onStatus,
}: {
  account: SimulationAccount;
  onAccountUpdated: (account: SimulationAccount) => void;
  onStatus: (message: string) => void;
}) {
  if (account.orders.length === 0) {
    return (
      <div className="rounded-xl border border-dashed border-white/[0.12] bg-[#121821] px-4 py-8 text-center text-sm text-[#8b949e]">
        No simulated orders yet.
      </div>
    );
  }

  async function cancel(order: SimulationOrder) {
    onAccountUpdated(await cancelSimulationOrder(order.id));
    onStatus(`Cancelled pending order for ${order.symbol}.`);
  }

  return (
    <div className="overflow-hidden rounded-xl border border-white/[0.06] bg-[#121821]">
      <div className="border-b border-white/[0.06] px-4 py-3 text-sm font-semibold text-white">
        Order History
      </div>
      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-xs">
          <thead className="bg-[#0b111a] text-[10px] uppercase tracking-[0.18em] text-[#8b949e]">
            <tr>
              <th className="px-4 py-3">Created</th>
              <th className="px-4 py-3">Order</th>
              <th className="px-4 py-3">Type</th>
              <th className="px-4 py-3">Limit</th>
              <th className="px-4 py-3">Fill</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3 text-right">Action</th>
            </tr>
          </thead>
          <tbody>
            {account.orders.map((order) => (
              <tr key={order.id} className="border-t border-white/[0.04] text-[#c9d1d9]">
                <td className="px-4 py-3">{formatDateTime(order.createdAt)}</td>
                <td className="px-4 py-3">
                  <div className="font-semibold text-white">
                    {order.side} {order.quantity} {order.symbol}
                  </div>
                  <div className="text-[11px] text-[#8b949e]">
                    {order.optionType} {formatCurrency(order.contract.strike)} exp {order.contract.expiration}
                  </div>
                </td>
                <td className="px-4 py-3">{order.orderType}</td>
                <td className="px-4 py-3">{order.limitPrice === null ? "-" : formatCurrency(order.limitPrice)}</td>
                <td className="px-4 py-3">{order.fillPrice === null ? "-" : formatCurrency(order.fillPrice)}</td>
                <td className="px-4 py-3">
                  <StatusPill status={order.status} />
                  {order.triggerReason && (
                    <div className="mt-1 text-[10px] text-[#f0b72f]">{order.triggerReason.replace("_", " ")}</div>
                  )}
                  {order.rejectionReason && (
                    <div className="mt-1 max-w-[220px] text-[10px] text-[#f85149]">{order.rejectionReason}</div>
                  )}
                </td>
                <td className="px-4 py-3 text-right">
                  {order.status === "PENDING" ? (
                    <button
                      onClick={() => void cancel(order)}
                      className="rounded-md border border-white/[0.08] bg-[#21262d] px-2.5 py-1.5 text-xs font-semibold text-[#c9d1d9] transition hover:bg-[#30363d] hover:text-white"
                    >
                      Cancel
                    </button>
                  ) : (
                    <span className="text-[#484f58]">-</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function StatusPill({ status }: { status: SimulationOrder["status"] }) {
  const className =
    status === "FILLED"
      ? "bg-[#238636]/10 text-[#3fb950]"
      : status === "PENDING"
        ? "bg-[#d29922]/10 text-[#f0b72f]"
        : status === "REJECTED" || status === "CANCELLED"
          ? "bg-[#f85149]/10 text-[#ffb3ad]"
          : "bg-[#30363d] text-[#c9d1d9]";
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${className}`}>
      {status}
    </span>
  );
}
