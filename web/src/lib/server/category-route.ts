import type { CategoryIndexResponse } from "@/lib/search-contract";

export async function runCategoryIndexRequest(
  getIndex: () => Promise<CategoryIndexResponse>,
): Promise<Response> {
  try {
    return Response.json(await getIndex(), {
      headers: { "Cache-Control": "private, max-age=60" },
    });
  } catch {
    return Response.json(
      { error: "카테고리 색인을 불러오지 못했습니다." },
      { status: 503 },
    );
  }
}
