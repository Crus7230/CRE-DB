import { isValidEmail, normalizeEmail } from "@/lib/server/auth-session";
import type { SqlValue } from "@/lib/server/market-search";

export type AuthSqlExecutor = (
  text: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<Record<string, unknown>> }>;

const APPROVED_EMAIL_QUERY = `
SELECT access_subject_id AS subject_id
FROM dashboard_access_allowlist
WHERE email_normalized = ?
  AND is_enabled = 1
  AND revoked_at IS NULL
  AND (access_expires_at IS NULL OR datetime(access_expires_at) > CURRENT_TIMESTAMP)
LIMIT 1
`;

export async function findAllowedSubjectId(execute: AuthSqlExecutor, candidate: string) {
  const email = normalizeEmail(candidate);
  if (!isValidEmail(email)) return null;
  const result = await execute(APPROVED_EMAIL_QUERY, [email]);
  const subjectId = result.rows[0]?.subject_id;
  return typeof subjectId === "string" && subjectId ? subjectId : null;
}

const APPROVED_SUBJECT_QUERY = `
SELECT access_subject_id AS subject_id
FROM dashboard_access_allowlist
WHERE access_subject_id = ?
  AND is_enabled = 1
  AND revoked_at IS NULL
  AND (access_expires_at IS NULL OR datetime(access_expires_at) > CURRENT_TIMESTAMP)
LIMIT 1
`;

export async function isAllowedSubjectId(execute: AuthSqlExecutor, subjectId: string) {
  const result = await execute(APPROVED_SUBJECT_QUERY, [subjectId]);
  return result.rows[0]?.subject_id === subjectId;
}
