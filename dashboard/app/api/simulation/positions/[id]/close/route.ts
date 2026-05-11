import { NextResponse, type NextRequest } from "next/server";
import { closePositionAtMarket, finalizeAccount } from "@/lib/simulation/portfolioService";
import { findAccountByPosition } from "@/lib/simulation/simulationStore";
import { type CloseReason } from "@/types/simulation";
import { type OptionQuote } from "@/types/option";

export const dynamic = "force-dynamic";

export async function POST(
  request: NextRequest,
  { params }: { params: { id: string } },
) {
  const account = findAccountByPosition(params.id);
  if (!account) {
    return NextResponse.json({ detail: "Position was not found." }, { status: 404 });
  }

  const position = account.openPositions.find((item) => item.id === params.id);
  if (!position) {
    return NextResponse.json({ detail: "Position is no longer open." }, { status: 404 });
  }

  const payload = (await request.json()) as {
    reason?: CloseReason;
    quote?: Partial<OptionQuote>;
  };
  const reason =
    payload.reason === "STOP_LOSS" || payload.reason === "TAKE_PROFIT"
      ? payload.reason
      : "MANUAL";
  const quote: OptionQuote = {
    ...position.contract,
    bid: payload.quote?.bid ?? position.currentBid,
    ask: payload.quote?.ask ?? position.currentAsk,
    mid: payload.quote?.mid ?? position.currentMid,
    lastPrice: payload.quote?.lastPrice ?? position.contract.lastPrice,
    underlyingPrice: payload.quote?.underlyingPrice ?? position.contract.underlyingPrice,
    source: payload.quote?.source ?? position.contract.source,
    timestamp: payload.quote?.timestamp ?? new Date().toISOString(),
  };

  const triggerReason = reason === "MANUAL" ? undefined : reason;
  const closed = closePositionAtMarket(account, params.id, quote, triggerReason);
  if (!closed) {
    return NextResponse.json({ detail: "Position could not be closed." }, { status: 400 });
  }

  return NextResponse.json(finalizeAccount(account));
}
