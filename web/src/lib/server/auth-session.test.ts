import { describe, expect, it } from "vitest";
import { createSessionToken, isValidAccessCode, shouldBypassAuth } from "@/lib/server/auth-session";

describe("dashboard access-code session", () => {
  it("creates a deterministic signed token without exposing the access code", () => {
    const token = createSessionToken("team-code", "session-secret");
    expect(token).toMatch(/^[a-f0-9]{64}$/);
    expect(token).toBe(createSessionToken("team-code", "session-secret"));
    expect(token).not.toContain("team-code");
    expect(token).not.toBe(createSessionToken("team-code", "other-secret"));
  });

  it("compares access codes without accepting length or value mismatches", () => {
    expect(isValidAccessCode("correct-code", "correct-code")).toBe(true);
    expect(isValidAccessCode("wrong-code", "correct-code")).toBe(false);
    expect(isValidAccessCode("short", "correct-code")).toBe(false);
  });

  it("bypasses only login and framework assets", () => {
    expect(shouldBypassAuth("/login")).toBe(true);
    expect(shouldBypassAuth("/api/auth/login")).toBe(true);
    expect(shouldBypassAuth("/_next/static/chunk.js")).toBe(true);
    expect(shouldBypassAuth("/favicon.ico")).toBe(true);
    expect(shouldBypassAuth("/")).toBe(false);
    expect(shouldBypassAuth("/api/search")).toBe(false);
  });
});
