import {
  infrastructureUnavailableResponse,
  jsonWithServerTiming,
  safeErrorDescriptor,
} from "@/lib/server/api-response";
import { executeMarketSql, isLocalMarketDatabaseAuthority } from "@/lib/server/db";
import { getDocumentDetail } from "@/lib/server/document-intelligence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  const startedAt = performance.now();
  try {
    const { id } = await context.params;
    const detail = await getDocumentDetail(executeMarketSql, id, {
      allowArchiveFallback: isLocalMarketDatabaseAuthority(),
    });
    if (!detail) return jsonWithServerTiming(
      { error: "문서를 찾지 못했습니다." },
      { status: 404 },
      "data",
      startedAt,
    );
    return jsonWithServerTiming(detail, {}, "data", startedAt);
  } catch (error) {
    console.error("document intelligence query failed", safeErrorDescriptor(error));
    return infrastructureUnavailableResponse("DOCUMENT_DETAIL_UNAVAILABLE", startedAt);
  }
}
