#!/usr/bin/env python
"""Retire superseded collection history after a validated full archive exists."""
from __future__ import annotations

import argparse
from pathlib import Path
import json
from typing import Any

DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
ACTIVE_RUN_STATUSES = {"STARTED", "RUNNING", "IN_PROGRESS", "QUEUED"}


def load_env(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if text and not text.startswith("#") and "=" in text:
            key, value = text.split("=", 1)
            out[key.strip()] = value.strip().strip("\"'")
    return out


def ensure_retire_gate(
    *, requested_snapshot_id: str, current_snapshot: dict[str, Any],
    staged_rows: int, expected_minimum_rows: int,
) -> None:
    valid = (
        current_snapshot.get("snapshot_id") == requested_snapshot_id
        and current_snapshot.get("integrity_status") == "VALIDATED"
        and current_snapshot.get("is_current") is True
        and staged_rows >= expected_minimum_rows
    )
    if not valid:
        raise RuntimeError("snapshot gate failed: current validated snapshot and staged index are required")


def counts(conn: Any, schema: str) -> dict[str, int]:
    q = f'"{schema}"'
    sql = f"""
    WITH keep_runs AS (
      SELECT run_id FROM (
        SELECT DISTINCT ON (r.job_id) r.run_id
        FROM {q}.collection_runs r JOIN {q}.collection_jobs j ON j.job_id=r.job_id AND j.is_active=1
        ORDER BY r.job_id,r.started_at DESC,r.run_id DESC
      ) latest
      UNION
      SELECT run_id FROM {q}.collection_runs WHERE status_code IN ('STARTED','RUNNING','IN_PROGRESS','QUEUED')
    ), old_runs AS (SELECT run_id FROM {q}.collection_runs WHERE run_id NOT IN (SELECT run_id FROM keep_runs))
    SELECT
      (SELECT count(*) FROM old_runs),
      (SELECT count(*) FROM {q}.run_documents WHERE run_id IN (SELECT run_id FROM old_runs)),
      (SELECT count(*) FROM {q}.audit_log WHERE run_id IN (SELECT run_id FROM old_runs)),
      (SELECT count(*) FROM {q}.relationship_resolution_runs WHERE collection_run_id IN (SELECT run_id FROM old_runs)),
      (SELECT count(*) FROM {q}.snapshots WHERE collection_run_id IN (SELECT run_id FROM old_runs)),
      (SELECT count(*) FROM {q}.review_tasks WHERE status_code NOT IN ('PENDING','IN_PROGRESS')),
      (SELECT count(*) FROM {q}.collection_jobs WHERE is_active=0)
    """
    values = conn.execute(sql).fetchone()
    keys = ["collection_runs", "run_documents", "audit_log", "relationship_resolution_runs", "snapshots", "review_tasks", "inactive_collection_jobs"]
    return dict(zip(keys, values))


def run(snapshot_id: str, env_path: Path, apply: bool) -> dict[str, Any]:
    import psycopg
    env=load_env(env_path);schema=env.get("SUPABASE_DB_SCHEMA","market_intelligence");q=f'"{schema}"'
    with psycopg.connect(env["SUPABASE_DB_URL"]) as conn:
        row=conn.execute(f"SELECT archive_snapshot_id,integrity_status,is_current FROM {q}.archive_snapshots WHERE is_current=1").fetchone()
        current={"snapshot_id":row[0],"integrity_status":row[1],"is_current":bool(row[2])} if row else {}
        staged=conn.execute(f"SELECT count(*) FROM {q}.archived_serving_index WHERE archive_snapshot_id=%s",(snapshot_id,)).fetchone()[0]
        ensure_retire_gate(requested_snapshot_id=snapshot_id,current_snapshot=current,staged_rows=staged,expected_minimum_rows=1)
        in_flight=conn.execute(f"SELECT count(*) FROM {q}.collection_runs WHERE status_code IN ('STARTED','RUNNING','IN_PROGRESS','QUEUED')").fetchone()[0]
        if in_flight: raise RuntimeError(f"collector is active; refusing retire with {in_flight} in-flight runs")
        before=counts(conn,schema)
        if not apply:
            return {"apply":False,"snapshot_id":snapshot_id,"staged_index_rows":staged,"would_retire":before}
        with conn.transaction():
            conn.execute("SELECT pg_advisory_xact_lock(70832026)")
            conn.execute(f"""CREATE TEMP TABLE retire_runs ON COMMIT DROP AS
              WITH latest AS (SELECT DISTINCT ON (r.job_id) r.run_id FROM {q}.collection_runs r JOIN {q}.collection_jobs j ON j.job_id=r.job_id AND j.is_active=1 ORDER BY r.job_id,r.started_at DESC,r.run_id DESC)
              SELECT run_id FROM {q}.collection_runs WHERE run_id NOT IN (SELECT run_id FROM latest) AND status_code NOT IN ('STARTED','RUNNING','IN_PROGRESS','QUEUED')""")
            conn.execute(f"DELETE FROM {q}.audit_log WHERE run_id IN (SELECT run_id FROM retire_runs)")
            conn.execute(f"DELETE FROM {q}.relationship_resolution_runs WHERE collection_run_id IN (SELECT run_id FROM retire_runs)")
            conn.execute(f"DELETE FROM {q}.snapshots WHERE collection_run_id IN (SELECT run_id FROM retire_runs)")
            conn.execute(f"DELETE FROM {q}.review_tasks WHERE status_code NOT IN ('PENDING','IN_PROGRESS')")
            conn.execute(f"DELETE FROM {q}.collection_runs WHERE run_id IN (SELECT run_id FROM retire_runs)")
            conn.execute(f"DELETE FROM {q}.collection_job_categories c USING {q}.collection_jobs j WHERE c.job_id=j.job_id AND j.is_active=0 AND NOT EXISTS (SELECT 1 FROM {q}.collection_runs r WHERE r.job_id=j.job_id)")
            conn.execute(f"DELETE FROM {q}.collection_jobs j WHERE j.is_active=0 AND NOT EXISTS (SELECT 1 FROM {q}.collection_runs r WHERE r.job_id=j.job_id)")
        after={k:conn.execute(f"SELECT count(*) FROM {q}.{k}").fetchone()[0] for k in ["collection_runs","run_documents","audit_log","relationship_resolution_runs","snapshots","review_tasks","collection_jobs"]}
        return {"apply":True,"snapshot_id":snapshot_id,"staged_index_rows":staged,"retired":before,"remaining":after}


def main() -> None:
    p=argparse.ArgumentParser();p.add_argument("--snapshot-id",required=True);p.add_argument("--env",type=Path,default=DEFAULT_ENV);p.add_argument("--apply",action="store_true");args=p.parse_args()
    print(json.dumps(run(args.snapshot_id,args.env.resolve(),args.apply),ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
