import { NextResponse, type NextRequest } from "next/server";
import { fetchDashboardSnapshot } from "@/lib/api";
import { recommendationToContract } from "@/lib/simulation/recommendationContract";

export const dynamic = "force-dynamic";

export async function GET(
  _request: NextRequest,
  { params }: { params: { symbol: string } },
) {
  const snapshot = await fetchDashboardSnapshot();
  const symbol = params.symbol.toUpperCase();
  return NextResponse.json(
    snapshot.recommendations
      .filter((recommendation) => recommendation.ticker.toUpperCase() === symbol)
      .map(recommendationToContract),
  );
}
