import { NextRequest } from "next/server";
import { SESSION_COOKIE, isValidSessionSecret, verifySessionToken } from "@/lib/server/auth-session";
import { createLookupContext } from "@/lib/server/smart-lookup-http";
import { LookupInputError, runSmartLookup, validateLookupRequest } from "@/lib/server/smart-lookup";

export const runtime = "nodejs";
const windows = new Map<string, { start: number; count: number }>();
const headers = { "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff" };

async function readBoundedBody(request: NextRequest) {
  if (!request.body) throw new LookupInputError("검색 요청을 확인해 주세요.");
  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > 16384) throw new LookupInputError("검색 요청이 너무 큽니다.");
      chunks.push(value);
    }
  } finally { await reader.cancel().catch(() => undefined); }
  return Buffer.concat(chunks).toString("utf8");
}

export async function POST(request: NextRequest) {
  const secret = process.env.DASHBOARD_SESSION_SECRET ?? "";
  if (!isValidSessionSecret(secret)) return Response.json({ error: "접속 인증 설정을 확인해 주세요." }, { status: 503, headers });
  const session = await verifySessionToken(request.cookies.get(SESSION_COOKIE)?.value ?? "", secret);
  if (!session) return Response.json({ error: "로그인 후 조회해 주세요." }, { status: 401, headers });
  // The existing proxy additionally rechecks allowlist membership for this route.
  const origin = request.headers.get("origin");
  const requestUrl = new URL(request.url);
  // Next can reconstruct request.url with localhost while the browser uses
  // 127.0.0.1. Match the actual Host, without trusting forwarded-origin headers.
  const expectedOrigin = `${requestUrl.protocol}//${request.headers.get("host") ?? requestUrl.host}`;
  if (origin && origin !== expectedOrigin) return Response.json({ error: "허용되지 않은 요청입니다." }, { status: 403, headers });
  const now = Date.now();
  for (const [key, window] of windows) if (now - window.start >= 60_000) windows.delete(key);
  const window = windows.get(session.subjectId) ?? { start: now, count: 0 };
  if (window.count >= 20 || (!windows.has(session.subjectId) && windows.size >= 512)) return Response.json({ error: "조회가 많습니다. 1분 후 다시 시도해 주세요." }, { status: 429, headers: { ...headers, "Retry-After": "60" } });
  window.count++;
  windows.set(session.subjectId, window);
  try {
    if (!request.headers.get("content-type")?.includes("application/json")) throw new LookupInputError("JSON 요청이 필요합니다.");
    if (Number(request.headers.get("content-length")) > 16384) throw new LookupInputError("검색 요청이 너무 큽니다.");
    const body = await readBoundedBody(request);
    let payload: unknown;
    try { payload = JSON.parse(body); } catch { throw new LookupInputError("검색 요청을 확인해 주세요."); }
    const input = validateLookupRequest(payload);
    return Response.json(await runSmartLookup(input, createLookupContext(), session.subjectId, secret), { headers });
  } catch (error) {
    if (error instanceof LookupInputError) return Response.json({ error: error.message }, { status: 400, headers });
    // Do not log provider errors, query strings or any credential-bearing URLs.
    return Response.json({ error: "조회 중 문제가 발생했습니다. 잠시 후 다시 시도해 주세요." }, { status: 503, headers });
  }
}
