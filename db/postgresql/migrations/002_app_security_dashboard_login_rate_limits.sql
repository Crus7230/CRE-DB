BEGIN;
CREATE SCHEMA IF NOT EXISTS app_security;
REVOKE ALL ON SCHEMA app_security FROM PUBLIC;

CREATE TABLE IF NOT EXISTS app_security.dashboard_login_rate_limits (
    rate_limit_key TEXT PRIMARY KEY,
    window_started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    blocked_until TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
CREATE INDEX IF NOT EXISTS ix_dashboard_login_rate_limits_cleanup
ON app_security.dashboard_login_rate_limits(updated_at);
REVOKE ALL ON TABLE app_security.dashboard_login_rate_limits FROM PUBLIC;
COMMENT ON TABLE app_security.dashboard_login_rate_limits IS 'Server-only shared login throttling state; keys are HMAC pseudonyms, never raw IPs.';
COMMIT;
