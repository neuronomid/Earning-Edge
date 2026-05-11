import { NextResponse, type NextRequest } from "next/server";
import { refreshAccount } from "@/lib/simulation/portfolioService";
import { processPendingOrders } from "@/lib/simulation/orderSimulationService";
import { getOrCreateAccount } from "@/lib/simulation/simulationStore";

export const dynamic = "force-dynamic";

export async function GET(
  request: NextRequest,
  { params }: { params: { accountId: string } },
) {
  const startingCash = Number(request.nextUrl.searchParams.get("startingCash") ?? "150000");
  const account = getOrCreateAccount(params.accountId, Number.isFinite(startingCash) ? startingCash : 150000);
  await processPendingOrders(account);
  return NextResponse.json(await refreshAccount(account));
}
