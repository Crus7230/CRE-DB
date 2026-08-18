import { NextResponse } from "next/server";
import { executeMarketSql } from "@/lib/server/db";
import { getInstitutionalCapital } from "@/lib/server/domain-workspaces";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await getInstitutionalCapital(executeMarketSql));
  } catch {
    return NextResponse.json({ error: "기관자금 상세정보를 조회하지 못했습니다." }, { status: 500 });
  }
}
