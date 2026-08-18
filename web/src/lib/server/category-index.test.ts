import { describe, expect, it, vi } from "vitest";
import { getCategoryIndex, type CategorySqlExecutor } from "@/lib/server/category-index";

describe("getCategoryIndex", () => {
  it("normalizes database taxonomy groups without interpolating user input", async () => {
    const execute: CategorySqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ payload: { groups: [
        { group: "EVENT_CATEGORY", label: "이벤트 카테고리", kind: "EVENT", items: [{ key: "PF", label: "PF", itemCount: 645, canonicalCount: 0 }] },
        { group: "DOCUMENT_TYPE", label: "문서 유형", kind: "DOCUMENT", items: [{ key: "RSS_ITEM", label: "RSS_ITEM", itemCount: 7400 }] },
      ] } }],
    });

    const result = await getCategoryIndex(execute);

    expect(result.groups).toHaveLength(2);
    expect(result.groups[0].items[0]).toMatchObject({ key: "PF", itemCount: 645 });
    expect(execute).toHaveBeenCalledTimes(1);
  });
});
