import { createTursoClient, normalizeRows } from "./libsql-client.mjs";

const emailPattern = /^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$/u;

const createAllowlist = `
CREATE TABLE IF NOT EXISTS dashboard_access_allowlist (
  access_subject_id TEXT PRIMARY KEY DEFAULT (
    lower(hex(randomblob(4))) || '-' ||
    lower(hex(randomblob(2))) || '-4' ||
    substr(lower(hex(randomblob(2))), 2) || '-' ||
    substr('89ab', (random() & 3) + 1, 1) ||
    substr(lower(hex(randomblob(2))), 2) || '-' ||
    lower(hex(randomblob(6)))
  ),
  email_normalized TEXT NOT NULL UNIQUE,
  is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
  approved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  approved_by TEXT NOT NULL,
  revoked_at TEXT,
  revoked_by TEXT,
  access_expires_at TEXT
)`;

const createRateLimits = `
CREATE TABLE IF NOT EXISTS dashboard_login_rate_limits (
  rate_limit_key TEXT PRIMARY KEY,
  window_started_at TEXT NOT NULL,
  attempt_count INTEGER NOT NULL CHECK (attempt_count >= 0),
  blocked_until TEXT,
  updated_at TEXT NOT NULL
)`;

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

async function tableExists(client, tableName) {
  const result = await client.execute({
    sql: `
      SELECT name AS table_name
      FROM sqlite_schema
      WHERE type = 'table' AND name = ?
      LIMIT 1
    `,
    args: [tableName],
  });
  return result.rows[0]?.table_name === tableName;
}

async function accessCounts(client, emails) {
  const placeholders = emails.map(() => "(?)").join(", ");
  const result = await client.execute({
    sql: `
      WITH requested(email_normalized) AS (VALUES ${placeholders})
      SELECT
        count(*) AS total_count,
        count(CASE WHEN a.is_enabled = 1 AND a.revoked_at IS NULL THEN 1 END) AS enabled_count,
        count(CASE WHEN EXISTS (
          SELECT 1 FROM requested AS r WHERE r.email_normalized = a.email_normalized
        ) THEN 1 END) AS requested_count,
        count(CASE
          WHEN EXISTS (
            SELECT 1 FROM requested AS r WHERE r.email_normalized = a.email_normalized
          )
            AND a.is_enabled = 1
            AND a.revoked_at IS NULL
            AND (a.access_expires_at IS NULL OR datetime(a.access_expires_at) > CURRENT_TIMESTAMP)
          THEN 1
        END) AS active_requested_count,
        count(CASE
          WHEN NOT EXISTS (
            SELECT 1 FROM requested AS r WHERE r.email_normalized = a.email_normalized
          )
            AND a.is_enabled = 1
            AND a.revoked_at IS NULL
            AND (a.access_expires_at IS NULL OR datetime(a.access_expires_at) > CURRENT_TIMESTAMP)
          THEN 1
        END) AS active_other_count
      FROM dashboard_access_allowlist AS a
    `,
    args: emails,
  });
  return normalizeRows(result.rows)[0];
}

const command = process.argv[2] ?? "audit";
if (!new Set(["audit", "apply"]).has(command)) throw new Error("Use audit or apply");

const emails = approvedEmails();
const client = createTursoClient();

try {
  let allowlistExists = await tableExists(client, "dashboard_access_allowlist");
  let rateLimitsExist = await tableExists(client, "dashboard_login_rate_limits");

  if (command === "audit") {
    console.log(JSON.stringify({
      tableExists: allowlistExists,
      rateLimitTableExists: rateLimitsExist,
      ...(allowlistExists ? await accessCounts(client, emails) : {}),
    }));
  } else {
    const approvedBy = process.env.DASHBOARD_APPROVED_BY?.trim();
    if (!approvedBy) throw new Error("DASHBOARD_APPROVED_BY is required for apply");

    const tableCreated = !allowlistExists;
    const rateLimitTableCreated = !rateLimitsExist;
    await client.batch([createAllowlist, createRateLimits], "write");
    allowlistExists = await tableExists(client, "dashboard_access_allowlist");
    rateLimitsExist = await tableExists(client, "dashboard_login_rate_limits");
    if (!allowlistExists || !rateLimitsExist) {
      throw new Error("Turso auth table creation did not complete");
    }

    const before = await accessCounts(client, emails);
    if (before.active_other_count > 0) {
      throw new Error("Other active approvals already exist; refusing to change the allowlist implicitly");
    }

    await client.batch(emails.map((email) => ({
      sql: `
        INSERT INTO dashboard_access_allowlist (
          email_normalized, approved_by, access_expires_at
        ) VALUES (?, ?, NULL)
        ON CONFLICT(email_normalized) DO UPDATE SET
          is_enabled = 1,
          approved_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
          approved_by = excluded.approved_by,
          revoked_at = NULL,
          revoked_by = NULL,
          access_expires_at = NULL
      `,
      args: [email, approvedBy],
    })), "write");

    const after = await accessCounts(client, emails);
    if (after.active_requested_count !== emails.length || after.active_other_count !== 0) {
      throw new Error("Allowlist verification failed after apply");
    }
    console.log(JSON.stringify({
      tableCreated,
      rateLimitTableCreated,
      requested: emails.length,
      ...after,
    }));
  }
} finally {
  client.close();
}
