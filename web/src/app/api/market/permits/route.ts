import {
  parsePermitTimeseriesRequest,
  PermitRequestError,
} from "@/lib/permit-timeseries-contract";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";
import { getCachedPermitTimeseries } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

type PermitLoader = typeof getCachedPermitTimeseries;

export async function loadPermitTimeseriesResponse(
  request: Request,
  loader: PermitLoader,
) {
  const startedAt = performance.now();
  let parsed;
  try {
    parsed = parsePermitTimeseriesRequest(new URL(request.url).searchParams);
  } catch (error) {
    if (error instanceof PermitRequestError) {
      return jsonWithServerTiming(
        { error: "허가 통계 조회 조건이 올바르지 않습니다.", code: error.code },
        { status: 400, headers: { "Cache-Control": "no-store" } },
        "data",
        startedAt,
      );
    }
    throw error;
  }
  try {
    const payload = await loader(parsed);
    return jsonWithServerTiming(
      payload,
      { headers: { "Cache-Control": "private, max-age=21600" } },
      "data",
      startedAt,
    );
  } catch (error) {
    console.error("building permit timeseries request failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse(
      "PERMIT_TIMESERIES_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "no-store" },
    );
  }
}

export async function GET(request: Request) {
  return loadPermitTimeseriesResponse(request, getCachedPermitTimeseries);
}
