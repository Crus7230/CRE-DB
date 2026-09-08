from __future__ import annotations

from pathlib import Path
import re
import sqlite3

import pytest

from db.v2.migrate_2_9 import migrate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def create_v28(path: Path) -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    sql = re.sub(
        r"\nCREATE TABLE document_scope_assessments \(.*?\nCREATE INDEX ix_document_scope_assessments_scope_status\n    ON document_scope_assessments\(scope_code,status_code,classifier_version,document_version_id\);\n",
        "\n",
        sql,
        flags=re.S,
    )
    sql = sql.replace("'schema_version', '3.5.0'", "'schema_version', '2.8.0'")
    conn = sqlite3.connect(path)
    try:
        conn.executescript(sql)
        conn.commit()
    finally:
        conn.close()


def test_migrates_v28_to_v29(tmp_path: Path) -> None:
    db = tmp_path / "market.db"
    create_v28(db)
    result = migrate(db)
    assert result["schema_version"] == "2.9.0"
    assert result["integrity"] == "ok"
    conn = sqlite3.connect(db)
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(document_scope_assessments)")]
        assert columns == [
            "document_scope_assessment_id", "document_version_id", "scope_code",
            "classifier_version", "status_code", "reason_codes_json", "evidence_json", "assessed_at",
        ]
    finally:
        conn.close()


def test_rejects_wrong_source_version(tmp_path: Path) -> None:
    db = tmp_path / "market.db"
    create_v28(db)
    conn = sqlite3.connect(db)
    conn.execute("UPDATE schema_meta SET schema_value='2.7.0' WHERE schema_key='schema_version'")
    conn.commit()
    conn.close()
    with pytest.raises(SystemExit, match="Expected schema 2.8.0"):
        migrate(db)


def test_rejects_preexisting_scope_table(tmp_path: Path) -> None:
    db = tmp_path / "market.db"
    create_v28(db)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE document_scope_assessments(dummy TEXT)")
    conn.commit()
    conn.close()
    with pytest.raises(RuntimeError, match="PREEXISTING_DOCUMENT_SCOPE_ASSESSMENTS_TABLE"):
        migrate(db)
