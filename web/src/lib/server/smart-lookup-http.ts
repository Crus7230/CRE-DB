import "server-only";
import fs from "node:fs";
import { LookupProviderError, type LookupContext, type LookupCredentials } from "@/lib/server/smart-lookup-types";

const ENV_NAMES = {
  VWORLD_KEY: "vworldKey", DATA_GO_KR_KEY: "publicDataKey", DART_API_KEY: "dartKey", KRX_API_KEY: "krxKey",
} as const;
const HOSTS = new Set(["api.vworld.kr", "apis.data.go.kr", "opendart.fss.or.kr", "data-dbg.krx.co.kr"]);

export function readLookupCredentials(): LookupCredentials {
  const result: LookupCredentials = {};
  // Deployment uses runtime secrets. A workstation may explicitly use its
  // existing external authority; values are never put in the source tree.
  const envFile = process.env.SMART_LOOKUP_ENV_FILE
    ?? (!process.env.VERCEL && process.platform === "win32" ? "C:/10137_WorkSpace/env/.env" : undefined);
  const local: Record<string, string> = {};
  if (envFile && !process.env.VERCEL) {
    try {
      for (const line of fs.readFileSync(envFile, "utf8").replace(/^\uFEFF/, "").split(/\r?\n/)) {
        const match = line.match(/^\s*(?:export\s+)?([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
        if (match && Object.hasOwn(ENV_NAMES, match[1])) local[match[1]] = match[2].replace(/^(["'])(.*)\1$/, "$2");
      }
    } catch { /* Missing authority is shown as an unconfigured provider. */ }
  }
  for (const [name, field] of Object.entries(ENV_NAMES)) {
    const value = (process.env[name] ?? local[name])?.trim();
    if (value) result[field] = value;
  }
  return result;
}

export function validateProviderUrl(raw: string) {
  let url: URL;
  try { url = new URL(raw); } catch { throw new LookupProviderError("configuration"); }
  if (url.protocol !== "https:" || !HOSTS.has(url.hostname) || url.username || url.password || (url.port && url.port !== "443")) {
    throw new LookupProviderError("configuration");
  }
  return url;
}

export async function requestProviderBytes(raw: string, init: RequestInit = {}, fetcher: typeof fetch = fetch, timeoutMs = 15_000): Promise<Uint8Array> {
  const url = validateProviderUrl(raw);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1, Math.min(15_000, timeoutMs)));
  const maxBytes = 16 * 1024 * 1024;
  try {
    const requestInit: RequestInit = { ...init, cache: "no-store", redirect: "error", signal: controller.signal };
    let response = await fetcher(url, requestInit);
    // Public gateways sometimes return a transient cold-request 503. One retry
    // shares the same 15-second budget; auth and quota failures are not retried.
    if ([502, 503, 504].includes(response.status)) {
      await response.body?.cancel().catch(() => undefined);
      await new Promise(resolve => setTimeout(resolve, 250));
      if (controller.signal.aborted) throw new LookupProviderError("timeout");
      response = await fetcher(url, requestInit);
    }
    if (!response.ok) throw new LookupProviderError("http");
    if (Number(response.headers.get("content-length")) > maxBytes) throw new LookupProviderError("too_large");
    if (!response.body) throw new LookupProviderError("invalid_response");
    const reader = response.body.getReader();
    const chunks: Uint8Array[] = [];
    let size = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > maxBytes) throw new LookupProviderError("too_large");
        chunks.push(value);
      }
    } finally { await reader.cancel().catch(() => undefined); }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.length; }
    return bytes;
  } catch (error) {
    if (controller.signal.aborted) throw new LookupProviderError("timeout");
    if (error instanceof LookupProviderError) throw error;
    // Provider URLs often contain API keys. Never rethrow the native error.
    throw new LookupProviderError("http");
  } finally { clearTimeout(timer); }
}

export function createLookupContext(credentials = readLookupCredentials()): LookupContext {
  let requests = 0;
  const deadline = Date.now() + 35_000;
  const requestBytes = (url: string, init?: RequestInit) => {
    const remaining = deadline - Date.now();
    if (remaining <= 0) throw new LookupProviderError("timeout");
    if (++requests > 18) throw new LookupProviderError("too_large");
    return requestProviderBytes(url, init, fetch, remaining);
  };
  return {
    credentials, now: () => new Date(), requestBytes,
    requestJson: async (url, init) => {
      const bytes = await requestBytes(url, init);
      try { return JSON.parse(new TextDecoder().decode(bytes)) as unknown; }
      catch { throw new LookupProviderError("invalid_response"); }
    },
  };
}
