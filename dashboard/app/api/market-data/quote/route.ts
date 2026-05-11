import { NextResponse, type NextRequest } from "next/server";
import { getMarketDataProvider } from "@/lib/marketData";
import type { OptionQuoteRequest } from "@/lib/marketData/MarketDataProvider";

export const dynamic = "force-dynamic";

export async function POST(request: NextRequest) {
  let payload: OptionQuoteRequest;
  try {
    payload = (await request.json()) as OptionQuoteRequest;
  } catch {
    return NextResponse.json({ error: "Invalid JSON body." }, { status: 400 });
  }

  if (!payload.ticker || !payload.expiry || !payload.optionType || payload.strike == null) {
    return NextResponse.json(
      { error: "ticker, expiry, optionType, and strike are required." },
      { status: 400 },
    );
  }

  const provider = getMarketDataProvider();
  try {
    const quote = await provider.fetchOptionQuote(payload);
    return NextResponse.json(quote, {
      headers: {
        "X-Data-Mode": quote.dataMode,
        "X-Data-Source": quote.source,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Market data fetch failed.";
    // Fallback to mock if backend fails
    const { MockProvider } = await import("@/lib/marketData/MockProvider");
    const mock = new MockProvider();
    const fallback = await mock.fetchOptionQuote(payload);
    return NextResponse.json(
      { ...fallback, _fallbackReason: message },
      {
        headers: {
          "X-Data-Mode": "MOCK",
          "X-Data-Source": "mock_fallback",
        },
      },
    );
  }
}
