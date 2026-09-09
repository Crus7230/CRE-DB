// @vitest-environment node
import { afterEach, describe, expect, it, vi } from "vitest";
vi.mock("server-only", () => ({}));
import { createLookupContext, requestProviderBytes, validateProviderUrl } from "./smart-lookup-http";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("official provider HTTP boundary", () => {
  it("retries one transient gateway response using the same abort budget", async () => {
    const fetcher = vi.fn().mockResolvedValueOnce(new Response("", { status: 503 })).mockResolvedValueOnce(new Response("{}"));
    await expect(requestProviderBytes("https://apis.data.go.kr/test", {}, fetcher)).resolves.toBeInstanceOf(Uint8Array);
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(fetcher.mock.calls[0][1].signal).toBe(fetcher.mock.calls[1][1].signal);
  });
  it("does not retry authentication or quota errors", async () => {
    for (const status of [401, 403, 429]) {
      const fetcher = vi.fn().mockResolvedValue(new Response("", { status }));
      await expect(requestProviderBytes("https://apis.data.go.kr/test", {}, fetcher)).rejects.toThrow("http");
      expect(fetcher).toHaveBeenCalledOnce();
    }
  });
  it("never retries a gateway failure more than once", async () => {
    const fetcher = vi.fn(async () => new Response("", { status: 503 }));
    await expect(requestProviderBytes("https://apis.data.go.kr/test", {}, fetcher)).rejects.toThrow("http");
    expect(fetcher).toHaveBeenCalledTimes(2);
  });
  it("only allows HTTPS requests to known official hosts", () => {
    expect(validateProviderUrl("https://opendart.fss.or.kr/api/company.json").hostname).toBe("opendart.fss.or.kr");
    for (const url of ["http://api.vworld.kr/req/search", "https://localhost/", "https://apis.data.go.kr.evil.test/", "https://user:pass@apis.data.go.kr/", "https://apis.data.go.kr:444/", "file:///C:/secret"]) {
      expect(() => validateProviderUrl(url)).toThrow("configuration");
    }
  });
  it("does not follow redirects or leak underlying errors", async () => {
    const fetcher = vi.fn().mockRejectedValue(new Error("URL with credential super-secret"));
    await expect(requestProviderBytes("https://apis.data.go.kr/test", {}, fetcher)).rejects.toThrow("http");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ redirect: "error", cache: "no-store" });
  });
  it("rejects oversized responses before downloading them", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("{}", { headers: { "content-length": String(32 * 1024 * 1024) } }));
    await expect(requestProviderBytes("https://api.vworld.kr/req/search", {}, fetcher)).rejects.toThrow("too_large");
  });
  it("reads bounded response streams", async () => {
    const fetcher = vi.fn().mockResolvedValue(new Response("공식자료"));
    const result = await requestProviderBytes("https://api.vworld.kr/req/search", {}, fetcher);
    expect(new TextDecoder().decode(result)).toBe("공식자료");
  });

  it("applies one 35-second deadline across sequential provider requests", async () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-08T00:00:00.000Z"));
    const fetcher = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    const context = createLookupContext({});

    await expect(context.requestJson("https://opendart.fss.or.kr/api/company.json")).resolves.toEqual({});
    vi.advanceTimersByTime(35_001);

    expect(() => context.requestBytes("https://opendart.fss.or.kr/api/company.json")).toThrow("timeout");
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("rejects the nineteenth provider request without issuing another fetch", async () => {
    const fetcher = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetcher);
    const context = createLookupContext({});

    for (let index = 0; index < 18; index += 1) {
      await expect(context.requestJson("https://opendart.fss.or.kr/api/company.json")).resolves.toEqual({});
    }
    expect(() => context.requestBytes("https://opendart.fss.or.kr/api/company.json")).toThrow("too_large");
    expect(fetcher).toHaveBeenCalledTimes(18);
  });
});
