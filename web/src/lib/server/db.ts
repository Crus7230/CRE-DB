import "server-only";

import { createClient, type Client, type Row } from "@libsql/client";
import { createHash } from "node:crypto";
import fs from "node:fs";
import type { AuthSqlExecutor } from "@/lib/server/email-allowlist";
import type { SqlExecutor, SqlValue } from "@/lib/server/market-search";

const DEFAULT_AUTHORITY = String.raw`C:\10137_WorkSpace\env\.env.personal.txt`;

type TursoConfiguration = {
  url: string;
  authToken?: string;
};

function unquote(value: string) {
  const trimmed = value.trim();
  if (trimmed.length >= 2) {
    const first = trimmed[0];
    const last = trimmed.at(-1);
    if ((first === "\"" && last === "\"") || (first === "'" && last === "'")) {
      return trimmed.slice(1, -1);
    }
  }
  return trimmed;
}

function parseAuthority(text: string) {
  const values = new Map<string, string>();
  for (const rawLine of text.replace(/^\uFEFF/u, "").split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const rawName = line.slice(0, separator).trim();
    const name = rawName.startsWith("export ") ? rawName.slice(7).trim() : rawName;
    if (name !== "TURSO_DATABASE_URL" && name !== "TURSO_AUTH_TOKEN") continue;
    const value = unquote(line.slice(separator + 1));
    if (value) values.set(name, value);
  }
  return values;
}

function validateConfiguration(url: string | undefined, authToken: string | undefined): TursoConfiguration {
  const normalizedUrl = url?.trim();
  const normalizedToken = authToken?.trim();
  if (!normalizedUrl) throw new Error("TURSO_DATABASE_URL is not configured");
  if (!normalizedToken && !normalizedUrl.startsWith("file:")) {
    throw new Error("TURSO_AUTH_TOKEN is not configured");
  }
  return normalizedToken ? { url: normalizedUrl, authToken: normalizedToken } : { url: normalizedUrl };
}

function readConfiguration(): TursoConfiguration {
  const environmentUrl = process.env.TURSO_DATABASE_URL;
  const environmentToken = process.env.TURSO_AUTH_TOKEN;

  // Treat process.env as one authority. Mixing a URL from one authority with a
  // token from another could send a credential to the wrong database host.
  if (environmentUrl || environmentToken) {
    return validateConfiguration(environmentUrl, environmentToken);
  }

  const authority = process.env.TURSO_ENV_FILE ?? DEFAULT_AUTHORITY;
  const values = parseAuthority(
    fs.readFileSync(/* turbopackIgnore: true */ authority, "utf8"),
  );
  return validateConfiguration(
    values.get("TURSO_DATABASE_URL"),
    values.get("TURSO_AUTH_TOKEN"),
  );
}

type GlobalWithClient = typeof globalThis & {
  __marketLibsqlClient?: Client;
  __marketLibsqlClientFingerprint?: string;
};
const globalWithClient = globalThis as GlobalWithClient;
let moduleConfiguration: {
  value: TursoConfiguration;
  fingerprint: string;
  cacheAuthorityNamespace: string;
} | undefined;

function normalizeAuthorityUrl(rawUrl: string) {
  const trimmed = rawUrl.trim();
  try {
    const parsed = new URL(trimmed);
    // The database URL is not a credential in the supported configuration,
    // but strip userinfo/query/fragment defensively before deriving a cache
    // authority. The database scheme, host, port and path remain identity.
    parsed.username = "";
    parsed.password = "";
    parsed.search = "";
    parsed.hash = "";
    parsed.protocol = parsed.protocol.toLowerCase();
    parsed.hostname = parsed.hostname.toLowerCase();
    if (!parsed.pathname || parsed.pathname === "/") parsed.pathname = "/";
    else parsed.pathname = parsed.pathname.replace(/\/+$/u, "");
    return parsed.toString();
  } catch {
    // Validation remains the client's responsibility. This fallback is only
    // used to keep the cache namespace deterministic for its input string.
    return trimmed.replace(/\\/gu, "/").replace(/\/+$/u, "");
  }
}

function configuration() {
  if (moduleConfiguration) return moduleConfiguration;
  const value = readConfiguration();
  const fingerprint = createHash("sha256")
    .update(value.url)
    .update("\0")
    .update(value.authToken ?? "")
    .digest("hex")
    .slice(0, 16);
  const cacheAuthorityNamespace = `url-${createHash("sha256")
    .update(normalizeAuthorityUrl(value.url))
    .digest("hex")
    .slice(0, 16)}`;
  moduleConfiguration = { value, fingerprint, cacheAuthorityNamespace };
  return moduleConfiguration;
}

// Read lazily from request-time configuration. The value contains no token or
// raw URL and lets persistent Next caches distinguish a local QA file from the
// production Turso authority across rebuilds/restarts.
export function getMarketCacheAuthorityNamespace() {
  return configuration().cacheAuthorityNamespace;
}

export function isLocalMarketDatabaseAuthority() {
  return configuration().value.url.trim().toLowerCase().startsWith("file:");
}

function queryTimeoutMs() {
  const parsed = Number.parseInt(process.env.TURSO_QUERY_TIMEOUT_MS ?? "8000", 10);
  return Number.isFinite(parsed) ? Math.min(30_000, Math.max(1_000, parsed)) : 8_000;
}

export class DatabaseQueryTimeoutError extends Error {
  readonly code = "DATABASE_QUERY_TIMEOUT";

  constructor(readonly timeoutMs: number) {
    super("Database query timed out");
    this.name = "DatabaseQueryTimeoutError";
  }
}

function client() {
  const configured = configuration();
  if (
    globalWithClient.__marketLibsqlClient
    && globalWithClient.__marketLibsqlClientFingerprint !== configured.fingerprint
  ) {
    globalWithClient.__marketLibsqlClient.close();
    globalWithClient.__marketLibsqlClient = undefined;
  }
  if (!globalWithClient.__marketLibsqlClient) {
    globalWithClient.__marketLibsqlClient = createClient(configured.value);
    globalWithClient.__marketLibsqlClientFingerprint = configured.fingerprint;
  }
  return globalWithClient.__marketLibsqlClient;
}

function parsePayload(value: unknown) {
  if (typeof value !== "string") return value;
  try {
    return JSON.parse(value) as unknown;
  } catch {
    return value;
  }
}

function normalizeRows(rows: readonly Row[]) {
  return rows.map((row) => {
    const normalized: Record<string, unknown> = {};
    for (const [name, value] of Object.entries(row)) normalized[name] = value;
    if (Object.hasOwn(normalized, "payload")) {
      normalized.payload = parsePayload(normalized.payload);
    }
    return normalized;
  });
}

async function execute(text: string, values: readonly SqlValue[]) {
  const timeoutMs = queryTimeoutMs();
  let timeout: ReturnType<typeof setTimeout> | undefined;
  const timeoutResult = new Promise<never>((_resolve, reject) => {
    timeout = setTimeout(() => reject(new DatabaseQueryTimeoutError(timeoutMs)), timeoutMs);
  });
  const result = await Promise.race([
    client().execute({ sql: text, args: [...values] }),
    timeoutResult,
  ]).finally(() => {
    if (timeout) clearTimeout(timeout);
  });
  return { rows: normalizeRows(result.rows) };
}

export const executeMarketSql: SqlExecutor = async (text, values) => {
  const result = await execute(text, values);
  return { rows: result.rows as Array<{ payload: unknown }> };
};

export const executeAuthSql: AuthSqlExecutor = execute;
export const executeAuthWriteSql: AuthSqlExecutor = execute;
