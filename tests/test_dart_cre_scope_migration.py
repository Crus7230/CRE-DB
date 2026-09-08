from __future__ import annotations

from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.9.0_document_cre_scope.sqlite.sql"
POSTGRES_MIGRATION = ROOT / "db" / "v2" / "migrations" / "2.9.0_document_cre_scope.sql"


def database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES ('schema_version','2.8.0');
        CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY);
        INSERT INTO document_versions VALUES ('v1');
        """
    )
    conn.executescript(MIGRATION.read_text(encoding="utf-8"))
    return conn


def test_scope_assessment_is_versioned_and_schema_advances() -> None:
    conn = database()
    conn.execute(
        """INSERT INTO document_scope_assessments(
               document_scope_assessment_id,document_version_id,scope_code,
               classifier_version,status_code,reason_codes_json,evidence_json,assessed_at
           ) VALUES (?,?,?,?,?,?,?,?)""",
        ("a1", "v1", "CRE", "RULE_V1", "CRE_CONFIRMED", '["PROPERTY"]', "{}", "2026-08-20T00:00:00Z"),
    )
    assert conn.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
    ).fetchone()[0] == "2.9.0"
    assert conn.execute("SELECT status_code FROM document_scope_assessments").fetchone()[0] == "CRE_CONFIRMED"


def test_scope_assessment_rejects_unknown_status() -> None:
    conn = database()
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO document_scope_assessments(
                   document_scope_assessment_id,document_version_id,scope_code,
                   classifier_version,status_code,reason_codes_json,evidence_json,assessed_at
               ) VALUES ('a1','v1','CRE','RULE_V1','MAYBE','[]','{}','2026-08-20T00:00:00Z')"""
        )


def test_scope_assessment_cascades_with_document_version() -> None:
    conn = database()
    conn.execute(
        """INSERT INTO document_scope_assessments(
               document_scope_assessment_id,document_version_id,scope_code,
               classifier_version,status_code,reason_codes_json,evidence_json,assessed_at
           ) VALUES ('a1','v1','CRE','RULE_V1','CRE_REVIEW','[]','{}','2026-08-20T00:00:00Z')"""
    )
    conn.execute("DELETE FROM document_versions WHERE document_version_id='v1'")
    assert conn.execute("SELECT count(*) FROM document_scope_assessments").fetchone()[0] == 0


def test_postgres_migration_requires_v28_source_schema() -> None:
    sql = POSTGRES_MIGRATION.read_text(encoding="utf-8")
    assert "current_version IS DISTINCT FROM '2.8.0'" in sql
    assert "Expected schema 2.8.0" in sql
