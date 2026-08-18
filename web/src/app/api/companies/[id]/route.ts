import { NextResponse } from "next/server";
import { executeMarketSql } from "@/lib/server/db";
import { getCompanyDetail } from "@/lib/server/company-intelligence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(_request: Request, context: { params: Promise<{ id: string }> }) {
  try {
    const { id } = await context.params;
    return NextResponse.json(await getCompanyDetail(executeMarketSql, id));
  } catch (error) {
    const status = error instanceof Error && /not found/i.test(error.message) ? 404 : 500;
    return NextResponse.json({ error: status === 404 ? "회사를 찾을 수 없습니다." : "회사 상세정보를 조회하지 못했습니다." }, { status });
  }
}
