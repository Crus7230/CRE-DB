import "server-only";

import { createClient, type Client, type Row } from "@libsql/client";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { fileURLToPath } from "node:url";
import type { SqlExecutor, SqlValue } from "@/lib/server/market-search";

const DEFAULT_AUTHORITY = String.raw`C:\10137_WorkSpace\env\.env.personal.txt`;
const CONFIGURATION_NAMES = new Set([
  "DASHBOARD_DATA_PROVIDER",
  "DASHBOARD_HOSTED_DEPLOYMENT",
  "DASHBOARD_DATASET_VERSION",
  "DASHBOARD_QUERY_TIMEOUT_MS",
  "SUPABASE_URL",
  "SUPABASE_PROJECT_REF",
  "SUPABASE_SECRET_KEY",
  "SUPABASE_PUBLISHABLE_KEY",
  "SUPABASE_DB_SCHEMA",
  "DASHBOARD_SUPABASE_RPC_SCHEMA",
  "TURSO_DATABASE_URL",
  "NEWS_DATABASE_URL",
  "TIMESERIES_DATABASE_URL",
]);

export type DashboardDataProvider = "supabase" | "sqlite";
type DatabaseDomain = "market" | "news" | "timeseries";
type SqliteConfiguration = { url: string };
type SupabaseConfiguration = {
  url: string;
  projectRef: string;
  apiKey: string;
  schema: "public";
};

export type ServingManifest = {
  datasetVersion: string;
  sourceAsOfAt: string | null;
  activatedAt: string | null;
  schemaVersion: string | null;
  rowCounts: Record<string, number>;
  tableHashes: Record<string, string>;
};

type DatabaseDiagnostics = {
  dataRpcCalls: number;
  manifestRpcCalls: number;
  authRpcCalls: number;
  sqliteDataQueries: number;
  sqliteAuthQueries: number;
};

const diagnostics: DatabaseDiagnostics = {
  dataRpcCalls: 0,
  manifestRpcCalls: 0,
  authRpcCalls: 0,
  sqliteDataQueries: 0,
  sqliteAuthQueries: 0,
};

export function getDatabaseDiagnostics(): Readonly<DatabaseDiagnostics> {
  return { ...diagnostics };
}

export function resetDatabaseDiagnostics() {
  for (const key of Object.keys(diagnostics) as Array<keyof DatabaseDiagnostics>) diagnostics[key] = 0;
}

export class DatabaseConfigurationError extends Error {
  readonly code = "DATABASE_CONFIGURATION_ERROR";

  constructor(message: string) {
    super(message);
    this.name = "DatabaseConfigurationError";
  }
}

export class DatabaseQueryTimeoutError extends Error {
  readonly code = "DATABASE_QUERY_TIMEOUT";

  constructor(readonly timeoutMs: number) {
    super("Database query timed out");
    this.name = "DatabaseQueryTimeoutError";
  }
}

export class DatabaseRequestError extends Error {
  readonly code = "DATABASE_REQUEST_FAILED";

  constructor(readonly status: number) {
    super("Database request failed");
    this.name = "DatabaseRequestError";
  }
}

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

// Duplicate keys are intentional in the personal authority during migrations.
// Last assignment wins, matching dotenv/Vercel override semantics.
export function parseDatabaseAuthority(text: string) {
  const values = new Map<string, string>();
  for (const rawLine of text.replace(/^\uFEFF/u, "").split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const rawName = line.slice(0, separator).trim();
    const name = rawName.startsWith("export ") ? rawName.slice(7).trim() : rawName;
    if (!CONFIGURATION_NAMES.has(name)) continue;
    const parsed = unquote(line.slice(separator + 1));
    if (parsed) values.set(name, parsed);
  }
  return values;
}

function authorityFileValues() {
  const authority = process.env.DASHBOARD_ENV_FILE ?? process.env.TURSO_ENV_FILE ?? DEFAULT_AUTHORITY;
  try {
    return parseDatabaseAuthority(fs.readFileSync(/* turbopackIgnore: true */ authority, "utf8"));
  } catch (error) {
    throw new DatabaseConfigurationError(
      `Dashboard database authority could not be read: ${error instanceof Error ? error.name : "UnknownError"}`,
    );
  }
}

function processAuthorityValues() {
  const values = new Map<string, string>();
  for (const name of CONFIGURATION_NAMES) {
    const candidate = process.env[name]?.trim();
    if (candidate) values.set(name, candidate);
  }
  return values;
}

let moduleAuthorityValues: Map<string, string> | undefined;
function authorityValues() {
  if (moduleAuthorityValues) return moduleAuthorityValues;
  const environment = processAuthorityValues();
  // Never combine a URL/key/provider from Vercel with a credential from a local
  // authority file. An environment containing any data authority is complete.
  const environmentOwnsAuthority = [
    "DASHBOARD_DATA_PROVIDER", "SUPABASE_URL", "SUPABASE_SECRET_KEY",
    "SUPABASE_PUBLISHABLE_KEY", "TURSO_DATABASE_URL", "NEWS_DATABASE_URL",
    "TIMESERIES_DATABASE_URL",
  ].some((name) => environment.has(name));
  moduleAuthorityValues = environmentOwnsAuthority ? environment : authorityFileValues();
  return moduleAuthorityValues;
}

function value(name: string) {
  return authorityValues().get(name)?.trim();
}

function isHostedDeployment() {
  return Boolean(process.env.VERCEL) || value("DASHBOARD_HOSTED_DEPLOYMENT") === "1";
}

let moduleProvider: DashboardDataProvider | undefined;
export function getDashboardDataProvider(): DashboardDataProvider {
  if (moduleProvider) return moduleProvider;
  const configured = value("DASHBOARD_DATA_PROVIDER")?.toLowerCase();
  if (configured !== "supabase" && configured !== "sqlite") {
    throw new DatabaseConfigurationError(
      "DASHBOARD_DATA_PROVIDER must be explicitly configured as supabase or sqlite",
    );
  }
  if (configured === "sqlite" && isHostedDeployment()) {
    throw new DatabaseConfigurationError(
      "Hosted dashboard deployments require DASHBOARD_DATA_PROVIDER=supabase",
    );
  }
  moduleProvider = configured;
  return configured;
}

function queryTimeoutMs() {
  const parsed = Number.parseInt(value("DASHBOARD_QUERY_TIMEOUT_MS") ?? "8000", 10);
  return Number.isFinite(parsed) ? Math.min(30_000, Math.max(1_000, parsed)) : 8_000;
}

function validProjectRef(candidate: string) {
  return /^[a-z0-9]{20}$/u.test(candidate);
}

function projectRefFromUrl(url: URL) {
  const match = url.hostname.toLowerCase().match(/^([a-z0-9]{20})\.supabase\.co$/u);
  return match?.[1] ?? null;
}

function projectRefFromLegacyJwt(apiKey: string) {
  if (!apiKey.startsWith("eyJ")) return null;
  const payload = apiKey.split(".")[1];
  if (!payload) return null;
  try {
    const decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      ref?: unknown;
      iss?: unknown;
    };
    if (typeof decoded.ref === "string" && validProjectRef(decoded.ref)) return decoded.ref;
    if (typeof decoded.iss === "string") {
      const issuerMatch = decoded.iss.match(/https:\/\/([a-z0-9]{20})\.supabase\.co/u);
      return issuerMatch?.[1] ?? null;
    }
  } catch {
    return null;
  }
  return null;
}

let moduleSupabaseConfiguration: SupabaseConfiguration | undefined;
function supabaseConfiguration() {
  if (moduleSupabaseConfiguration) return moduleSupabaseConfiguration;
  if (getDashboardDataProvider() !== "supabase") {
    throw new DatabaseConfigurationError("Supabase RPC is unavailable in sqlite mode");
  }
  const rawUrl = value("SUPABASE_URL");
  const apiKey = value("SUPABASE_SECRET_KEY");
  if (!rawUrl) throw new DatabaseConfigurationError("SUPABASE_URL is not configured");
  if (!apiKey) {
    throw new DatabaseConfigurationError(
      "SUPABASE_SECRET_KEY is required for the server-only dashboard RPC contract",
    );
  }
  let url: URL;
  try {
    url = new URL(rawUrl);
  } catch {
    throw new DatabaseConfigurationError("SUPABASE_URL is invalid");
  }
  if (url.protocol !== "https:" || url.username || url.password || url.search || url.hash) {
    throw new DatabaseConfigurationError("SUPABASE_URL must be a credential-free https project URL");
  }
  const urlProjectRef = projectRefFromUrl(url);
  if (!urlProjectRef) throw new DatabaseConfigurationError("SUPABASE_URL is not a project API URL");
  const configuredProjectRef = value("SUPABASE_PROJECT_REF") ?? urlProjectRef;
  if (!validProjectRef(configuredProjectRef) || configuredProjectRef !== urlProjectRef) {
    throw new DatabaseConfigurationError("SUPABASE_PROJECT_REF does not match SUPABASE_URL");
  }
  const jwtProjectRef = projectRefFromLegacyJwt(apiKey);
  if (jwtProjectRef && jwtProjectRef !== urlProjectRef) {
    throw new DatabaseConfigurationError("Supabase API key does not match SUPABASE_URL");
  }
  const rpcSchema = value("DASHBOARD_SUPABASE_RPC_SCHEMA") ?? "public";
  if (rpcSchema !== "public") {
    throw new DatabaseConfigurationError("DASHBOARD_SUPABASE_RPC_SCHEMA must be public");
  }
  moduleSupabaseConfiguration = {
    url: url.origin,
    projectRef: urlProjectRef,
    apiKey,
    // Purpose-built facades are intentionally exposed only from public. The
    // physical cre_* schemas remain inaccessible to PostgREST clients.
    schema: "public",
  };
  return moduleSupabaseConfiguration;
}

function validateLocalFileUrl(rawUrl: string | undefined, name: string): SqliteConfiguration {
  if (!rawUrl) throw new DatabaseConfigurationError(`${name} is not configured`);
  let parsed: URL;
  try {
    parsed = new URL(rawUrl);
  } catch {
    throw new DatabaseConfigurationError(`${name} must be a valid file: URL`);
  }
  if (parsed.protocol !== "file:") {
    throw new DatabaseConfigurationError(`${name} must use a local file: authority`);
  }
  return { url: rawUrl };
}

const moduleSqliteConfigurations: Partial<Record<DatabaseDomain, SqliteConfiguration>> = {};
function sqliteConfiguration(domain: DatabaseDomain) {
  const existing = moduleSqliteConfigurations[domain];
  if (existing) return existing;
  if (getDashboardDataProvider() !== "sqlite") {
    throw new DatabaseConfigurationError("Arbitrary SQL is disabled for the Supabase dashboard provider");
  }
  const name = domain === "market"
    ? "TURSO_DATABASE_URL"
    : domain === "news" ? "NEWS_DATABASE_URL" : "TIMESERIES_DATABASE_URL";
  const configured = validateLocalFileUrl(value(name), name);
  moduleSqliteConfigurations[domain] = configured;
  return configured;
}

type GlobalWithClients = typeof globalThis & {
  __creDashboardSqliteClients?: Partial<Record<DatabaseDomain, Client>>;
  __creDashboardSqliteFingerprints?: Partial<Record<DatabaseDomain, string>>;
  __creDashboardSqliteInitializations?: Partial<Record<DatabaseDomain, Promise<void>>>;
};
const globalWithClients = globalThis as GlobalWithClients;

async function sqliteClient(domain: DatabaseDomain) {
  const configured = sqliteConfiguration(domain);
  const clients = globalWithClients.__creDashboardSqliteClients ??= {};
  const fingerprints = globalWithClients.__creDashboardSqliteFingerprints ??= {};
  const initializations = globalWithClients.__creDashboardSqliteInitializations ??= {};
  const fingerprint = createHash("sha256").update(configured.url).digest("hex").slice(0, 16);
  if (clients[domain] && fingerprints[domain] !== fingerprint) {
    clients[domain]?.close();
    delete clients[domain];
    delete initializations[domain];
  }
  if (!clients[domain]) {
    const created = createClient(configured);
    clients[domain] = created;
    fingerprints[domain] = fingerprint;
    if (domain !== "market") {
      initializations[domain] = (async () => {
        await created.execute("PRAGMA query_only=ON");
        const verification = await created.execute("PRAGMA query_only");
        if (Number(verification.rows[0]?.query_only) !== 1) {
          throw new DatabaseConfigurationError(`Failed to enforce read-only ${domain} database authority`);
        }
      })().catch((error: unknown) => {
        if (clients[domain] === created) {
          created.close();
          delete clients[domain];
          delete fingerprints[domain];
          delete initializations[domain];
        }
        throw error;
      });
    }
  }
  await initializations[domain];
  return clients[domain];
}

function parsePayload(payload: unknown) {
  if (typeof payload !== "string") return payload;
  try {
    return JSON.parse(payload) as unknown;
  } catch {
    return payload;
  }
}

function normalizeRows(rows: readonly Row[]) {
  return rows.map((row) => {
    const normalized: Record<string, unknown> = {};
    for (const [name, rowValue] of Object.entries(row)) normalized[name] = rowValue;
    if (Object.hasOwn(normalized, "payload")) normalized.payload = parsePayload(normalized.payload);
    return normalized;
  });
}

async function withTimeout<T>(operation: (signal: AbortSignal) => Promise<T>) {
  const timeoutMs = queryTimeoutMs();
  const controller = new AbortController();
  let timer: ReturnType<typeof setTimeout> | undefined;
  const timedOut = new Promise<never>((_resolve, reject) => {
    timer = setTimeout(() => {
      controller.abort();
      reject(new DatabaseQueryTimeoutError(timeoutMs));
    }, timeoutMs);
  });
  try {
    return await Promise.race([operation(controller.signal), timedOut]);
  } catch (error) {
    if (controller.signal.aborted && !(error instanceof DatabaseQueryTimeoutError)) {
      throw new DatabaseQueryTimeoutError(timeoutMs);
    }
    throw error;
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function executeSqlite(domain: DatabaseDomain, sql: string, values: readonly SqlValue[]) {
  if (domain === "market") diagnostics.sqliteAuthQueries += 1;
  else diagnostics.sqliteDataQueries += 1;
  return withTimeout(async () => {
    const result = await (await sqliteClient(domain)).execute({ sql, args: [...values] });
    return { rows: normalizeRows(result.rows) };
  });
}

export const executeMarketSql: SqlExecutor = async (sql, values) => {
  const result = await executeSqlite("market", sql, values);
  return { rows: result.rows as Array<{ payload: unknown }> };
};

export const executeNewsSql: SqlExecutor = async (sql, values) => {
  const result = await executeSqlite("news", sql, values);
  return { rows: result.rows as Array<{ payload: unknown }> };
};

export const executeTimeseriesSql: SqlExecutor = async (sql, values) => {
  const result = await executeSqlite("timeseries", sql, values);
  return { rows: result.rows as Array<{ payload: unknown }> };
};

export type AuthSqlExecutor = (
  sql: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<Record<string, unknown>> }>;

export const executeAuthSql: AuthSqlExecutor = (sql, values) => executeSqlite("market", sql, values);
export const executeAuthWriteSql: AuthSqlExecutor = (sql, values) => executeSqlite("market", sql, values);

type DashboardRpcName =
  | "dashboard_serving_manifest"
  | "dashboard_daily_articles"
  | "dashboard_article_detail"
  | "dashboard_macro_timeseries"
  | "dashboard_permit_timeseries"
  | "dashboard_market_pulse"
  | "dashboard_contextual_evidence_search"
  | "dashboard_find_authorized_subject"
  | "dashboard_authorize_subject"
  | "dashboard_consume_login_attempts"
  | "dashboard_clear_login_attempts";

const AUTH_RPCS = new Set<DashboardRpcName>([
  "dashboard_find_authorized_subject",
  "dashboard_authorize_subject",
  "dashboard_consume_login_attempts",
  "dashboard_clear_login_attempts",
]);

function unwrapRpcResult(payload: unknown): unknown {
  if (Array.isArray(payload) && payload.length === 1) return unwrapRpcResult(payload[0]);
  if (payload && typeof payload === "object" && !Array.isArray(payload)) {
    const record = payload as Record<string, unknown>;
    if (Object.keys(record).length === 1 && Object.hasOwn(record, "payload")) {
      return parsePayload(record.payload);
    }
  }
  return payload;
}

async function callDashboardRpc<T>(name: DashboardRpcName, body: Record<string, unknown>): Promise<T> {
  const configured = supabaseConfiguration();
  if (AUTH_RPCS.has(name)) diagnostics.authRpcCalls += 1;
  else if (name === "dashboard_serving_manifest") diagnostics.manifestRpcCalls += 1;
  else diagnostics.dataRpcCalls += 1;

  return withTimeout(async (signal) => {
    const response = await fetch(
      `${configured.url}/rest/v1/rpc/${name}`,
      {
        method: "POST",
        headers: {
          apikey: configured.apiKey,
          "Content-Type": "application/json",
          "Content-Profile": configured.schema,
          "Accept-Profile": configured.schema,
        },
        body: JSON.stringify(body),
        cache: "no-store",
        signal,
      },
    );
    if (!response.ok) throw new DatabaseRequestError(response.status);
    return unwrapRpcResult(await response.json()) as T;
  });
}

function record(candidate: unknown): candidate is Record<string, unknown> {
  return Boolean(candidate) && typeof candidate === "object" && !Array.isArray(candidate);
}

function requiredText(candidate: unknown, field: string) {
  if (typeof candidate !== "string" || !candidate.trim() || candidate.length > 256) {
    throw new Error(`Invalid dashboard ${field}`);
  }
  return candidate;
}

function nullableText(candidate: unknown) {
  return typeof candidate === "string" && candidate ? candidate : null;
}

function numericRecord(candidate: unknown) {
  if (!record(candidate)) return {};
  return Object.fromEntries(Object.entries(candidate).flatMap(([key, item]) => (
    typeof item === "number" && Number.isFinite(item) && item >= 0 ? [[key, item]] : []
  )));
}

function stringRecord(candidate: unknown) {
  if (!record(candidate)) return {};
  return Object.fromEntries(Object.entries(candidate).flatMap(([key, item]) => (
    typeof item === "string" ? [[key, item]] : []
  )));
}

export async function getServingManifest(): Promise<ServingManifest> {
  if (getDashboardDataProvider() === "supabase") {
    const raw = await callDashboardRpc<unknown>("dashboard_serving_manifest", {});
    if (!record(raw)) throw new Error("Invalid dashboard serving manifest");
    return {
      datasetVersion: requiredText(raw.dataset_version ?? raw.datasetVersion, "dataset version"),
      sourceAsOfAt: nullableText(raw.source_as_of_at ?? raw.sourceAsOfAt),
      activatedAt: nullableText(raw.activated_at ?? raw.activatedAt),
      schemaVersion: nullableText(raw.schema_version ?? raw.schemaVersion),
      rowCounts: numericRecord(raw.row_counts ?? raw.rowCounts),
      tableHashes: stringRecord(raw.table_hashes ?? raw.tableHashes),
    };
  }

  const explicit = value("DASHBOARD_DATASET_VERSION");
  if (explicit) {
    return {
      datasetVersion: requiredText(explicit, "dataset version"), sourceAsOfAt: null,
      activatedAt: null, schemaVersion: null, rowCounts: {}, tableHashes: {},
    };
  }
  const fingerprint = createHash("sha256");
  for (const domain of ["news", "timeseries"] as const) {
    const path = fileURLToPath(sqliteConfiguration(domain).url);
    const stat = fs.statSync(/* turbopackIgnore: true */ path);
    fingerprint.update(domain).update("\0").update(String(stat.size)).update("\0")
      .update(String(stat.mtimeMs)).update("\0");
  }
  return {
    datasetVersion: `sqlite-${fingerprint.digest("hex").slice(0, 20)}`,
    sourceAsOfAt: null,
    activatedAt: null,
    schemaVersion: null,
    rowCounts: {},
    tableHashes: {},
  };
}

export function getProjectCacheNamespace() {
  if (getDashboardDataProvider() === "supabase") {
    return `supabase-${createHash("sha256")
      .update(supabaseConfiguration().projectRef)
      .digest("hex").slice(0, 16)}`;
  }
  const identity = createHash("sha256");
  for (const domain of ["market", "news", "timeseries"] as const) {
    identity.update(domain).update("\0").update(sqliteConfiguration(domain).url).update("\0");
  }
  return `sqlite-${identity.digest("hex").slice(0, 16)}`;
}

// Compatibility aliases for local-only diagnostic scripts. Shared production
// cache keys use getProjectCacheNamespace + the published dataset version.
export const getMarketCacheAuthorityNamespace = getProjectCacheNamespace;
export const getNewsCacheAuthorityNamespace = getProjectCacheNamespace;
export const getTimeseriesCacheAuthorityNamespace = getProjectCacheNamespace;

export function isLocalMarketDatabaseAuthority() {
  return getDashboardDataProvider() === "sqlite";
}

export function canUseNewsArchiveFallback() {
  // The split news database is already a complete serving projection. Production
  // never falls through to a workstation archive or prior cloud authority.
  return false;
}

export const fetchDashboardDailyArticles = (selectedDate: string, datasetVersion: string) => callDashboardRpc<unknown>(
  "dashboard_daily_articles",
  {
    p_date: selectedDate === "LATEST" ? null : selectedDate,
    p_limit: 200,
    p_dataset_version: datasetVersion,
  },
);

export const fetchDashboardArticleDetail = (documentId: string, datasetVersion: string) => callDashboardRpc<unknown>(
  "dashboard_article_detail",
  { p_document_id: documentId, p_dataset_version: datasetVersion },
);

export const fetchDashboardMacroTimeseries = (datasetVersion: string) => callDashboardRpc<unknown>(
  "dashboard_macro_timeseries",
  { p_dataset_version: datasetVersion },
);

export const fetchDashboardPermitTimeseries = (request: {
  groupBy: string;
  from: string | null;
  to: string | null;
  eventType: string | null;
  assetType: string | null;
  district: string | null;
  constructionAction: string | null;
}, datasetVersion: string) => callDashboardRpc<unknown>("dashboard_permit_timeseries", {
  p_group_by: request.groupBy,
  // The public UI contract is monthly while PostgreSQL's bounded facade uses
  // date arguments. Pin both bounds to the first day of their selected month.
  p_from: request.from ? `${request.from}-01` : null,
  p_to: request.to ? `${request.to}-01` : null,
  p_event_type: request.eventType,
  p_asset_type: request.assetType,
  p_district: request.district,
  p_construction_action: request.constructionAction,
  p_dataset_version: datasetVersion,
});

export const fetchDashboardMarketPulse = (datasetVersion: string) => callDashboardRpc<unknown>(
  "dashboard_market_pulse",
  { p_dataset_version: datasetVersion },
);

export const fetchDashboardContextualEvidence = (request: {
  q: string;
  from: string | null;
  to: string | null;
  topic: string | null;
  topK: number;
}, datasetVersion: string) => callDashboardRpc<unknown>("dashboard_contextual_evidence_search", {
  q: request.q,
  filters: { from: request.from, to: request.to, topic: request.topic },
  top_k: request.topK,
  p_dataset_version: datasetVersion,
});

type AuthorizationRecord = {
  authorized: boolean;
  subjectId: string | null;
  authzVersion: number | null;
  datasetVersion: string | null;
};

function authorizationRecord(candidate: unknown): AuthorizationRecord {
  if (!record(candidate)) throw new Error("Invalid dashboard authorization response");
  const rawAuthorized = candidate.authorized;
  if (typeof rawAuthorized !== "boolean") throw new Error("Invalid dashboard authorization response");
  const subjectId = candidate.subject_id ?? candidate.subjectId;
  const authzVersion = candidate.authz_version ?? candidate.authzVersion;
  return {
    authorized: rawAuthorized,
    subjectId: typeof subjectId === "string" ? subjectId : null,
    authzVersion: typeof authzVersion === "number" ? authzVersion : null,
    datasetVersion: nullableText(candidate.dataset_version ?? candidate.datasetVersion),
  };
}

const LOCAL_FIND_SUBJECT = `SELECT access_subject_id AS subject_id FROM dashboard_access_allowlist
WHERE email_normalized=? AND is_enabled=1 AND revoked_at IS NULL
AND (access_expires_at IS NULL OR datetime(access_expires_at)>CURRENT_TIMESTAMP) LIMIT 1`;
const LOCAL_AUTHORIZE_SUBJECT = `SELECT access_subject_id AS subject_id FROM dashboard_access_allowlist
WHERE access_subject_id=? AND is_enabled=1 AND revoked_at IS NULL
AND (access_expires_at IS NULL OR datetime(access_expires_at)>CURRENT_TIMESTAMP) LIMIT 1`;

export async function findDashboardSubjectByEmail(email: string) {
  if (getDashboardDataProvider() === "supabase") {
    const auth = authorizationRecord(await callDashboardRpc(
      "dashboard_find_authorized_subject",
      { p_email: email },
    ));
    return auth.authorized ? auth.subjectId : null;
  }
  const result = await executeAuthSql(LOCAL_FIND_SUBJECT, [email]);
  const subjectId = result.rows[0]?.subject_id;
  return typeof subjectId === "string" && subjectId ? subjectId : null;
}

export async function authorizeDashboardSubject(subjectId: string) {
  if (getDashboardDataProvider() === "supabase") {
    const auth = authorizationRecord(await callDashboardRpc(
      "dashboard_authorize_subject",
      { p_subject_id: subjectId },
    ));
    return auth.authorized && auth.subjectId === subjectId;
  }
  const result = await executeAuthSql(LOCAL_AUTHORIZE_SUBJECT, [subjectId]);
  return result.rows[0]?.subject_id === subjectId;
}

function normalizeRateLimitKeys(keys: readonly string[]) {
  if (keys.some((key) => !key)) throw new Error("Login rate-limit keys must be non-empty");
  const unique = [...new Set(keys)];
  if (unique.length === 0 || unique.length > 2) {
    throw new Error("Login rate limiting requires one or two unique keys");
  }
  return { unique, pair: [unique[0], unique[1] ?? unique[0]] as [string, string] };
}

const LOCAL_PRUNE_RATE_LIMITS = `DELETE FROM dashboard_login_rate_limits
WHERE unixepoch(updated_at)<unixepoch('now','-7 days')`;
const LOCAL_CONSUME_RATE_LIMITS = `WITH requested_keys(rate_limit_key) AS (SELECT ? UNION SELECT ?)
INSERT INTO dashboard_login_rate_limits(rate_limit_key,window_started_at,attempt_count,blocked_until,updated_at)
SELECT rate_limit_key,CURRENT_TIMESTAMP,1,NULL,CURRENT_TIMESTAMP FROM requested_keys WHERE 1
ON CONFLICT(rate_limit_key) DO UPDATE SET
window_started_at=CASE WHEN unixepoch(window_started_at)<unixepoch('now','-15 minutes') THEN CURRENT_TIMESTAMP ELSE window_started_at END,
attempt_count=CASE WHEN unixepoch(window_started_at)<unixepoch('now','-15 minutes') THEN 1 ELSE attempt_count+1 END,
blocked_until=CASE WHEN unixepoch(blocked_until)>unixepoch('now') THEN blocked_until WHEN unixepoch(window_started_at)<unixepoch('now','-15 minutes') THEN NULL WHEN attempt_count+1>=10 THEN datetime('now','+15 minutes') ELSE NULL END,
updated_at=CURRENT_TIMESTAMP RETURNING rate_limit_key,CASE WHEN unixepoch(blocked_until)>unixepoch('now') THEN 1 ELSE 0 END AS blocked`;
const LOCAL_CLEAR_RATE_LIMITS = `DELETE FROM dashboard_login_rate_limits WHERE rate_limit_key IN (?,?)`;

export async function consumeDashboardLoginAttempts(keys: readonly string[]) {
  const { unique, pair } = normalizeRateLimitKeys(keys);
  if (getDashboardDataProvider() === "supabase") {
    const raw = await callDashboardRpc<unknown>("dashboard_consume_login_attempts", { p_keys: unique });
    if (typeof raw === "boolean") return raw;
    if (record(raw) && typeof raw.blocked === "boolean") return raw.blocked;
    throw new Error("Invalid dashboard rate-limit response");
  }
  await executeAuthWriteSql(LOCAL_PRUNE_RATE_LIMITS, []);
  const result = await executeAuthWriteSql(LOCAL_CONSUME_RATE_LIMITS, pair);
  if (result.rows.length !== unique.length) throw new Error("Login rate-limit update was incomplete");
  const returnedKeys = new Set<string>();
  let blocked = false;
  for (const row of result.rows) {
    if (typeof row.rate_limit_key !== "string" || !unique.includes(row.rate_limit_key)) {
      throw new Error("Login rate-limit result has an unexpected key");
    }
    if (returnedKeys.has(row.rate_limit_key)) {
      throw new Error("Login rate-limit update returned a duplicate key");
    }
    returnedKeys.add(row.rate_limit_key);
    if (row.blocked === true || row.blocked === 1 || row.blocked === BigInt(1)) blocked = true;
    else if (!(row.blocked === false || row.blocked === 0 || row.blocked === BigInt(0))) {
      throw new Error("Login rate-limit result is invalid");
    }
  }
  if (returnedKeys.size !== unique.length) throw new Error("Login rate-limit update was incomplete");
  return blocked;
}

export async function clearDashboardLoginAttempts(keys: readonly string[]) {
  const { unique, pair } = normalizeRateLimitKeys(keys);
  if (getDashboardDataProvider() === "supabase") {
    await callDashboardRpc("dashboard_clear_login_attempts", { p_keys: unique });
    return;
  }
  await executeAuthWriteSql(LOCAL_CLEAR_RATE_LIMITS, pair);
}
