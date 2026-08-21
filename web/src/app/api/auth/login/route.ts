import {
  AUTH_REJECTED_MESSAGE,
  createSessionToken,
  isValidEmail,
  isValidSessionSecret,
  normalizeEmail,
  SESSION_COOKIE,
  SESSION_MAX_AGE_SECONDS,
  shouldUseSecureCookie,
} from "@/lib/server/auth-session";
import { executeAuthSql } from "@/lib/server/db";
import { findAllowedSubjectId } from "@/lib/server/email-allowlist";

export const runtime = "nodejs";

const NO_STORE_HEADERS = { "Cache-Control": "no-store" };
const MAX_LOGIN_BODY_BYTES = 4 * 1_024;

async function readLimitedBody(request: Request) {
  const declaredLength = Number(request.headers.get("content-length"));
  if (Number.isFinite(declaredLength) && declaredLength > MAX_LOGIN_BODY_BYTES) return null;
  if (!request.body) return new Uint8Array();

  const reader = request.body.getReader();
  const chunks: Uint8Array[] = [];
  let total = 0;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    total += value.byteLength;
    if (total > MAX_LOGIN_BODY_BYTES) {
      await reader.cancel();
      return null;
    }
    chunks.push(value);
  }

  const body = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    body.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return body;
}

export async function POST(request: Request) {
  const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;
  if (!sessionSecret || !isValidSessionSecret(sessionSecret)) {
    return Response.json({ error: "접근 인증이 구성되지 않았습니다." }, { status: 503, headers: NO_STORE_HEADERS });
  }

  let email = "";
  try {
    const bytes = await readLimitedBody(request);
    if (!bytes) {
      return Response.json({ error: "요청 크기가 너무 큽니다." }, { status: 413, headers: NO_STORE_HEADERS });
    }
    const body = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes)) as { email?: unknown };
    email = normalizeEmail(typeof body.email === "string" ? body.email : "");
  } catch {
    return Response.json({ error: "잘못된 요청입니다." }, { status: 400, headers: NO_STORE_HEADERS });
  }

  if (!isValidEmail(email)) {
    return Response.json({ error: AUTH_REJECTED_MESSAGE }, { status: 401, headers: NO_STORE_HEADERS });
  }

  let subjectId: string | null = null;
  try {
    subjectId = await findAllowedSubjectId(executeAuthSql, email);
  } catch {
    console.error("Dashboard email allowlist lookup failed");
    return Response.json({ error: "접근 인증을 확인하지 못했습니다." }, { status: 503, headers: NO_STORE_HEADERS });
  }

  if (!subjectId) {
    return Response.json({ error: AUTH_REJECTED_MESSAGE }, { status: 401, headers: NO_STORE_HEADERS });
  }

  const token = await createSessionToken(subjectId, sessionSecret);
  const secure = shouldUseSecureCookie(request.url);
  const cookie = `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${SESSION_MAX_AGE_SECONDS}; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`;
  return Response.json({ ok: true }, { headers: { "Set-Cookie": cookie, ...NO_STORE_HEADERS } });
}
