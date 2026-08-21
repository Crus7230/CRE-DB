import { describe, expect, it } from "vitest";
import {
  createSessionToken,
  isValidEmail,
  isValidSessionSecret,
  normalizeEmail,
  SESSION_MAX_AGE_SECONDS,
  shouldBypassAuth,
  verifySessionToken,
} from "@/lib/server/auth-session";

const SUBJECT_ID = "49caafcd-f6c5-4d79-92bd-6f4cd968cf25";
const ISSUED_AT = new Date("2026-08-21T00:00:00Z");
const SESSION_SECRET = "0123456789abcdef0123456789abcdef";

describe("dashboard approved-email session", () => {
  it("normalizes and validates an email before an allowlist lookup", () => {
    expect(normalizeEmail("  Person@Example.COM ")).toBe("person@example.com");
    expect(normalizeEmail(" First.Last+CRE@Example.COM ")).toBe("first.last+cre@example.com");
    expect(isValidEmail("person@example.com")).toBe(true);
    expect(isValidEmail("first.last+cre@example.com")).toBe(true);
    expect(isValidEmail("person@example")).toBe(false);
    expect(isValidEmail(" person@example.com ")).toBe(false);
    expect(isValidEmail(".person@example.com")).toBe(false);
    expect(isValidEmail("person..name@example.com")).toBe(false);
    expect(isValidEmail("person@도메인.example")).toBe(false);
    expect(isValidEmail("person\u0000@example.com")).toBe(false);
    expect(isValidEmail("person\u007f@example.com")).toBe(false);
  });

  it("creates and verifies an expiring per-subject signed token", async () => {
    const token = await createSessionToken(SUBJECT_ID, SESSION_SECRET, ISSUED_AT);
    const claims = await verifySessionToken(token, SESSION_SECRET, new Date("2026-08-21T11:59:59Z"));

    expect(token).toMatch(/^v1\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/u);
    expect(token).not.toContain("person@example.com");
    expect(claims).toEqual({
      subjectId: SUBJECT_ID,
      issuedAt: Math.floor(ISSUED_AT.getTime() / 1_000),
      expiresAt: Math.floor(ISSUED_AT.getTime() / 1_000) + SESSION_MAX_AGE_SECONDS,
    });
  });

  it("rejects expired, tampered, and differently signed tokens", async () => {
    const token = await createSessionToken(SUBJECT_ID, SESSION_SECRET, ISSUED_AT);
    const tampered = `${token.slice(0, -1)}${token.endsWith("a") ? "b" : "a"}`;

    expect(await verifySessionToken(token, SESSION_SECRET, new Date("2026-08-21T12:00:00Z"))).toBeNull();
    expect(await verifySessionToken(tampered, SESSION_SECRET, ISSUED_AT)).toBeNull();
    expect(await verifySessionToken(token, "fedcba9876543210fedcba9876543210", ISSUED_AT)).toBeNull();
  });

  it("rejects session secrets shorter than 32 bytes", async () => {
    expect(isValidSessionSecret("short-secret")).toBe(false);
    expect(isValidSessionSecret(SESSION_SECRET)).toBe(true);
    await expect(createSessionToken(SUBJECT_ID, "short-secret", ISSUED_AT)).rejects.toThrow();
  });

  it("bypasses only login and framework assets", () => {
    expect(shouldBypassAuth("/login")).toBe(true);
    expect(shouldBypassAuth("/api/auth/login")).toBe(true);
    expect(shouldBypassAuth("/api/auth/logout")).toBe(true);
    expect(shouldBypassAuth("/api/auth/debug")).toBe(false);
    expect(shouldBypassAuth("/_next/static/chunk.js")).toBe(true);
    expect(shouldBypassAuth("/favicon.ico")).toBe(true);
    expect(shouldBypassAuth("/")).toBe(false);
    expect(shouldBypassAuth("/api/search")).toBe(false);
  });
});
