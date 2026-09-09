import { getCachedQuantitativeMarketPulse } from "@/lib/server/market-data-cache";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";

export const runtime = "nodejs";

type MarketPulseLoader = () => Promise<unknown>;

export async function loadMarketPulseResponse(loader: MarketPulseLoader) {
  const startedAt = performance.now();
  try {
    return jsonWithServerTiming(
      await loader(),
      { headers: { "cache-control": "private, no-store" } },
      "data",
      startedAt,
    );
  } catch (error) {
    console.error("quantitative market pulse request failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse(
      "MARKET_PULSE_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "private, no-store" },
    );
  }
}

export async function GET() {
  return loadMarketPulseResponse(() => getCachedQuantitativeMarketPulse());
}
