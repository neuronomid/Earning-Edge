import { NextResponse, type NextRequest } from "next/server";
import { fetchLatestOptionQuote } from "@/lib/simulation/optionQuoteService";
import { type OptionContract } from "@/types/option";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { contractId: string } },
) {
  const contract = (await request.json()) as OptionContract;
  if (!contract?.symbol) {
    return NextResponse.json({ detail: "Contract payload is required." }, { status: 400 });
  }
  return NextResponse.json(
    await fetchLatestOptionQuote({ ...contract, contractId: params.contractId }),
  );
}
