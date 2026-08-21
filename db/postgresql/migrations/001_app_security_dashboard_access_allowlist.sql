-- PostgreSQL-only operational migration.
-- This schema contains access-control PII and is intentionally outside
-- market_intelligence schema_version, SQLite replicas, archives, and snapshots.
BEGIN;

SET LOCAL lock_timeout = '5s';
SET LOCAL statement_timeout = '30s';

CREATE SCHEMA IF NOT EXISTS app_security;
REVOKE ALL ON SCHEMA app_security FROM PUBLIC;

CREATE TABLE app_security.dashboard_access_allowlist (
    access_subject_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email_normalized TEXT NOT NULL UNIQUE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    approved_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    approved_by TEXT NOT NULL,
    revoked_at TIMESTAMPTZ,
    revoked_by TEXT,
    access_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT dashboard_access_email_length CHECK (length(email_normalized) BETWEEN 3 AND 254),
    CONSTRAINT dashboard_access_email_normalized CHECK (email_normalized = lower(btrim(email_normalized))),
    CONSTRAINT dashboard_access_email_no_control CHECK (email_normalized !~ '[[:cntrl:]]'),
    CONSTRAINT dashboard_access_email_shape CHECK (
        email_normalized ~ '^[A-Za-z0-9.!#$%&''*+/=?^_`{|}~-]+@[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?([.][A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'
        AND length(split_part(email_normalized, '@', 1)) <= 64
        AND left(split_part(email_normalized, '@', 1), 1) <> '.'
        AND right(split_part(email_normalized, '@', 1), 1) <> '.'
        AND position('..' IN split_part(email_normalized, '@', 1)) = 0
    ),
    CONSTRAINT dashboard_access_approved_by_present CHECK (btrim(approved_by) <> ''),
    CONSTRAINT dashboard_access_revocation_state CHECK (
        (is_enabled AND revoked_at IS NULL AND revoked_by IS NULL)
        OR
        (NOT is_enabled AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND btrim(revoked_by) <> '')
    ),
    CONSTRAINT dashboard_access_timestamp_order CHECK (
        updated_at >= created_at AND (revoked_at IS NULL OR revoked_at >= approved_at)
    )
);

CREATE FUNCTION app_security.touch_dashboard_access_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = pg_catalog
AS $$
BEGIN
    NEW.updated_at := clock_timestamp();
    RETURN NEW;
END;
$$;

CREATE TRIGGER dashboard_access_allowlist_touch_updated_at
BEFORE UPDATE ON app_security.dashboard_access_allowlist
FOR EACH ROW
EXECUTE FUNCTION app_security.touch_dashboard_access_updated_at();

REVOKE ALL ON TABLE app_security.dashboard_access_allowlist FROM PUBLIC;
REVOKE ALL ON FUNCTION app_security.touch_dashboard_access_updated_at() FROM PUBLIC;

COMMENT ON SCHEMA app_security IS 'Operational access-control data; excluded from market data replicas and snapshots.';
COMMENT ON TABLE app_security.dashboard_access_allowlist IS 'Server-only approved email allowlist for CRE dashboard access.';
COMMENT ON COLUMN app_security.dashboard_access_allowlist.access_subject_id IS 'Opaque session subject; emails are never embedded in session cookies.';

COMMIT;
