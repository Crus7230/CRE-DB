PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS dashboard_access_allowlist (
    access_subject_id TEXT PRIMARY KEY
        DEFAULT (
            lower(hex(randomblob(4))) || '-' ||
            lower(hex(randomblob(2))) || '-4' ||
            substr(lower(hex(randomblob(2))), 2) || '-' ||
            substr('89ab', abs(random()) % 4 + 1, 1) ||
            substr(lower(hex(randomblob(2))), 2) || '-' ||
            lower(hex(randomblob(6)))
        ),
    email_normalized TEXT NOT NULL UNIQUE,
    is_enabled INTEGER NOT NULL DEFAULT 1 CHECK (is_enabled IN (0, 1)),
    approved_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    approved_by TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT,
    access_expires_at TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    CHECK (length(email_normalized) BETWEEN 3 AND 254),
    CHECK (email_normalized = lower(trim(email_normalized))),
    CHECK (instr(email_normalized, '@') > 1),
    CHECK (trim(approved_by) <> ''),
    CHECK (
        (is_enabled = 1 AND revoked_at IS NULL AND revoked_by IS NULL)
        OR
        (is_enabled = 0 AND revoked_at IS NOT NULL AND revoked_by IS NOT NULL AND trim(revoked_by) <> '')
    ),
    CHECK (updated_at >= created_at AND (revoked_at IS NULL OR revoked_at >= approved_at))
);

CREATE TRIGGER IF NOT EXISTS dashboard_access_allowlist_touch_updated_at
AFTER UPDATE ON dashboard_access_allowlist
FOR EACH ROW
WHEN NEW.updated_at = OLD.updated_at
BEGIN
    UPDATE dashboard_access_allowlist
    SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
    WHERE access_subject_id = NEW.access_subject_id;
END;

CREATE TABLE IF NOT EXISTS dashboard_login_rate_limits (
    rate_limit_key TEXT PRIMARY KEY,
    window_started_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    blocked_until TEXT,
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS ix_dashboard_login_rate_limits_cleanup
ON dashboard_login_rate_limits(updated_at);