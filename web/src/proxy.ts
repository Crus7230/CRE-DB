import { NextRequest, NextResponse } from "next/server";
import { createSessionToken, SESSION_COOKIE, shouldBypassAuth } from "@/lib/server/auth-session";

export function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (shouldBypassAuth(pathname)) return NextResponse.next();

  const accessCode = process.env.DASHBOARD_ACCESS_CODE;
  const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;
  if (!accessCode || !sessionSecret) {
    return new NextResponse("Dashboard access authentication is not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  const supplied = request.cookies.get(SESSION_COOKIE)?.value ?? "";
  const expected = createSessionToken(accessCode, sessionSecret);
  if (supplied === expected) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "인증이 필요합니다." }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const loginUrl = new URL("/login", request.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/image|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
