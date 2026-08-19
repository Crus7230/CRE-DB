import { SESSION_COOKIE } from "@/lib/server/auth-session";

export async function POST() {
  return Response.json({ ok: true }, {
    headers: {
      "Set-Cookie": `${SESSION_COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax; Secure`,
      "Cache-Control": "no-store",
    },
  });
}
