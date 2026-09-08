import { describe, expect, it, vi } from "vitest";
import { searchContextualIntelligence } from "@/lib/server/contextual-search";
import type { ContextualSearchRequest } from "@/lib/contextual-search-contract";

const request: ContextualSearchRequest = {
  q: "국민연금",
  mode: "APPROVED",
  domain: "MANAGER_SELECTION",
  eventType: "MANAGER_SELECTION",
  stage: "SELECTED",
  processType: "RFP",
  role: "APPOINTING_ENTITY",
  participantEntityId: "org-nps",
  assetId: "asset-1",
  region: "SEOUL_CBD",
  industry: "AI",
  impact: "INCREASE",
  sourceGrade: "OFFICIAL_DIRECT",
  from: "2026-01-01",
  to: "2026-09-03",
  page: 1,
  pageSize: 50,
};

describe("contextual search SQL", () => {
  it("uses approved-only relation filters without interpolating user text", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload: { total: 0, facets: {}, results: [] } }] });
    await searchContextualIntelligence(execute, request);

    const [sql, values] = execute.mock.calls[0];
    expect(sql).toContain("FROM contextual_search_records");
    expect(sql).toContain("record_mode = $1");
    expect(sql).toContain("review_status = 'APPROVED'");
    expect(sql).toContain("FROM contextual_frame_participants participant");
    expect(sql).toContain("participant.frame_id=record.frame_id");
    expect(sql).toContain("participant.role_code=$7");
    expect(sql).toContain("participant.entity_id=$8");
    expect(sql).not.toContain("participant_roles_json ? $7");
    expect(sql).not.toContain("participant_entity_ids_json ? $8");
    expect(sql).toContain("json_each(record.asset_ids_json)");
    expect(sql).toContain("json_each(record.region_ids_json)");
    expect(sql).toContain("json_each(record.industry_codes_json)");
    expect(sql).toContain("json_each(record.impact_directions_json)");
    expect(sql).toContain("lower(search_text) LIKE lower($2)");
    expect(sql).not.toMatch(/market_intelligence\.|::|\bILIKE\b|jsonb_/i);
    expect(sql).not.toContain("국민연금");
    expect(values).toContain("%국민연금%");
    expect(sql).toContain("ORDER BY event_domain");
    expect(sql).toContain("FROM paged result");
    expect(sql).not.toContain("json(item) ORDER BY");
    expect(sql).not.toContain(") ORDER BY event_date IS NULL");
  });

  it("queries only the legacy ledger in explicit legacy mode", async () => {
    const execute = vi.fn().mockResolvedValue({ rows: [{ payload: { total: 0, facets: {}, results: [] } }] });
    await searchContextualIntelligence(execute, { ...request, mode: "LEGACY" });
    const [sql] = execute.mock.calls[0];
    expect(sql).toContain("FROM legacy_derived_records");
    expect(sql).toContain("$1 AS mode");
    expect(sql).toContain("$15 AS date_to");
    expect(sql).toContain("$17 AS row_limit");
    expect(sql).toContain("legacy_reason");
    expect(sql).not.toContain("reason_code");
    expect(sql).not.toContain("lineage_json");
    expect(sql).not.toContain("FROM contextual_search_records");
    expect(sql).toContain("ORDER BY target_kind");
    expect(sql).toContain("FROM paged result");
    expect(sql).not.toContain("json(item) ORDER BY");
    expect(sql).not.toContain(") ORDER BY captured_at DESC");
    expect(sql).not.toMatch(/market_intelligence\.|::|\bILIKE\b|jsonb_/i);
  });
});
