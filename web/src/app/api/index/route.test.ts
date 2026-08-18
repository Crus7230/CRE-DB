import { expect, it, vi } from "vitest";
import { runCategoryIndexRequest } from "@/lib/server/category-route";

it("returns the database category index as JSON", async () => {
  const getIndex = vi.fn().mockResolvedValue({ groups: [], database: "supabase-postgresql", generatedAt: "2026-08-18T00:00:00Z", elapsedMs: 3 });
  const response = await runCategoryIndexRequest(getIndex);
  expect(response.status).toBe(200);
  expect(await response.json()).toMatchObject({ database: "supabase-postgresql", groups: [] });
});
