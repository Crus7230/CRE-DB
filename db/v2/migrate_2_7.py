"""Apply V2.7 post-collection relationship migration after a consistent SQLite backup."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path

from migrate_2_6 import backup, connect, version

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "migrations" / "2.7.0_post_collection_relationships.sql"
EXPECTED_FROM = "2.6.0"
EXPECTED_TO = "2.7.0"
REQUIRED_TABLES = {"relationship_resolution_runs", "predicate_relationship_rules"}
REQUIRED_VIEWS = {"v_relationship_gaps"}
REQUIRED_RULES = {
    ("PARTICIPANT_ROLE", role, "EVENT_PARTICIPANT", role, "VERIFIED")
    for role in ("TENANT", "LANDLORD", "OWNER", "OPERATOR", "INVESTOR", "BUYER", "SELLER")
} | {("BUSINESS_DOMAIN", "SUBJECT_ORGANIZATION", "BUSINESS_ACTIVITY", None, "VERIFIED")}


def validate_migration(con) -> dict:
    actual = version(con)
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    views = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    missing = sorted((REQUIRED_TABLES - tables) | (REQUIRED_VIEWS - views))
    actual_rules = set()
    if not missing:
        actual_rules = set(con.execute(
            """SELECT predicate_code,claim_role_code,target_relation,
                      participant_role_code,minimum_verification_status
                 FROM predicate_relationship_rules WHERE auto_apply=1"""
        ))
    missing_rules = sorted(REQUIRED_RULES - actual_rules, key=str)
    role = con.execute("SELECT COUNT(*) FROM claim_role_definitions WHERE role_code='SUBJECT_ORGANIZATION'").fetchone()[0]
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = con.execute("PRAGMA foreign_key_check").fetchall()
    if actual != EXPECTED_TO or missing or missing_rules or role != 1 or integrity != "ok" or fk:
        raise RuntimeError(
            f"migration validation failed: version={actual}, missing={missing}, "
            f"missing_rules={missing_rules}, role={role}, integrity={integrity}, fk={len(fk)}"
        )
    return {"actual": actual, "rules": len(actual_rules), "integrity": integrity, "fk": fk}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    db_path = args.db.resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    con = connect(db_path)
    try:
        current = version(con)
    finally:
        con.close()
    if current == EXPECTED_TO:
        con = connect(db_path)
        try:
            validate_migration(con)
        finally:
            con.close()
        print(json.dumps({"status": "already_applied", "schemaVersion": current, "validated": True}, ensure_ascii=False))
        return
    if current != EXPECTED_FROM:
        raise SystemExit(f"Expected schema {EXPECTED_FROM}, found {current}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = (args.backup or db_path.parent.parent / "backups" / f"market-pre-v2.7.0-{stamp}.db").resolve()
    manifest = backup(db_path, backup_path)
    con = connect(db_path)
    try:
        con.executescript(MIGRATION.read_text(encoding="utf-8"))
        validation = validate_migration(con)
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
    print(json.dumps({
        "status": "applied", "from": current, "to": validation["actual"], "backup": manifest,
        "relationshipRules": validation["rules"], "integrityCheck": validation["integrity"],
        "foreignKeyViolations": len(validation["fk"]),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
