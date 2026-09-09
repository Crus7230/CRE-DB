import { NextRequest, NextResponse } from "next/server";
import { isValidSessionSecret, SESSION_COOKIE, shouldBypassAuth, verifySessionToken } from "@/lib/server/auth-session";
import { authorizeDashboardSubject } from "@/lib/server/db";
import { createSubjectAuthorizationCache } from "@/lib/server/subject-authorization-cache";

const authorizeSubject = createSubjectAuthorizationCache(authorizeDashboardSubject);

function withAuthorizationTiming(response: NextResponse, startedAt: number) {
  // Do not overwrite the route's `Server-Timing: data` metric. Proxy response
  // headers are applied after the route response on hosted Next deployments.
  response.headers.set("X-CRE-Authz-Ms", Math.max(0, performance.now() - startedAt).toFixed(1));
  return response;
}

export async function proxy(request: NextRequest) {
  const authorizationStartedAt = performance.now();
  const { pathname } = request.nextUrl;
  if (shouldBypassAuth(pathname)) return NextResponse.next();

  const sessionSecret = process.env.DASHBOARD_SESSION_SECRET;
  if (!sessionSecret || !isValidSessionSecret(sessionSecret)) {
    return new NextResponse("Dashboard access authentication is not configured.", { status: 503, headers: { "Cache-Control": "no-store" } });
  }

  const supplied = request.cookies.get(SESSION_COOKIE)?.value ?? "";
  const claims=await verifySessionToken(supplied,sessionSecret);
  if(claims){
    try {
      const authorization=await authorizeSubject(claims.subjectId);
      if(authorization.allowed) return withAuthorizationTiming(NextResponse.next(),authorizationStartedAt);
    }
    catch { return withAuthorizationTiming(new NextResponse("Dashboard access authorization is unavailable.",{status:503,headers:{"Cache-Control":"no-store"}}),authorizationStartedAt); }
  }

  if (pathname.startsWith("/api/")) {
    return withAuthorizationTiming(NextResponse.json({ error: "인증이 필요합니다." }, { status: 401, headers: { "Cache-Control": "no-store" } }),authorizationStartedAt);
  }

  const loginUrl = new URL("/login", request.url);
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/((?!_next/image|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)"],
};
