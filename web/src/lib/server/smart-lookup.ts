import "server-only";
import { createHash, createHmac, timingSafeEqual } from "node:crypto";
import { detectLookupKind, type LookupKind, type LookupRequest, type LookupResponse } from "@/lib/smart-lookup-contract";
import { searchAddresses, loadAddress } from "@/lib/server/smart-lookup-address";
import { searchCompanies, loadCompany } from "@/lib/server/smart-lookup-company";
import { LookupProviderError, type LookupContext, type ProviderCandidate, type ProviderResult } from "@/lib/server/smart-lookup-types";

type Selection = { candidate: ProviderCandidate; query: string; subject: string; expires: number };
const CACHE_LIMIT = 96;
const cache = new Map<string, { expires: number; value: ProviderResult }>();
const pending = new Map<string, Promise<ProviderResult>>();
export class LookupInputError extends Error {}

export function validateLookupRequest(value: unknown): LookupRequest {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new LookupInputError("검색어를 확인해 주세요.");
  const input = value as Record<string, unknown>;
  if (typeof input.query !== "string") throw new LookupInputError("주소나 회사명을 입력해 주세요.");
  const query = input.query.normalize("NFC").trim().replace(/\s+/g, " ");
  if (query.length < 2 || query.length > 100 || /[\u0000-\u001F\u007F<>]/.test(input.query)) {
    throw new LookupInputError("검색어는 2~100자로 입력해 주세요.");
  }
  const kind = input.kind ?? "auto";
  if (!["auto", "address", "company"].includes(String(kind))) throw new LookupInputError("검색 유형을 확인해 주세요.");
  if (input.selection !== undefined && (typeof input.selection !== "string" || input.selection.length > 8192)) {
    throw new LookupInputError("검색 결과를 다시 선택해 주세요.");
  }
  return { query, kind: kind as LookupKind, selection: input.selection as string | undefined };
}

export function signSelection(candidate: ProviderCandidate, query: string, subject: string, secret: string, now: number) {
  const payload = Buffer.from(JSON.stringify({ candidate, query, subject, expires: now + 15 * 60_000 } satisfies Selection)).toString("base64url");
  const signature = createHmac("sha256", secret).update(`lookup:${payload}`).digest("base64url");
  return `${payload}.${signature}`;
}

export function verifySelection(token: string, query: string, subject: string, secret: string, now: number): ProviderCandidate {
  try {
    const [payload, signature, extra] = token.split(".");
    if (extra !== undefined || !payload || !signature) throw new Error();
    const expected = createHmac("sha256", secret).update(`lookup:${payload}`).digest();
    const supplied = Buffer.from(signature, "base64url");
    if (supplied.length !== expected.length || !timingSafeEqual(expected, supplied)) throw new Error();
    const value = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as Selection;
    if (value.query !== query || value.subject !== subject || value.expires <= now || value.expires > now + 15 * 60_000) throw new Error();
    if (!["company", "address"].includes(value.candidate.kind)) throw new Error();
    return value.candidate;
  } catch { throw new LookupInputError("선택 결과가 만료되었거나 변경되었습니다. 다시 검색해 주세요."); }
}

async function cached(key: string, load: () => Promise<ProviderResult>, now: number): Promise<{ value: ProviderResult; hit: boolean }> {
  const existing = cache.get(key);
  if (existing && existing.expires > now) return { value: existing.value, hit: true };
  if (pending.has(key)) return { value: await pending.get(key)!, hit: true };
  if (pending.size >= 24) throw new LookupProviderError("too_large");
  const promise = load();
  pending.set(key, promise);
  try {
    const value = await promise;
    // Do not retain failures: setting up a key or fixing approval should recover immediately.
    if (value.sources.length && value.sources.every((source) => ["ok", "empty"].includes(source.status))) {
      if (cache.size >= CACHE_LIMIT) cache.delete(cache.keys().next().value!);
      cache.set(key, { value, expires: now + 5 * 60_000 });
    }
    return { value, hit: false };
  } finally { pending.delete(key); }
}

export async function runSmartLookup(input: LookupRequest, context: LookupContext, subject: string, secret: string): Promise<LookupResponse> {
  const now = context.now().getTime();
  const kind = input.kind === "auto" || !input.kind ? detectLookupKind(input.query) : input.kind;
  const candidate = input.selection ? verifySelection(input.selection, input.query, subject, secret, now) : undefined;
  if (candidate && kind !== "auto" && candidate.kind !== kind) throw new LookupInputError("검색 유형이 바뀌었습니다. 다시 검색해 주세요.");
  const credentialScope = createHash("sha256").update(JSON.stringify(context.credentials)).digest("hex");
  const key = createHash("sha256").update(JSON.stringify([credentialScope, kind, input.query, candidate?.identity])).digest("hex");
  const { value, hit } = await cached(key, async () => {
    const tasks: Array<{ kind: "address" | "company"; load: () => Promise<ProviderResult> }> = candidate
      ? [{ kind: candidate.kind, load: () => candidate.kind === "address" ? loadAddress(candidate.identity, context) : loadCompany(candidate.identity, context) }]
      : [
        ...(kind !== "company" ? [{ kind: "address" as const, load: () => searchAddresses(input.query, context) }] : []),
        ...(kind !== "address" ? [{ kind: "company" as const, load: () => searchCompanies(input.query, context) }] : []),
      ];
    const results = await Promise.all(tasks.map(async (task): Promise<ProviderResult> => {
      try { return await task.load(); }
      catch (error) {
        const timeout = error instanceof LookupProviderError && error.code === "timeout";
        return { candidates: [], cards: [], sources: [{ id: task.kind, label: task.kind === "address" ? "주소 조회" : "기업 조회", status: timeout ? "timeout" : "error", message: timeout ? "응답 시간이 초과되었습니다. 잠시 후 다시 조회해 주세요." : "원천기관 조회를 완료하지 못했습니다. 잠시 후 다시 조회해 주세요." }] };
      }
    }));
    return { candidates: results.flatMap((result) => result.candidates).slice(0, 20), cards: results.flatMap((result) => result.cards), sources: results.flatMap((result) => result.sources), message: results.map((result) => result.message).filter(Boolean).join(" ") || undefined };
  }, now);
  const candidates = value.candidates.map((item) => ({
    id: signSelection(item, input.query, subject, secret, now), kind: item.kind, title: item.title, subtitle: item.subtitle, sourceLabel: item.sourceLabel,
  }));
  const unavailable = value.sources.some((source) => ["error", "timeout", "unconfigured"].includes(source.status));
  return {
    query: input.query, kind: candidate?.kind ?? kind,
    stage: candidates.length ? "candidates" : value.cards.length ? "detail" : unavailable ? "unavailable" : "empty",
    candidates, cards: value.cards, sources: value.sources, queriedAt: new Date(now).toISOString(), cacheHit: hit,
    message: value.message ?? (candidates.length ? "정확한 주소 또는 기업을 선택해 주세요." : value.cards.length ? undefined : unavailable ? "조회하지 못한 출처가 있습니다. 아래 연결 상태를 확인해 주세요." : "일치하는 결과가 없습니다. 주소 또는 회사명을 더 구체적으로 입력해 주세요."),
  };
}
