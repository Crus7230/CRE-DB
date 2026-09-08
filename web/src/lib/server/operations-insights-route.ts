import type { OperationsOverviewResponse } from "@/lib/operations-insights-contract";

export async function runOperationsOverviewRequest(
  getOverview: () => Promise<OperationsOverviewResponse>,
): Promise<Response> {
  try {
    return Response.json(await getOverview(), {
      headers: { "Cache-Control": "private, max-age=60" },
    });
  } catch (error) {
    const detail = error instanceof Error
      ? { name: error.name, code: "code" in error ? String(error.code) : undefined }
      : { name: "UnknownError" };
    console.error("operations overview request failed", detail);
    return Response.json(
      { error: "운영 현황을 불러오지 못했습니다." },
      { status: 503 },
    );
  }
}
