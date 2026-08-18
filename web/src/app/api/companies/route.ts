import { NextRequest, NextResponse } from "next/server";
import { parseCompanyParams } from "@/lib/intelligence-contract";
import { executeMarketSql } from "@/lib/server/db";
import { getCompanies } from "@/lib/server/company-intelligence";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET(request: NextRequest) {
  try {
    return NextResponse.json(await getCompanies(executeMarketSql, parseCompanyParams(request.nextUrl.searchParams)));
  } catch (error) {
    console.error("company intelligence query failed", error);
    return NextResponse.json({ error: "회사 인텔리전스를 조회하지 못했습니다." }, { status: 500 });
  }
}
