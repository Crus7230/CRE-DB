import type { AuthSqlExecutor } from "@/lib/server/email-allowlist";

const encoder = new TextEncoder();

const PRUNE = `
DELETE FROM dashboard_login_rate_limits
WHERE unixepoch(updated_at) < unixepoch('now', '-7 days')`;

// A single INSERT statement consumes both keys, so SQLite applies both limiter
// mutations atomically even when concurrent login requests target the same row.
const CONSUME = `
WITH requested_keys(rate_limit_key) AS (
  SELECT ?
  UNION
  SELECT ?
)
INSERT INTO dashboard_login_rate_limits(
  rate_limit_key, window_started_at, attempt_count, blocked_until, updated_at
)
SELECT rate_limit_key, CURRENT_TIMESTAMP, 1, NULL, CURRENT_TIMESTAMP
FROM requested_keys
WHERE 1
ON CONFLICT(rate_limit_key) DO UPDATE SET
  window_started_at = CASE
    WHEN unixepoch(dashboard_login_rate_limits.window_started_at) < unixepoch('now', '-15 minutes')
      THEN CURRENT_TIMESTAMP
    ELSE dashboard_login_rate_limits.window_started_at
  END,
  attempt_count = CASE
    WHEN unixepoch(dashboard_login_rate_limits.window_started_at) < unixepoch('now', '-15 minutes')
      THEN 1
    ELSE dashboard_login_rate_limits.attempt_count + 1
  END,
  blocked_until = CASE
    WHEN unixepoch(dashboard_login_rate_limits.blocked_until) > unixepoch('now')
      THEN dashboard_login_rate_limits.blocked_until
    WHEN unixepoch(dashboard_login_rate_limits.window_started_at) < unixepoch('now', '-15 minutes')
      THEN NULL
    WHEN dashboard_login_rate_limits.attempt_count + 1 >= 10
      THEN datetime('now', '+15 minutes')
    ELSE NULL
  END,
  updated_at = CURRENT_TIMESTAMP
RETURNING rate_limit_key,
  CASE WHEN unixepoch(blocked_until) > unixepoch('now') THEN 1 ELSE 0 END AS blocked`;

const CLEAR = `
DELETE FROM dashboard_login_rate_limits
WHERE rate_limit_key IN (?, ?)`;

export async function loginRateLimitKeys(request: Request, sessionSecret: string, email: string) {
  const forwarded = (request.headers.get("x-vercel-forwarded-for") ?? "").split(",")[0]?.trim()
    || request.headers.get("x-real-ip")
    || (request.headers.get("x-forwarded-for") ?? "").split(",")[0]?.trim()
    || "unknown";
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(sessionSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  const values = [`login-ip:${forwarded}`, `login-account:${email || "invalid"}`];
  return Promise.all(values.map(async (value) => Buffer.from(
    await crypto.subtle.sign("HMAC", key, encoder.encode(value)),
  ).toString("base64url")));
}

function normalizedKeyPair(keys: readonly string[]) {
  if (keys.some((key) => !key)) throw new Error("Login rate-limit keys must be non-empty");
  const unique = [...new Set(keys)];
  if (unique.length === 0 || unique.length > 2) {
    throw new Error("Login rate limiting requires one or two unique keys");
  }
  return {
    pair: [unique[0], unique[1] ?? unique[0]] as [string, string],
    unique,
  };
}

function blockedValue(value: unknown) {
  if (value === true || value === 1 || (typeof value === "bigint" && value === BigInt(1))) return true;
  if (value === false || value === 0 || (typeof value === "bigint" && value === BigInt(0))) return false;
  throw new Error("Login rate-limit result is invalid");
}

export async function consumeLoginAttempts(execute: AuthSqlExecutor, keys: readonly string[]) {
  const { pair, unique } = normalizedKeyPair(keys);
  await execute(PRUNE, []);
  const result = await execute(CONSUME, pair);
  if (result.rows.length !== unique.length) {
    throw new Error("Login rate-limit update was incomplete");
  }

  const returnedKeys = new Set<string>();
  let blocked = false;
  for (const row of result.rows) {
    if (typeof row.rate_limit_key !== "string" || !unique.includes(row.rate_limit_key)) {
      throw new Error("Login rate-limit result has an unexpected key");
    }
    returnedKeys.add(row.rate_limit_key);
    blocked ||= blockedValue(row.blocked);
  }
  if (returnedKeys.size !== unique.length) {
    throw new Error("Login rate-limit update was incomplete");
  }
  return blocked;
}

export async function clearLoginAttempts(execute: AuthSqlExecutor, keys: readonly string[]) {
  const { pair } = normalizedKeyPair(keys);
  await execute(CLEAR, pair);
}
