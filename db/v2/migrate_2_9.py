#!/usr/bin/env python
from __future__ import annotations

import argparse
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "migrations" / "2.9.0_document_cre_scope.sqlite.sql"
EXPECTED_FROM = "2.8.0"
EXPECTED_TO = "2.9.0"
EXPECTED_COLUMNS = (
    "document_scope_assessment_id", "document_version_id", "scope_code",
    "classifier_version", "status_code", "reason_codes_json", "evidence_json", "assessed_at",
)


def migrate(db_path: Path, backup_path: Path | None = None) -> dict[str, str | int]:
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"database not found: {db_path}")
    if backup_path:
        backup_path = backup_path.resolve()
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        source = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
        target = sqlite3.connect(backup_path)
        try:
            source.backup(target)
            target.commit()
        finally:
            target.close()
            source.close()
    connection = sqlite3.connect(db_path)
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        current = connection.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()
        if current is None or current[0] != EXPECTED_FROM:
            raise SystemExit(f"Expected schema {EXPECTED_FROM}, found {current[0] if current else 'missing'}")
        existing = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='document_scope_assessments'"
        ).fetchone()
        if existing:
            raise RuntimeError("PREEXISTING_DOCUMENT_SCOPE_ASSESSMENTS_TABLE")
        connection.executescript("BEGIN IMMEDIATE;\n" + MIGRATION.read_text(encoding="utf-8"))
        actual_columns = tuple(
            row[1] for row in connection.execute("PRAGMA table_info(document_scope_assessments)")
        )
        if actual_columns != EXPECTED_COLUMNS:
            raise RuntimeError("DOCUMENT_SCOPE_ASSESSMENTS_COLUMN_MISMATCH")
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        version = connection.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        if integrity != "ok" or foreign_keys or version != EXPECTED_TO:
            raise RuntimeError(
                f"migration validation failed: integrity={integrity}, fk={len(foreign_keys)}, version={version}"
            )
        connection.commit()
        return {
            "schema_version": version,
            "integrity": integrity,
            "foreign_key_violations": len(foreign_keys),
            "database": str(db_path),
        }
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    print(migrate(args.database, args.backup))


if __name__ == "__main__":
    main()
