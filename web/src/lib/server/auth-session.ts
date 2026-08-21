export const SESSION_COOKIE = "cre_db_session";
export const SESSION_MAX_AGE_SECONDS = 60 * 60 * 12;
export const AUTH_REJECTED_MESSAGE = "이메일 주소 또는 접속 권한을 확인해 주세요.";

const SESSION_VERSION = "v1";
const MAX_EMAIL_LENGTH = 254;
const MAX_TOKEN_LENGTH = 2_048;
const MIN_SESSION_SECRET_BYTES = 32;
const CLOCK_SKEW_SECONDS = 60;
const EMAIL_ADDRESS_PATTERN = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/u;
const encoder = new TextEncoder();
const decoder = new TextDecoder("utf-8", { fatal: true });

export type SessionClaims = {
  subjectId: string;
  issuedAt: number;
  expiresAt: number;
};

type SessionPayload = {
  sub: string;
  iat: number;
  exp: number;
};

export function normalizeEmail(candidate: string) {
  return candidate.trim().toLowerCase();
}

export function isValidSessionSecret(candidate: string) {
  return encoder.encode(candidate).byteLength >= MIN_SESSION_SECRET_BYTES;
}

export function shouldUseSecureCookie(requestUrl: string) {
  return new URL(requestUrl).protocol === "https:"
    || Boolean(process.env.VERCEL)
    || process.env.NODE_ENV === "production";
}

export function isValidEmail(candidate: string) {
  if (
    !candidate
    || candidate.length > MAX_EMAIL_LENGTH
    || candidate !== normalizeEmail(candidate)
    || /[\u0000-\u001F\u007F]/u.test(candidate)
  ) return false;
  const localPart = candidate.split("@", 1)[0] ?? "";
  return EMAIL_ADDRESS_PATTERN.test(candidate)
    && localPart.length <= 64
    && !localPart.startsWith(".")
    && !localPart.endsWith(".")
    && !localPart.includes("..");
}

function isValidSubjectId(candidate: string) {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu.test(candidate);
}

function bytesToBase64Url(bytes: Uint8Array) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/u, "");
}

function base64UrlToBytes(value: string) {
  if (!/^[A-Za-z0-9_-]+$/u.test(value)) return null;
  const standard = value.replace(/-/g, "+").replace(/_/g, "/");
  const padded = standard.padEnd(Math.ceil(standard.length / 4) * 4, "=");
  try {
    const binary = atob(padded);
    return Uint8Array.from(binary, (character) => character.charCodeAt(0));
  } catch {
    return null;
  }
}

async function sessionKey(sessionSecret: string) {
  return crypto.subtle.importKey(
    "raw",
    encoder.encode(sessionSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign", "verify"],
  );
}

export async function createSessionToken(subjectId: string, sessionSecret: string, now = new Date()) {
  if (!isValidSubjectId(subjectId) || !isValidSessionSecret(sessionSecret)) {
    throw new Error("Cannot create an invalid dashboard session");
  }

  const issuedAt = Math.floor(now.getTime() / 1_000);
  const payload: SessionPayload = {
    sub: subjectId.toLowerCase(),
    iat: issuedAt,
    exp: issuedAt + SESSION_MAX_AGE_SECONDS,
  };
  const payloadPart = bytesToBase64Url(encoder.encode(JSON.stringify(payload)));
  const signingInput = `${SESSION_VERSION}.${payloadPart}`;
  const signature = await crypto.subtle.sign("HMAC", await sessionKey(sessionSecret), encoder.encode(signingInput));
  return `${signingInput}.${bytesToBase64Url(new Uint8Array(signature))}`;
}

export async function verifySessionToken(token: string, sessionSecret: string, now = new Date()): Promise<SessionClaims | null> {
  if (!isValidSessionSecret(sessionSecret) || !token || token.length > MAX_TOKEN_LENGTH) return null;
  const [version, payloadPart, signaturePart, extra] = token.split(".");
  if (version !== SESSION_VERSION || !payloadPart || !signaturePart || extra !== undefined) return null;

  const payloadBytes = base64UrlToBytes(payloadPart);
  const signatureBytes = base64UrlToBytes(signaturePart);
  if (!payloadBytes || !signatureBytes) return null;

  const signingInput = `${version}.${payloadPart}`;
  const signatureIsValid = await crypto.subtle.verify(
    "HMAC",
    await sessionKey(sessionSecret),
    signatureBytes,
    encoder.encode(signingInput),
  );
  if (!signatureIsValid) return null;

  try {
    const payload = JSON.parse(decoder.decode(payloadBytes)) as Partial<SessionPayload>;
    const nowSeconds = Math.floor(now.getTime() / 1_000);
    if (
      typeof payload.sub !== "string"
      || !isValidSubjectId(payload.sub)
      || !Number.isInteger(payload.iat)
      || !Number.isInteger(payload.exp)
      || (payload.iat as number) > nowSeconds + CLOCK_SKEW_SECONDS
      || (payload.exp as number) <= nowSeconds
      || (payload.exp as number) <= (payload.iat as number)
      || (payload.exp as number) - (payload.iat as number) > SESSION_MAX_AGE_SECONDS
    ) return null;

    return { subjectId: payload.sub, issuedAt: payload.iat as number, expiresAt: payload.exp as number };
  } catch {
    return null;
  }
}

export function shouldBypassAuth(pathname: string) {
  return pathname === "/login"
    || pathname === "/favicon.ico"
    || pathname === "/api/auth/login"
    || pathname === "/api/auth/logout"
    || pathname.startsWith("/_next/");
}
