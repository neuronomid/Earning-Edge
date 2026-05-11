import { NextResponse, type NextRequest } from "next/server";
import { updatePositionRisk } from "@/lib/simulation/portfolioService";
import { findAccountByPosition } from "@/lib/simulation/simulationStore";
import { type RiskUpdatePayload } from "@/types/simulation";

export const dynamic = "force-dynamic";

export async function PATCH(
  request: NextRequest,
  { params }: { params: { id: string } },
) {
  const account = findAccountByPosition(params.id);
  if (!account) {
    return NextResponse.json({ detail: "Position was not found." }, { status: 404 });
  }
  const payload = (await request.json()) as RiskUpdatePayload;
  return NextResponse.json(
    updatePositionRisk(
      account,
      params.id,
      payload.stopLoss ?? null,
      payload.takeProfit ?? null,
    ),
  );
}
