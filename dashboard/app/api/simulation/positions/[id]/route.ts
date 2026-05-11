import { NextResponse } from "next/server";
import { refreshAccount } from "@/lib/simulation/portfolioService";
import { processPendingOrders } from "@/lib/simulation/orderSimulationService";
import { getOrCreateAccount } from "@/lib/simulation/simulationStore";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: { id: string } },
) {
  const account = getOrCreateAccount(params.id);
  await processPendingOrders(account);
  const refreshed = await refreshAccount(account);
  return NextResponse.json({
    openPositions: refreshed.openPositions,
    closedPositions: refreshed.closedPositions,
  });
}
