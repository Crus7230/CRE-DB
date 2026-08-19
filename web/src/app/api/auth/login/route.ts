import { createSessionToken, isValidAccessCode, SESSION_COOKIE, SESSION_MAX_AGE_SECONDS } from "@/lib/server/auth-session";

export const runtime = "nodejs";

export async function POST(request: Request) {
  const accessCode = process.env.DASHBOARD_ACCESS_CODE;
  const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;
  if (!accessCode || !sessionSecret) {
    return Response.json({ error: "접근 인증이 구성되지 않았습니다." }, { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  let candidate = "";
  try {
    const body = await request.json() as { code?: unknown };
    candidate = typeof body.code === "string" ? body.code : "";
  } catch {
    return Response.json({ error: "잘못된 요청입니다." }, { status: 400, headers: { "Cache-Control": "no-store" } });
  }

  if (!isValidAccessCode(candidate, accessCode)) {
    return Response.json({ error: "접근코드가 올바르지 않습니다." }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const token = createSessionToken(accessCode, sessionSecret);
  const secure = new URL(request.url).protocol === "https:" || Boolean(process.env.VERCEL);
  const cookie = `${SESSION_COOKIE}=${token}; Path=/; Max-Age=${SESSION_MAX_AGE_SECONDS}; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`;
  return Response.json({ ok: true }, { headers: { "Set-Cookie": cookie, "Cache-Control": "no-store" } });
}
