from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "turso" / "migrations" / "001_dashboard_security.sql"


def test_turso_security_migration_is_idempotent_and_constrained() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(sql)
        connection.executescript(sql)
        connection.execute(
            "INSERT INTO dashboard_access_allowlist(email_normalized, approved_by) VALUES (?, ?)",
            ("qa@example.com", "migration-test"),
        )
        subject_id, enabled = connection.execute(
            "SELECT access_subject_id, is_enabled FROM dashboard_access_allowlist"
        ).fetchone()
        assert len(subject_id) == 36
        assert enabled == 1

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO dashboard_access_allowlist(email_normalized, approved_by) VALUES (?, ?)",
                ("NOT-NORMALIZED@example.com", "migration-test"),
            )
    finally:
        connection.close()