# Dashboard approved-email access

## Security boundary

Dashboard access-control data lives only in PostgreSQL schema `app_security`. It is outside the `market_intelligence` schema version and must never enter SQLite replicas, market snapshots, archives, fixtures, browser bundles, or Android resources.

The client sends only `{ "email": "person@example.com" }` to `POST /api/auth/login`. The endpoint rejects request bodies over 4 KiB, then the server trims and lowercases the address, validates it, and uses it as one PostgreSQL bind parameter. Missing, disabled, revoked, expired, and malformed addresses all receive the same `401` message, so failure states are not distinguished. A successful `200` still confirms that an address is currently approved; this endpoint is not resistant to address enumeration by itself.

On success, the server places only the row's opaque `access_subject_id` plus issued/expiry times in the signed `cre_db_session` cookie. The email is not embedded in the cookie. The HttpOnly, SameSite=Lax session expires after 12 hours and is verified with Web Crypto in the proxy.

> This email-only MVP checks an approved identifier, not ownership of the mailbox. Anyone who knows an approved address can enter it. Email OTP, magic link, company SSO, or a private network is required before exposing sensitive data on the public internet. A shared-store/platform rate limit is also required for public deployment; an in-process limiter is insufficient on multi-instance hosting.

## Migration-first deployment

Do not deploy the new web or Android login contract before the table and at least one administrator-approved address exist.

1. Review and apply `db/postgresql/migrations/001_app_security_dashboard_access_allowlist.sql` with a PostgreSQL migration/admin role. The application never applies it automatically.
2. Grant the dashboard runtime only the columns required by the lookup. Replace `<runtime-role>` with the actual login/reader role.

```sql
GRANT USAGE ON SCHEMA app_security TO <runtime-role>;
GRANT SELECT (access_subject_id, email_normalized, is_enabled, revoked_at, access_expires_at)
ON app_security.dashboard_access_allowlist TO <runtime-role>;
```

3. Add the initial approved address with an accountable operator value.

```sql
INSERT INTO app_security.dashboard_access_allowlist (
  email_normalized, approved_by, access_expires_at
) VALUES (
  lower(btrim('<approved-email>')), '<operator>', NULL
);
```

4. Create a dedicated runtime LOGIN/reader role, verify its grants by readback, and use its DSN instead of an owner or administrator connection. Set a server-only `DASHBOARD_SESSION_SECRET` of at least 32 bytes. Do not use a `NEXT_PUBLIC_` variable.
5. Deploy the web/API contract, then the Android client using `{email}` while preserving the `cre_db_session` cookie.
6. Run the live smoke test with an approved test address:

```powershell
$env:DASHBOARD_SMOKE_EMAIL = '<approved-test-email>'
node web/scripts/smoke-live.mjs
```

7. Remove the retired `DASHBOARD_ACCESS_CODE` secret after all deployed clients use the email contract.

Do not put either secret in a build command. Inject secrets only at runtime, exclude `.next/cache` and `.next/dev` from deployment artifacts, and delete old local `.next` caches before sharing the workspace.

## Approve, temporarily approve, revoke, and restore

New permanent approval:

```sql
INSERT INTO app_security.dashboard_access_allowlist (
  email_normalized, approved_by
) VALUES (
  lower(btrim('<approved-email>')), '<operator>'
);
```

Temporary approval uses a database timestamp. It automatically stops new logins after the timestamp:

```sql
INSERT INTO app_security.dashboard_access_allowlist (
  email_normalized, approved_by, access_expires_at
) VALUES (
  lower(btrim('<approved-email>')), '<operator>', clock_timestamp() + interval '7 days'
);
```

Revoke by state change; do not delete the row:

```sql
UPDATE app_security.dashboard_access_allowlist
SET is_enabled = FALSE,
    revoked_at = clock_timestamp(),
    revoked_by = '<operator>'
WHERE email_normalized = lower(btrim('<approved-email>'));
```

Restore an existing row:

```sql
UPDATE app_security.dashboard_access_allowlist
SET is_enabled = TRUE,
    approved_at = clock_timestamp(),
    approved_by = '<operator>',
    revoked_at = NULL,
    revoked_by = NULL,
    access_expires_at = NULL
WHERE email_normalized = lower(btrim('<approved-email>'));
```

## Revocation timing

Disabling, revoking, or expiring an address blocks the next login immediately. An already issued stateless cookie remains valid until logout or its signed expiry, for at most 12 hours. Immediate global revocation requires a server-side session/revocation store checked on every request (or a shorter session lifetime); the Edge-compatible stateless MVP does not claim immediate invalidation.

Rotating `DASHBOARD_SESSION_SECRET` invalidates every current session and should be reserved for incident response because it signs all users' cookies.

## Replica exclusion

The Supabase-to-SQLite refresh is scoped to `market_intelligence` and explicitly refuses `SUPABASE_DB_SCHEMA=app_security`. Backup or export jobs must keep the same schema boundary. Never add `app_security` to market-data coverage checks or SQLite templates.
