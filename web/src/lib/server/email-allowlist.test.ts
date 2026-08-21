import { describe, expect, it, vi } from "vitest";
import { findAllowedSubjectId, type AuthSqlExecutor } from "@/lib/server/email-allowlist";

describe("approved email lookup", () => {
  it("uses one normalized bind parameter against the isolated security schema", async () => {
    const executor: AuthSqlExecutor = vi.fn().mockResolvedValue({
      rows: [{ subject_id: "49caafcd-f6c5-4d79-92bd-6f4cd968cf25" }],
    });
    const subjectId = await findAllowedSubjectId(executor, "  Person@Example.COM ");

    expect(subjectId).toBe("49caafcd-f6c5-4d79-92bd-6f4cd968cf25");
    const [sql, values] = vi.mocked(executor).mock.calls[0];
    expect(sql).toContain("app_security.dashboard_access_allowlist");
    expect(sql).toContain("is_enabled = TRUE");
    expect(sql).toContain("revoked_at IS NULL");
    expect(sql).toContain("access_expires_at IS NULL OR access_expires_at > clock_timestamp()");
    expect(sql).not.toContain("person@example.com");
    expect(values).toEqual(["person@example.com"]);
  });

  it("returns the same empty result for missing or disabled entries", async () => {
    const executor: AuthSqlExecutor = vi.fn().mockResolvedValue({ rows: [] });
    expect(await findAllowedSubjectId(executor, "missing@example.com")).toBeNull();
  });

  it("does not query PostgreSQL for malformed email input", async () => {
    const executor: AuthSqlExecutor = vi.fn();
    expect(await findAllowedSubjectId(executor, "not-an-email")).toBeNull();
    expect(executor).not.toHaveBeenCalled();
  });
});
