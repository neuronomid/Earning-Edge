import { NextResponse, type NextRequest } from "next/server";
import { fetchLatestOptionQuotes } from "@/lib/simulation/optionQuoteService";
import { type OptionContract } from "@/types/option";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  const payload = (await request.json()) as { contracts?: OptionContract[] };
  const contracts = payload.contracts ?? [];
  return NextResponse.json(await fetchLatestOptionQuotes(contracts));
}
