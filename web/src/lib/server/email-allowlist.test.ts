import { createClient } from "@libsql/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  findAllowedSubjectId,
  isAllowedSubjectId,
  type AuthSqlExecutor,
} from "@/lib/server/email-allowlist";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const clients: Array<ReturnType<typeof createClient>> = [];

afterEach(() => {
  for (const client of clients.splice(0)) client.close();
});

describe("approved email lookup", () => {
  it("uses one normalized bind parameter against the Turso allowlist table", async () => {
    const executor: AuthSqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ subject_id: SUBJECT_ID }],
    });
    const subjectId = await findAllowedSubjectId(executor, "  Person@Example.COM ");

    expect(subjectId).toBe(SUBJECT_ID);
    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).toContain("FROM dashboard_access_allowlist");
    expect(sql).toContain("is_enabled = 1");
    expect(sql).toContain("revoked_at IS NULL");
    expect(sql).toContain("datetime(access_expires_at) > CURRENT_TIMESTAMP");
    expect(sql).not.toContain("app_security.");
    expect(sql).not.toMatch(/::|clock_timestamp/u);
    expect(sql).not.toContain("person@example.com");
    expect(values).toEqual(["person@example.com"]);
  });

  it("checks a signed subject with an uncast SQLite bind parameter", async () => {
    const executor: AuthSqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ subject_id: SUBJECT_ID }],
    });

    expect(await isAllowedSubjectId(executor, SUBJECT_ID)).toBe(true);
    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).toContain("access_subject_id = ?");
    expect(sql).not.toContain("::uuid");
    expect(values).toEqual([SUBJECT_ID]);
  });

  it("returns the same empty result for missing or disabled entries", async () => {
    const executor: AuthSqlExecutor = vi.fn().mockResolvedValue({ rows: [] });
    expect(await findAllowedSubjectId(executor, "missing@example.com")).toBeNull();
  });

  it("does not query Turso for malformed email input", async () => {
    const executor: AuthSqlExecutor = vi.fn();
    expect(await findAllowedSubjectId(executor, "not-an-email")).toBeNull();
    expect(executor).not.toHaveBeenCalled();
  });

  it("enforces enabled, revoked, and expiration state against real libSQL", async () => {
    const client = createClient({ url: "file::memory:" });
    clients.push(client);
    await client.execute(`
      CREATE TABLE dashboard_access_allowlist(
        access_subject_id TEXT PRIMARY KEY,
        email_normalized TEXT NOT NULL UNIQUE,
        is_enabled INTEGER NOT NULL,
        revoked_at TEXT,
        access_expires_at TEXT
      )
    `);
    await client.batch([
      {
        sql: `INSERT INTO dashboard_access_allowlist VALUES (?, ?, 1, NULL, datetime('now', '+1 day'))`,
        args: [SUBJECT_ID, "active@example.com"],
      },
      {
        sql: `INSERT INTO dashboard_access_allowlist VALUES (?, ?, 1, NULL, datetime('now', '-1 day'))`,
        args: ["14bda25a-5a93-48e5-9512-8f679508d831", "expired@example.com"],
      },
      {
        sql: `INSERT INTO dashboard_access_allowlist VALUES (?, ?, 0, NULL, NULL)`,
        args: ["b4791592-d650-40fc-91af-da1d3cdf48dc", "disabled@example.com"],
      },
      {
        sql: `INSERT INTO dashboard_access_allowlist VALUES (?, ?, 1, CURRENT_TIMESTAMP, NULL)`,
        args: ["8df372b5-b513-430d-a285-af58a9221c8e", "revoked@example.com"],
      },
    ], "write");
    const execute: AuthSqlExecutor = async (sql, args) => {
      const result = await client.execute({ sql, args: [...args] });
      return { rows: result.rows.map((row) => Object.fromEntries(Object.entries(row))) };
    };

    expect(await findAllowedSubjectId(execute, "active@example.com")).toBe(SUBJECT_ID);
    expect(await isAllowedSubjectId(execute, SUBJECT_ID)).toBe(true);
    expect(await findAllowedSubjectId(execute, "expired@example.com")).toBeNull();
    expect(await findAllowedSubjectId(execute, "disabled@example.com")).toBeNull();
    expect(await findAllowedSubjectId(execute, "revoked@example.com")).toBeNull();
  });
});
