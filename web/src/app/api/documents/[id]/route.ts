import { NextResponse } from "next/server";
import { executeMarketSql } from "@/lib/server/db";
import { getDocumentDetail } from "@/lib/server/document-intelligence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    const detail = await getDocumentDetail(executeMarketSql, id);
    if (!detail) return NextResponse.json({ error: "문서를 찾지 못했습니다." }, { status: 404 });
    return NextResponse.json(detail);
  } catch (error) {
    console.error("document intelligence query failed", error);
    return NextResponse.json({ error: "문서 상세를 조회하지 못했습니다." }, { status: 500 });
  }
}
