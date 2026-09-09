import {
  EvidenceSearchRequestError,
  parseEvidenceSearchBody,
} from "@/lib/evidence-search-contract";
import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";
import { ProcessDataCacheOverloadError } from "@/lib/server/bounded-data-cache";
import { getCachedEvidenceSearch } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const MAX_REQUEST_BYTES = 4_096;

function firstForwardedValue(value: string | null) {
  return value?.split(",", 1)[0]?.trim() || null;
}

function externallyVisibleOrigin(request: Request) {
  const internal = new URL(request.url);
  const host = firstForwardedValue(request.headers.get("x-forwarded-host"))
    ?? request.headers.get("host")?.trim()
    ?? internal.host;
  const protocol = firstForwardedValue(request.headers.get("x-forwarded-proto"))
    ?? internal.protocol.slice(0, -1);
  try {
    return new URL(`${protocol}://${host}`).origin;
  } catch {
    throw new EvidenceSearchRequestError("Invalid request origin");
  }
}

async function readBoundedJson(request: Request) {
  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_REQUEST_BYTES) {
    throw new EvidenceSearchRequestError("Evidence search body is too large");
  }
  if (!request.body) throw new EvidenceSearchRequestError("Evidence search body is required");
  const reader = request.body.getReader();
  const decoder = new TextDecoder();
  let size = 0;
  let text = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > MAX_REQUEST_BYTES) {
        await reader.cancel();
        throw new EvidenceSearchRequestError("Evidence search body is too large");
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    return JSON.parse(text) as unknown;
  } catch (error) {
    if (error instanceof EvidenceSearchRequestError) throw error;
    throw new EvidenceSearchRequestError("Evidence search body must be valid JSON");
  } finally {
    reader.releaseLock();
  }
}

export async function POST(request: Request): Promise<Response> {
  const startedAt = performance.now();
  try {
    const origin = request.headers.get("origin");
    if (origin && origin !== externallyVisibleOrigin(request)) {
      return jsonWithServerTiming(
        { error: "허용되지 않은 요청입니다.", code: "CROSS_ORIGIN_REQUEST" },
        { status: 403, headers: { "Cache-Control": "private, no-store" } },
        "data",
        startedAt,
      );
    }
    const search = parseEvidenceSearchBody(await readBoundedJson(request));
    const payload = await getCachedEvidenceSearch(search);
    return jsonWithServerTiming(
      payload,
      { headers: { "Cache-Control": "private, no-store" } },
      "data",
      startedAt,
    );
  } catch (error) {
    if (error instanceof EvidenceSearchRequestError) {
      return jsonWithServerTiming(
        { error: "검색어와 필터를 확인해 주세요.", code: error.code },
        { status: 400, headers: { "Cache-Control": "private, no-store" } },
        "data",
        startedAt,
      );
    }
    if (error instanceof ProcessDataCacheOverloadError) {
      return infrastructureUnavailableResponse(
        error.code,
        startedAt,
        { "Cache-Control": "private, no-store", "Retry-After": "1" },
      );
    }
    console.error("Evidence search failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse(
      "EVIDENCE_SEARCH_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "private, no-store" },
    );
  }
}
