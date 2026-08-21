import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import postgres from "postgres";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(scriptDir, "..", "..");
const defaultAuthority = String.raw`C:\10137_WorkSpace\env\.env.supabase.local`;
const emailPattern = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/u;

function parseEnv(text) {
  const values = {};
  for (const rawLine of text.replace(/^\uFEFF/u, "").split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/u);
    if (!match) continue;
    values[match[1]] = match[2].trim().replace(/^(['"])(.*)\1$/u, "$2");
  }
  return values;
}

async function connectionUrl() {
  if (process.env.SUPABASE_DB_URL) return process.env.SUPABASE_DB_URL;
  const authority = process.env.SUPABASE_ENV_FILE ?? defaultAuthority;
  const values = parseEnv(await fs.readFile(authority, "utf8"));
  if (!values.SUPABASE_DB_URL) throw new Error("SUPABASE_DB_URL is not configured");
  return values.SUPABASE_DB_URL;
}

function normalizeEmail(value) {
  return value.trim().toLowerCase();
}

function validEmail(value) {
  const localPart = value.split("@", 1)[0] ?? "";
  return value.length >= 3
    && value.length <= 254
    && localPart.length <= 64
    && !localPart.startsWith(".")
    && !localPart.endsWith(".")
    && !localPart.includes("..")
    && emailPattern.test(value);
}

function approvedEmails() {
  const parsed = JSON.parse(process.env.DASHBOARD_APPROVED_EMAILS_JSON ?? "[]");
  if (!Array.isArray(parsed)) throw new Error("DASHBOARD_APPROVED_EMAILS_JSON must be an array");
  const emails = [...new Set(parsed.map((value) => normalizeEmail(String(value))))];
  if (!emails.length || emails.some((email) => !validEmail(email))) {
    throw new Error("Every approved email must match the dashboard email contract");
  }
  return emails;
}

async function tableExists(sql) {
  const [row] = await sql`SELECT to_regclass('app_security.dashboard_access_allowlist')::text AS table_name`;
  return Boolean(row?.table_name);
}

async function accessCounts(sql, emails) {
  const [row] = await sql.unsafe(`
    SELECT
      count(*)::int AS total_count,
      count(*) FILTER (WHERE is_enabled AND revoked_at IS NULL)::int AS enabled_count,
      count(*) FILTER (WHERE email_normalized = ANY($1::text[]))::int AS requested_count,
      count(*) FILTER (
        WHERE email_normalized = ANY($1::text[])
          AND is_enabled
          AND revoked_at IS NULL
          AND (access_expires_at IS NULL OR access_expires_at > clock_timestamp())
      )::int AS active_requested_count,
      count(*) FILTER (
        WHERE NOT (email_normalized = ANY($1::text[]))
          AND is_enabled
          AND revoked_at IS NULL
          AND (access_expires_at IS NULL OR access_expires_at > clock_timestamp())
      )::int AS active_other_count
    FROM app_security.dashboard_access_allowlist
  `, [emails]);
  return row;
}

const command = process.argv[2] ?? "audit";
if (!new Set(["audit", "apply"]).has(command)) throw new Error("Use audit or apply");

const emails = approvedEmails();
const sql = postgres(await connectionUrl(), {
  max: 1,
  connect_timeout: 15,
  idle_timeout: 10,
  ssl: "require",
  prepare: false,
});

try {
  let exists = await tableExists(sql);
  let tableCreated = false;
  if (command === "audit") {
    console.log(JSON.stringify({ tableExists: exists, ...(exists ? await accessCounts(sql, emails) : {}) }));
    process.exitCode = 0;
  } else {
    const approvedBy = process.env.DASHBOARD_APPROVED_BY?.trim();
    if (!approvedBy) throw new Error("DASHBOARD_APPROVED_BY is required for apply");

    if (!exists) {
      const migration = await fs.readFile(
        path.join(projectRoot, "db", "postgresql", "migrations", "001_app_security_dashboard_access_allowlist.sql"),
        "utf8",
      );
      await sql.unsafe(migration);
      exists = await tableExists(sql);
      if (!exists) throw new Error("app_security migration did not create the allowlist table");
      tableCreated = true;
    }

    const before = await accessCounts(sql, emails);
    if (before.active_other_count > 0) {
      throw new Error("Other active approvals already exist; refusing to change the allowlist implicitly");
    }

    await sql.begin(async (transaction) => {
      for (const email of emails) {
        await transaction.unsafe(`
          INSERT INTO app_security.dashboard_access_allowlist (
            email_normalized, approved_by, access_expires_at
          ) VALUES ($1, $2, NULL)
          ON CONFLICT (email_normalized) DO UPDATE SET
            is_enabled = TRUE,
            approved_at = clock_timestamp(),
            approved_by = EXCLUDED.approved_by,
            revoked_at = NULL,
            revoked_by = NULL,
            access_expires_at = NULL
        `, [email, approvedBy]);
      }
    });

    const after = await accessCounts(sql, emails);
    if (after.active_requested_count !== emails.length || after.active_other_count !== 0) {
      throw new Error("Allowlist verification failed after apply");
    }
    console.log(JSON.stringify({ tableCreated, requested: emails.length, ...after }));
  }
} finally {
  await sql.end({ timeout: 5 });
}
