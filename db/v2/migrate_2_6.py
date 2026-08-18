"""Apply V2.6 company/tenant intelligence migration after a consistent SQLite backup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "migrations" / "2.6.0_company_tenant_intelligence.sql"
EXPECTED_FROM = "2.5.0"
EXPECTED_TO = "2.6.0"
REQUIRED_TABLES = {
    "industry_taxonomies", "industry_nodes", "organization_industry_assignments",
    "market_universe_snapshots", "market_universe_members",
    "organization_business_activities", "organization_property_occupancies",
}
REQUIRED_VIEWS = {"v_company_universe_current", "v_company_real_estate_timeline", "v_company_event_universe_context"}


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5) if readonly else sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def version(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()
    return row[0] if row else ""


def backup(source_path: Path, backup_path: Path) -> dict[str, object]:
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = connect(source_path, readonly=True); target = connect(backup_path)
    try:
        source.backup(target); target.commit()
        quick = target.execute("PRAGMA quick_check").fetchone()[0]
        fk = target.execute("PRAGMA foreign_key_check").fetchall()
        schema_version = version(target)
        if quick != "ok" or fk:
            raise RuntimeError(f"backup validation failed: quick={quick}, fk={len(fk)}")
    finally:
        target.close(); source.close()
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    manifest = {
        "source": str(source_path.resolve()), "backup": str(backup_path.resolve()),
        "createdAt": datetime.now(timezone.utc).isoformat(), "schemaVersion": schema_version,
        "bytes": backup_path.stat().st_size, "sha256": digest,
        "quickCheck": quick, "foreignKeyViolations": len(fk),
    }
    backup_path.with_suffix(backup_path.suffix + ".manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("db", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    db_path = args.db.resolve()
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")
    con = connect(db_path)
    try: current = version(con)
    finally: con.close()
    if current == EXPECTED_TO:
        print(json.dumps({"status": "already_applied", "schemaVersion": current}, ensure_ascii=False)); return
    if current != EXPECTED_FROM:
        raise SystemExit(f"Expected schema {EXPECTED_FROM}, found {current}")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = (args.backup or db_path.parent.parent / "backups" / f"market-pre-v2.6.0-{stamp}.db").resolve()
    manifest = backup(db_path, backup_path)
    con = connect(db_path)
    try:
        con.executescript(MIGRATION.read_text(encoding="utf-8"))
        actual = version(con)
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        views = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='view'")}
        missing = sorted((REQUIRED_TABLES - tables) | (REQUIRED_VIEWS - views))
        stage_count = con.execute("SELECT COUNT(*) FROM event_stages WHERE stage_code LIKE 'RELOCATION_%'").fetchone()[0]
        predicate_count = con.execute("SELECT COUNT(*) FROM predicate_definitions WHERE predicate_code IN ('BUSINESS_DOMAIN','INVESTMENT_PLAN_AMOUNT','INVESTMENT_PLAN_DESCRIPTION','HEADCOUNT_PLAN','RELOCATION_ORIGIN','RELOCATION_DESTINATION','EXPECTED_MOVE_IN_DATE')").fetchone()[0]
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if actual != EXPECTED_TO or missing or stage_count != 6 or predicate_count != 7 or integrity != "ok" or fk:
            raise RuntimeError(f"migration validation failed: version={actual}, missing={missing}, stages={stage_count}, predicates={predicate_count}, integrity={integrity}, fk={len(fk)}")
        con.commit()
    finally:
        con.close()
    print(json.dumps({"status": "applied", "from": current, "to": actual, "backup": manifest, "integrityCheck": integrity, "foreignKeyViolations": len(fk)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
