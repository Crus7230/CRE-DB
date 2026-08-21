import { SESSION_COOKIE, shouldUseSecureCookie } from "@/lib/server/auth-session";

export async function POST(request: Request) {
  const secure = shouldUseSecureCookie(request.url);
  return Response.json({ ok: true }, {
    headers: {
      "Set-Cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax${secure ? "; Secure" : ""}`,
      "Cache-Control": "no-store",
    },
  });
}
