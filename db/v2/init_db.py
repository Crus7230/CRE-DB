"""Initialize a new V2 market.db without synthetic event data."""
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--force", action="store_true", help="replace an existing database")
    args = parser.parse_args()
    output = args.output.resolve()

    if output.exists() and not args.force:
        raise SystemExit(f"Refusing to overwrite existing database: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()

    con = sqlite3.connect(output, timeout=5)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    try:
        con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((ROOT / "seed.sql").read_text(encoding="utf-8"))
        integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        fk_violations = con.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or fk_violations:
            raise RuntimeError(
                f"database validation failed: integrity={integrity}, foreign_keys={len(fk_violations)}"
            )
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.commit()
        version = con.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        print(f"created={output}")
        print(f"schema_version={version}")
        print(f"integrity={integrity}")
        print(f"foreign_key_violations={len(fk_violations)}")
    finally:
        con.close()


if __name__ == "__main__":
    main()
