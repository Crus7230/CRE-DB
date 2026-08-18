"""Create a consistent SQLite backup and a SHA-256 manifest."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        uri = f"file:{path.resolve().as_posix()}?mode=ro"
        con = sqlite3.connect(uri, uri=True, timeout=5)
    else:
        con = sqlite3.connect(path, timeout=5)
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    return con


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    source_path = args.source.resolve()
    output_path = args.output.resolve()
    if not source_path.exists():
        raise SystemExit(f"Source database not found: {source_path}")
    if output_path.exists():
        raise SystemExit(f"Refusing to overwrite backup: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    source = connect(source_path, readonly=True)
    target = connect(output_path)
    try:
        source.backup(target)
        target.commit()
        integrity = target.execute("PRAGMA quick_check").fetchone()[0]
        fk_violations = target.execute("PRAGMA foreign_key_check").fetchall()
        schema_version_row = target.execute(
            "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
        ).fetchone()
        schema_version = schema_version_row[0] if schema_version_row else None
        if integrity != "ok" or fk_violations:
            raise RuntimeError(
                f"backup validation failed: integrity={integrity}, foreign_keys={len(fk_violations)}"
            )
    finally:
        target.close()
        source.close()

    digest = hashlib.sha256(output_path.read_bytes()).hexdigest()
    manifest = {
        "source": str(source_path),
        "backup": str(output_path),
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "schemaVersion": schema_version,
        "bytes": output_path.stat().st_size,
        "sha256": digest,
        "quickCheck": integrity,
        "foreignKeyViolations": len(fk_violations),
    }
    manifest_path = output_path.with_suffix(output_path.suffix + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
