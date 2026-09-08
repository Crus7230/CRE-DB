import { describe, expect, it, vi } from "vitest";
import { createSubjectAuthorizationCache } from "@/lib/server/subject-authorization-cache";

describe("subject authorization cache", () => {
  it("caches only an approved subject until the short TTL expires", async () => {
    let now = 1_000;
    const authorize = vi.fn().mockResolvedValueOnce(true).mockResolvedValueOnce(false);
    const cachedAuthorize = createSubjectAuthorizationCache(authorize, { ttlMs: 30_000, now: () => now });

    expect(await cachedAuthorize("subject-1")).toEqual({ allowed: true, cacheHit: false });
    now += 29_999;
    expect(await cachedAuthorize("subject-1")).toEqual({ allowed: true, cacheHit: true });
    expect(authorize).toHaveBeenCalledTimes(1);

    now += 1;
    expect(await cachedAuthorize("subject-1")).toEqual({ allowed: false, cacheHit: false });
    expect(authorize).toHaveBeenCalledTimes(2);
  });

  it("does not cache denied subjects or database failures", async () => {
    const authorize = vi.fn()
      .mockResolvedValueOnce(false)
      .mockRejectedValueOnce(new Error("database unavailable"))
      .mockResolvedValueOnce(true);
    const cachedAuthorize = createSubjectAuthorizationCache(authorize);

    expect(await cachedAuthorize("subject-2")).toEqual({ allowed: false, cacheHit: false });
    await expect(cachedAuthorize("subject-2")).rejects.toThrow("database unavailable");
    expect(await cachedAuthorize("subject-2")).toEqual({ allowed: true, cacheHit: false });
    expect(authorize).toHaveBeenCalledTimes(3);
  });

  it("coalesces concurrent lookups for the same signed subject", async () => {
    let resolveLookup: ((allowed: boolean) => void) | undefined;
    const authorize = vi.fn(() => new Promise<boolean>((resolve) => { resolveLookup = resolve; }));
    const cachedAuthorize = createSubjectAuthorizationCache(authorize);

    const first = cachedAuthorize("subject-3");
    const second = cachedAuthorize("subject-3");
    resolveLookup?.(true);

    expect(await first).toEqual({ allowed: true, cacheHit: false });
    expect(await second).toEqual({ allowed: true, cacheHit: true });
    expect(authorize).toHaveBeenCalledTimes(1);
  });
});
