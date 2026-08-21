import { isValidEmail, normalizeEmail } from "@/lib/server/auth-session";
import type { SqlValue } from "@/lib/server/market-search";

export type AuthSqlExecutor = (
  text: string,
  values: readonly SqlValue[],
) => Promise<{ rows: Array<Record<string, unknown>> }>;

const APPROVED_EMAIL_QUERY = `
SELECT access_subject_id::text AS subject_id
FROM app_security.dashboard_access_allowlist
WHERE email_normalized = $1
  AND is_enabled = TRUE
  AND revoked_at IS NULL
  AND (access_expires_at IS NULL OR access_expires_at > clock_timestamp())
LIMIT 1
`;

export async function findAllowedSubjectId(execute: AuthSqlExecutor, candidate: string) {
  const email = normalizeEmail(candidate);
  if (!isValidEmail(email)) return null;
  const result = await execute(APPROVED_EMAIL_QUERY, [email]);
  const subjectId = result.rows[0]?.subject_id;
  return typeof subjectId === "string" && subjectId ? subjectId : null;
}
