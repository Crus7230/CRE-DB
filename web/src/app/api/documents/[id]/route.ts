import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";
import { getCachedArticleDetail } from "@/lib/server/market-data-cache";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const startedAt = performance.now();
  try {
    const { id } = await context.params;
    const detail = await getCachedArticleDetail(id);
    if (!detail) return jsonWithServerTiming(
      { error: "문서를 찾지 못했습니다." },
      { status: 404, headers: { "Cache-Control": "private, no-store" } },
      "data",
      startedAt,
    );
    return jsonWithServerTiming(
      detail,
      { headers: { "Cache-Control": "private, no-store" } },
      "data",
      startedAt,
    );
  } catch (error) {
    console.error("document intelligence query failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse(
      "DOCUMENT_DETAIL_UNAVAILABLE",
      startedAt,
      { "Cache-Control": "private, no-store" },
    );
  }
}
