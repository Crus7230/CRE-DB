import { executeMarketSql } from "@/lib/server/db";
import { getEntityDetail } from "@/lib/server/entity-intelligence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ kind: string; id: string }> }) {
  try {
    const { kind, id } = await context.params;
    const normalized = kind.toUpperCase();
    if (normalized !== "EVENT" && normalized !== "ASSET") return Response.json({ error: "지원하지 않는 상세 유형입니다." }, { status: 400 });
    const detail = await getEntityDetail(executeMarketSql, normalized, id);
    return detail ? Response.json(detail) : Response.json({ error: "상세정보를 찾지 못했습니다." }, { status: 404 });
  } catch (error) {
    console.error("entity intelligence query failed", error);
    return Response.json({ error: "상세정보를 조회하지 못했습니다." }, { status: 500 });
  }
}
