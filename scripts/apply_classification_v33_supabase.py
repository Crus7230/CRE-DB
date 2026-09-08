#!/usr/bin/env python
"""Apply V3.3 classification migration and backfill to Supabase atomically.

Default is a rollback rehearsal. Pass --apply to commit. No credentials are emitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_record_classifications import (  # noqa: E402
    _load_env,
    backfill_classifications,
    classification_qa,
)

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.3.0_classification_taxonomy.sql"
DEFAULT_REPORT = ROOT / "artifacts" / "classification-v33-supabase-apply.json"


def apply_v33(env_file: Path, *, apply: bool) -> dict:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = _load_env(env_file)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL or DATABASE_URL is missing")

    conn = psycopg.connect(dsn, connect_timeout=20)
    try:
        conn.execute("SET statement_timeout TO 0")
        before = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        if before == "3.2.0":
            conn.execute(MIGRATION.read_text(encoding="utf-8"), prepare=False)
        elif before != "3.3.0":
            raise RuntimeError(f"expected Supabase schema 3.2.0 or 3.3.0, found {before}")

        backfill = backfill_classifications(conn, apply=True, commit=False)
        qa = classification_qa(conn)
        after = conn.execute(
            "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'"
        ).fetchone()[0]
        if after != "3.3.0" or qa["primary_conflicts"]:
            raise RuntimeError({"schema_version": after, "qa": qa})
        if apply:
            conn.commit()
            status = "applied"
            persisted_after = after
        else:
            conn.rollback()
            status = "rollback_rehearsal"
            persisted_after = conn.execute(
                "SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'"
            ).fetchone()[0]
        return {
            "status": status,
            "schema_before": before,
            "schema_after_in_transaction": after,
            "persisted_schema_after": persisted_after,
            "backfill": backfill,
            "qa": qa,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    result = apply_v33(args.env_file.resolve(), apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    result["report"] = str(args.report.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
