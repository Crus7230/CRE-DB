import { NextRequest, NextResponse } from "next/server";
import { isValidSessionSecret, SESSION_COOKIE, shouldBypassAuth, verifySessionToken } from "@/lib/server/auth-session";

export async function proxy(request: NextRequest) {
  const { pathname } = request.nextUrl;
  if (shouldBypassAuth(pathname)) return NextResponse.next();

  const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;
  if (!sessionSecret || !isValidSessionSecret(sessionSecret)) {
    return new NextResponse("Dashboard access authentication is not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  const supplied = request.cookies.get(SESSION_COOKIE)?.value ?? "";
  if (await verifySessionToken(supplied, sessionSecret)) return NextResponse.next();

  if (pathname.startsWith("/api/")) {
    return NextResponse.json({ error: "인증이 필요합니다." }, { status: 401, headers: { "Cache-Control": "no-store" } });
  }

  const loginUrl = new URL("/login", request.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/image|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
