import { NextResponse } from "next/server";
import { executeMarketSql } from "@/lib/server/db";
import { getSaleProcesses } from "@/lib/server/domain-workspaces";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  try {
    return NextResponse.json(await getSaleProcesses(executeMarketSql));
  } catch {
    return NextResponse.json({ error: "매각절차 상세정보를 조회하지 못했습니다." }, { status: 500 });
  }
}
