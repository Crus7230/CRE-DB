import { createHmac, timingSafeEqual } from "node:crypto";

export const SESSION_COOKIE = "cre_db_session";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 12;

export function createSessionToken(accessCode: string, sessionSecret: string) {
  return createHmac("sha256", sessionSecret).update(accessCode, "utf8").digest("hex");
}

export function isValidAccessCode(candidate: string, expected: string) {
  const candidateBuffer = Buffer.from(candidate, "utf8");
  const expectedBuffer = Buffer.from(expected, "utf8");
  return candidateBuffer.length === expectedBuffer.length && timingSafeEqual(candidateBuffer, expectedBuffer);
}

export function shouldBypassAuth(pathname: string) {
  return pathname === "/login"
    || pathname === "/favicon.ico"
    || pathname.startsWith("/api/auth/")
    || pathname.startsWith("/_next/");
}
