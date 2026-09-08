import { describe, expect, it, vi } from "vitest";
import { createClient } from "@libsql/client";
import type { PermitTimeseriesResponse } from "@/lib/permit-timeseries-contract";
import {
  getPermitTimeseries,
  permitTimeseriesSql,
  type PermitTimeseriesSqlExecutor,
} from "@/lib/server/permit-timeseries";

const payload: PermitTimeseriesResponse = {
  generatedAt: "2026-09-08T05:00:00Z",
  sourceAsOfDate: "2026-09-07",
  availableFrom: "2000-01",
  availableThrough: "2026-08",
  selectedFrom: "2021-09",
  selectedThrough: "2026-08",
  groupBy: "ASSET_TYPE",
  filters: { eventType: "PERMIT", assetType: null, district: null, constructionAction: null },
  source: { code: "src_seoul_building_permit", label: "서울 열린데이터광장" },
  scope: { status: "IN_SCOPE", completedSnapshotsOnly: true, dateRule: "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT" },
  series: [],
  quality: { aggregateRowCount: 0, permitCount: 0, totalFloorAreaM2: 0, missingAreaCount: 0, invalidAreaCount: 0 },
};

describe("permit timeseries server query", () => {
  it("binds every filter and reads only the compact Seoul IN_SCOPE mart", async () => {
    const execute = vi.fn<PermitTimeseriesSqlExecutor>(async () => ({ rows: [{ payload }] }));
    await expect(getPermitTimeseries(execute, {
      groupBy: "ASSET_TYPE",
      from: null,
      to: null,
      eventType: "PERMIT",
      assetType: null,
      district: null,
      constructionAction: null,
    })).resolves.toEqual(payload);

    expect(execute).toHaveBeenCalledWith(permitTimeseriesSql, [
      "ASSET_TYPE", null, null, "PERMIT", null, null, null,
    ]);
    expect(permitTimeseriesSql).toContain("serving_v2_building_permit_monthly");
    expect(permitTimeseriesSql).toContain("source_id='src_seoul_building_permit'");
    expect(permitTimeseriesSql).toContain("scope_status='IN_SCOPE'");
    expect(permitTimeseriesSql).toContain("BETWEEN '1900-01' AND strftime('%Y-%m','now','+9 hours')");
    expect(permitTimeseriesSql).toContain("CASE ?1");
    expect(permitTimeseriesSql).not.toMatch(/\$\d/u);
    expect(permitTimeseriesSql).not.toMatch(/building_permit_snapshots|record_versions|REVIEW_|src_buildinghub/u);
  });

  it("binds numbered positional values in libSQL and returns the real non-empty JSON shape", async () => {
    const client = createClient({ url: "file::memory:" });
    try {
      await client.batch([
        `CREATE TABLE serving_v2_building_permit_monthly(
          source_id TEXT,event_month TEXT,event_type TEXT,district_name TEXT,
          asset_type TEXT,scope_status TEXT,construction_action TEXT,
          permit_count INTEGER,total_floor_area_m2 REAL,
          missing_area_count INTEGER,invalid_area_count INTEGER
        )`,
        `CREATE TABLE serving_dataset_freshness(
          dataset_code TEXT PRIMARY KEY,source_code TEXT,source_as_of_date TEXT,
          generated_at TEXT,source_status_code TEXT,source_row_count INTEGER,
          serving_row_count INTEGER,content_sha256 TEXT,metadata_json TEXT
        )`,
        `INSERT INTO serving_dataset_freshness VALUES(
          'SEOUL_BUILDING_PERMITS','src_seoul_building_permit','2026-09-07',
          '2026-09-08T05:00:00Z','READY',1,1,lower(hex(randomblob(32))),'{}'
        )`,
        `INSERT INTO serving_v2_building_permit_monthly VALUES(
          'src_seoul_building_permit','2026-08','PERMIT','강남구','OFFICE',
          'IN_SCOPE','NEW_SUPPLY',2,1200,0,0
        )`,
      ], "write");
      const result = await client.execute({
        sql: permitTimeseriesSql,
        args: ["EVENT_TYPE", "2026-08", "2026-08", null, null, null, null],
      });
      const actual = JSON.parse(String(result.rows[0]?.payload)) as {
        groupBy: string;
        quality: { permitCount: number };
        series: Array<{ key: string; points: unknown[] }>;
      };
      expect(actual.groupBy).toBe("EVENT_TYPE");
      expect(actual.quality.permitCount).toBe(2);
      expect(actual.series).toEqual([
        expect.objectContaining({ key: "PERMIT", points: [expect.any(Object)] }),
      ]);
    } finally {
      client.close();
    }
  });

  it("uses the KST month at the UTC midnight boundary and excludes a future KST month", async () => {
    const client = createClient({ url: "file::memory:" });
    try {
      await client.batch([
        `CREATE TABLE serving_v2_building_permit_monthly(
          source_id TEXT,event_month TEXT,event_type TEXT,district_name TEXT,
          asset_type TEXT,scope_status TEXT,construction_action TEXT,
          permit_count INTEGER,total_floor_area_m2 REAL,
          missing_area_count INTEGER,invalid_area_count INTEGER
        )`,
        `CREATE TABLE serving_dataset_freshness(
          dataset_code TEXT PRIMARY KEY,source_code TEXT,source_as_of_date TEXT,
          generated_at TEXT,source_status_code TEXT,source_row_count INTEGER,
          serving_row_count INTEGER,content_sha256 TEXT,metadata_json TEXT
        )`,
        `INSERT INTO serving_dataset_freshness VALUES(
          'SEOUL_BUILDING_PERMITS','src_seoul_building_permit','2026-09-01',
          '2026-08-31T15:30:00Z','READY',2,2,lower(hex(randomblob(32))),'{}'
        )`,
        `INSERT INTO serving_v2_building_permit_monthly VALUES
          ('src_seoul_building_permit','2026-09','PERMIT','강남구','OFFICE',
           'IN_SCOPE','NEW_SUPPLY',2,1200,0,0),
          ('src_seoul_building_permit','2026-10','PERMIT','강남구','OFFICE',
           'IN_SCOPE','NEW_SUPPLY',99,9900,0,0)`,
      ], "write");
      const boundarySql = permitTimeseriesSql.replaceAll(
        "'now'", "'2026-08-31T15:30:00Z'",
      );
      const result = await client.execute({
        sql: boundarySql,
        args: ["EVENT_TYPE", null, null, null, null, null, null],
      });
      const actual = JSON.parse(String(result.rows[0]?.payload)) as {
        availableThrough: string;
        selectedThrough: string;
        quality: { permitCount: number };
      };
      expect(actual.availableThrough).toBe("2026-09");
      expect(actual.selectedThrough).toBe("2026-09");
      expect(actual.quality.permitCount).toBe(2);
    } finally {
      client.close();
    }
  });
});
