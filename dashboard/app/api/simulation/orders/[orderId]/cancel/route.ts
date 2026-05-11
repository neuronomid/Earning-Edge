import { NextResponse } from "next/server";
import { cancelOrder } from "@/lib/simulation/orderSimulationService";
import { findAccountByOrder } from "@/lib/simulation/simulationStore";

export const dynamic = "force-dynamic";

export async function POST(
  _request: Request,
  { params }: { params: { orderId: string } },
) {
  const account = findAccountByOrder(params.orderId);
  if (!account) {
    return NextResponse.json({ detail: "Order was not found." }, { status: 404 });
  }
  const updated = cancelOrder(account, params.orderId);
  if (!updated) {
    return NextResponse.json({ detail: "Only pending orders can be cancelled." }, { status: 400 });
  }
  return NextResponse.json(updated);
}
