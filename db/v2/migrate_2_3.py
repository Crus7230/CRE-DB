"""Apply the V2.3 sale-process migration after a consistent SQLite backup."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parent
MIGRATION = ROOT / "migrations" / "2.3.0_sale_process.sql"
EXPECTED_FROM = "2.2.0"
EXPECTED_TO = "2.3.0"
REQUIRED_TABLES = {
    "sale_processes", "sale_process_roles", "bid_rounds",
    "bidder_participations", "bidder_participation_members",
    "bid_submissions", "bid_funding_components", "bid_decisions",
    "transaction_milestones",
}


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        con = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True, timeout=5)
    else:
        con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    return con


def version(con: sqlite3.Connection) -> str:
    row = con.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
    ).fetchone()
    return row[0] if row else ""


def backup(source_path: Path, backup_path: Path) -> dict[str, object]:
    if backup_path.exists():
        raise FileExistsError(f"Refusing to overwrite backup: {backup_path}")
    backup_path.parent.mkdir(parents=True, exist_ok=True)
    source = connect(source_path, readonly=True)
    target = connect(backup_path)
    try:
        source.backup(target)
        target.commit()
        quick = target.execute("PRAGMA quick_check").fetchone()[0]
        fk = target.execute("PRAGMA foreign_key_check").fetchall()
        schema_version = version(target)
        if quick != "ok" or fk:
            raise RuntimeError(f"backup validation failed: quick={quick}, fk={len(fk)}")
    finally:
        target.close()
        source.close()
    digest = hashlib.sha256(backup_path.read_bytes()).hexdigest()
    manifest = {
        "source": str(source_path.resolve()),
        "backup": str(backup_path.resolve()),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "schemaVersion": schema_version,
        "bytes": backup_path.stat().st_size,
        "sha256": digest,
        "quickCheck": quick,
        "foreignKeyViolations": len(fk),
    }
    backup_path.with_suffix(backup_path.suffix + ".manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
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
    try:
        current = version(con)
    finally:
        con.close()
    if current == EXPECTED_TO:
        print(json.dumps({"status": "already_applied", "schemaVersion": current}, ensure_ascii=False))
        return
    if current != EXPECTED_FROM:
        raise SystemExit(f"Expected schema {EXPECTED_FROM}, found {current}")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = (args.backup or db_path.parent.parent / "backups" / f"market-pre-v2.3.0-{stamp}.db").resolve()
    manifest = backup(db_path, backup_path)

    con = connect(db_path)
    try:
        con.executescript(MIGRATION.read_text(encoding="utf-8"))
        actual = version(con)
        tables = {
            row[0] for row in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        missing = sorted(REQUIRED_TABLES - tables)
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk = con.execute("PRAGMA foreign_key_check").fetchall()
        if actual != EXPECTED_TO or missing or integrity != "ok" or fk:
            raise RuntimeError(
                f"migration validation failed: version={actual}, missing={missing}, "
                f"integrity={integrity}, fk={len(fk)}"
            )
        con.commit()
    finally:
        con.close()
    print(json.dumps({
        "status": "applied",
        "from": current,
        "to": actual,
        "backup": manifest,
        "requiredTables": len(REQUIRED_TABLES),
        "integrityCheck": integrity,
        "foreignKeyViolations": len(fk),
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
