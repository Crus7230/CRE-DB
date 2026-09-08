import { getCachedMacroTimeseries } from "@/lib/server/market-data-cache";
import { normalizeCanonicalMacroTimeseries } from "@/lib/server/macro-timeseries";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";

export const runtime = "nodejs";

type MacroTimeseriesLoader = () => Promise<unknown>;

export async function loadMacroTimeseriesResponse(loader: MacroTimeseriesLoader) {
  const startedAt = performance.now();
  try {
    return jsonWithServerTiming(
      normalizeCanonicalMacroTimeseries(await loader()),
      { headers: { "cache-control": "private, max-age=3600" } },
      "data",
      startedAt,
    );
  } catch (error) {
    console.error("macro timeseries request failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse("MACRO_TIMESERIES_UNAVAILABLE", startedAt);
  }
}

export async function GET() {
  return loadMacroTimeseriesResponse(() => getCachedMacroTimeseries());
}
