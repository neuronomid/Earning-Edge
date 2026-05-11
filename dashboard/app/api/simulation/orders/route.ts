import { NextResponse, type NextRequest } from "next/server";
import { placeSimulationOrder } from "@/lib/simulation/orderSimulationService";
import { getOrCreateAccount } from "@/lib/simulation/simulationStore";
import { type PlaceOrderPayload } from "@/types/simulation";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const accountId = request.nextUrl.searchParams.get("accountId");
  if (!accountId) {
    return NextResponse.json({ detail: "accountId is required." }, { status: 400 });
  }
  return NextResponse.json(getOrCreateAccount(accountId).orders);
}

export async function POST(request: NextRequest) {
  try {
    const payload = (await request.json()) as PlaceOrderPayload;
    if (!payload.accountId || !payload.symbol || !payload.contract) {
      return NextResponse.json({ detail: "accountId, symbol, and contract are required." }, { status: 400 });
    }
    if (payload.orderType === "LIMIT" && (!payload.limitPrice || payload.limitPrice <= 0)) {
      return NextResponse.json({ detail: "Limit price is required for limit orders." }, { status: 400 });
    }
    return NextResponse.json(await placeSimulationOrder(payload, payload.startingCash));
  } catch (error) {
    const detail = error instanceof Error ? error.message : "Could not place simulated order.";
    return NextResponse.json({ detail }, { status: 400 });
  }
}
