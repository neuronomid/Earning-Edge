import { NextResponse, type NextRequest } from "next/server";
import { getMarketDataProvider } from "@/lib/marketData";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  const symbol = request.nextUrl.searchParams.get("symbol");
  const userId = request.nextUrl.searchParams.get("userId") ?? undefined;

  if (!symbol || symbol.trim().length === 0) {
    return NextResponse.json({ error: "symbol query parameter is required." }, { status: 400 });
  }

  const clean = symbol.trim().toUpperCase();
  const provider = getMarketDataProvider();

  try {
    const quote = await provider.fetchStockQuote(clean, userId);
    return NextResponse.json(quote, {
      headers: {
        "X-Data-Mode": quote.dataMode,
        "X-Data-Source": quote.provider,
      },
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : "Stock quote fetch failed.";
    // Fallback to mock so the UI always gets a response
    const { MockProvider } = await import("@/lib/marketData/MockProvider");
    const mock = new MockProvider();
    const fallback = await mock.fetchStockQuote(clean);
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
