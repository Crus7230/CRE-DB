"""Rehearse or apply analytics migrations and verified serving sync atomically."""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))
from scripts.backfill_record_classifications import _load_env  # noqa: E402
from scripts.sync_analytics_serving import PK, TABLE_COLUMNS, build_payload, sync_payload  # noqa: E402

ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
DB = ROOT / "data/market.db"
REPORT = ROOT / "artifacts/analytics-v350-supabase-rehearsal.json"
MIGRATIONS = [
    ("3.3.0", "3.4.0", ROOT / "db/v2/migrations/3.4.0_keyword_analytics.sql"),
    ("3.4.0", "3.4.1", ROOT / "db/v2/migrations/3.4.1_insight_signals.sql"),
    ("3.4.1", "3.5.0", ROOT / "db/v2/migrations/3.5.0_model_interpretations.sql"),
]
SECURITY_MIGRATIONS = [ROOT / "db/postgresql/migrations/002_app_security_dashboard_login_rate_limits.sql"]
# Stable two-int key; released by PostgreSQL on transaction commit/rollback.
ANALYTICS_SYNC_LOCK = (0x435245, 0x414E41)
WINDOW_TABLES = ("keyword_observations_daily", "keyword_cooccurrences_daily")


def migration_body(path: Path) -> str:
    body = path.read_text(encoding="utf-8")
    body, begin_count = re.subn(r"(?m)^BEGIN;\s*", "", body, count=1)
    body, commit_count = re.subn(r"(?m)^COMMIT;\s*$", "", body, count=1)
    if begin_count != 1 or commit_count != 1:
        raise RuntimeError(f"migration transaction wrapper not recognized: {path.name}")
    return body


def prepare_payload(payload: dict) -> dict:
    """Validate staging and retain evidence version IDs even for compact archives."""
    for table, columns in TABLE_COLUMNS.items():
        ids = set()
        for row in payload.get(table, []):
            if len(row) != len(columns) or not row[0] or row[0] in ids:
                raise RuntimeError(f"invalid or duplicate staged primary key/row in {table}")
            ids.add(row[0])
    scope = payload.get("_sync_scope", {})
    start, end = scope.get("keyword_start"), scope.get("keyword_end")
    if bool(start) != bool(end) or (start and start >= end):
        raise RuntimeError("invalid half-open keyword sync window")
    for table in WINDOW_TABLES:
        rows = payload.get(table, [])
        if rows and not start:
            raise RuntimeError("keyword rows require an explicit sync window")
        if any(not start <= row[1] < end for row in rows):
            raise RuntimeError(f"staged rows outside keyword sync window: {table}")
    result = dict(payload)
    evidence = []
    cols = TABLE_COLUMNS["insight_signal_evidence"]
    version_index, metadata_index = cols.index("source_document_version_id"), cols.index("metadata_json")
    for row in payload.get("insight_signal_evidence", []):
        values = list(row)
        metadata = json.loads(values[metadata_index] or "{}")
        if not isinstance(metadata, dict):
            raise RuntimeError("insight evidence metadata must be an object")
        if values[version_index]:
            metadata["source_document_version_id"] = values[version_index]
        values[metadata_index] = json.dumps(metadata, ensure_ascii=False)
        evidence.append(tuple(values))
    result["insight_signal_evidence"] = evidence
    return result


def latest_analytics_completion(conn) -> list[dict]:
    """Read actual completion rows, including after commit/rollback."""
    exists = conn.execute("SELECT to_regclass('market_intelligence.analytics_refresh_runs')").fetchone()[0]
    if exists is None:
        return []
    rows = conn.execute("""
        SELECT DISTINCT ON (pipeline_code)
               pipeline_code, analytics_refresh_run_id, completed_at,
               window_start, window_end, input_count, output_count
        FROM market_intelligence.analytics_refresh_runs
        WHERE status_code='COMPLETED' AND completed_at IS NOT NULL
        ORDER BY pipeline_code, completed_at DESC, started_at DESC, analytics_refresh_run_id DESC
    """).fetchall()
    keys = ("pipelineCode", "runId", "completedAt", "windowStart", "windowEnd", "inputCount", "outputCount")
    return [dict(zip(keys, row)) for row in rows]


def _staged_reference_check(conn, table: str, joins: str, invalid: str) -> int:
    pk = PK[table]
    return conn.execute(
        f"SELECT count(*) FROM market_intelligence.{table} target "
        f"JOIN _sync_{table} staged ON staged.{pk}=target.{pk} "
        f"{joins} WHERE {invalid}"
    ).fetchone()[0]


def _archive_exists(kind: str, value: str, column: str = "record_id", extra: str = "") -> str:
    """Only a current validated, checksum-matching compact locator is usable."""
    return (
        "EXISTS (SELECT 1 FROM market_intelligence.archived_serving_index archived "
        "JOIN market_intelligence.archive_snapshots snapshot ON "
        "snapshot.archive_snapshot_id=archived.archive_snapshot_id "
        "AND snapshot.is_current=1 AND snapshot.integrity_status='VALIDATED' "
        "AND snapshot.foreign_key_violations=0 "
        "AND snapshot.archive_snapshot_sha256=archived.archive_snapshot_sha256 "
        f"WHERE archived.record_kind='{kind}' AND archived.{column}={value} "
        f"AND length(trim(archived.archive_locator))>0 {extra})"
    )


def verify_sync(conn, payload: dict, staged: dict) -> dict:
    """Verify reconciled windows/staged IDs, not unrelated retained target rows."""
    scope = payload.get("_sync_scope", {})
    tables, failures = {}, []
    for table in TABLE_COLUMNS:
        pk, expected = PK[table], len(payload.get(table, []))
        total = conn.execute(f"SELECT count(*) FROM market_intelligence.{table}").fetchone()[0]
        matched = conn.execute(
            f"SELECT count(*) FROM _sync_{table} staged "
            f"JOIN market_intelligence.{table} target ON target.{pk}=staged.{pk}"
        ).fetchone()[0]
        result = {"staged": expected, "matchedStagedPrimaryKeys": matched,
                  "missingStagedPrimaryKeys": expected - matched, "targetTotal": total}
        if staged.get(table) != expected or matched != expected:
            failures.append(f"{table}: staged primary keys/counts do not match")
        if table in WINDOW_TABLES and scope.get("keyword_start"):
            target_in_scope = conn.execute(
                f"SELECT count(*) FROM market_intelligence.{table} WHERE bucket_date >= %s AND bucket_date < %s",
                (scope["keyword_start"], scope["keyword_end"]),
            ).fetchone()[0]
            result.update({"scope": "half_open_keyword_window", "targetInScope": target_in_scope,
                           "retainedOutsideScope": total - target_in_scope})
            if target_in_scope != expected:
                failures.append(f"{table}: keyword window reconciliation does not match")
        else:
            result.update({"scope": "staged_primary_keys", "targetInScope": matched,
                           "retainedOutsideScope": total - matched})
        tables[table] = result

    checks = {}
    for table, column in (
        ("keyword_observations_daily", "keyword_id"),
        ("keyword_cooccurrences_daily", "keyword_left_id"),
        ("keyword_cooccurrences_daily", "keyword_right_id"),
        ("insight_signals", "keyword_id"),
    ):
        checks[f"{table}.{column}"] = _staged_reference_check(
            conn, table,
            f"LEFT JOIN market_intelligence.keyword_dictionary referenced ON referenced.keyword_id=target.{column}",
            f"target.{column} IS NOT NULL AND referenced.keyword_id IS NULL",
        )
    checks["insight_signal_evidence.signal"] = _staged_reference_check(
        conn, "insight_signal_evidence",
        "LEFT JOIN market_intelligence.insight_signals referenced ON referenced.insight_signal_id=target.insight_signal_id",
        "referenced.insight_signal_id IS NULL",
    )
    archived_version = _archive_exists(
        "DOCUMENT", "staged.source_document_version_id", "source_document_version_id",
        "AND (target.target_kind<>'DOCUMENT' OR archived.record_id=target.target_id)",
    )
    checks["insight_signal_evidence.source_document_version"] = _staged_reference_check(
        conn, "insight_signal_evidence",
        "LEFT JOIN market_intelligence.document_versions referenced ON referenced.document_version_id=target.source_document_version_id",
        "(staged.source_document_version_id IS NOT NULL AND "
        "((target.metadata_json::jsonb->>'source_document_version_id') IS DISTINCT FROM staged.source_document_version_id OR "
        "((target.source_document_version_id IS DISTINCT FROM staged.source_document_version_id "
        f"OR referenced.document_version_id IS NULL) AND NOT {archived_version}))) OR "
        "(target.target_kind='DOCUMENT' AND target.source_document_version_id IS NOT NULL "
        "AND referenced.document_id IS DISTINCT FROM target.target_id) OR "
        "(target.target_kind='DOCUMENT_VERSION' AND target.source_document_version_id IS NOT NULL "
        "AND target.source_document_version_id IS DISTINCT FROM target.target_id)",
    )
    for kind, table, pk, archive_column in (
        ("DOCUMENT", "source_documents", "document_id", "record_id"),
        ("DOCUMENT_VERSION", "document_versions", "document_version_id", "source_document_version_id"),
        ("EVENT", "events", "event_id", "record_id"),
        ("CLAIM", "claims", "claim_id", None),
    ):
        archive_kind = "DOCUMENT" if kind == "DOCUMENT_VERSION" else kind
        fallback = f" AND NOT {_archive_exists(archive_kind, 'target.target_id', archive_column)}" if archive_column else ""
        checks[f"insight_signal_evidence.target_{kind.lower()}"] = _staged_reference_check(
            conn, "insight_signal_evidence",
            f"LEFT JOIN market_intelligence.{table} referenced ON referenced.{pk}=target.target_id",
            f"target.target_kind='{kind}' AND referenced.{pk} IS NULL{fallback}",
        )
    checks["insight_interpretation_evidence.signal_alignment"] = _staged_reference_check(
        conn, "insight_interpretation_evidence",
        "LEFT JOIN market_intelligence.insight_interpretations interpretation ON interpretation.interpretation_id=target.interpretation_id "
        "LEFT JOIN market_intelligence.insight_signal_evidence evidence ON evidence.insight_signal_evidence_id=target.insight_signal_evidence_id",
        "interpretation.interpretation_id IS NULL OR evidence.insight_signal_evidence_id IS NULL "
        "OR interpretation.insight_signal_id IS DISTINCT FROM evidence.insight_signal_id",
    )
    checks["analytics_refresh_runs.completion"] = _staged_reference_check(
        conn, "analytics_refresh_runs", "",
        "target.status_code IS DISTINCT FROM staged.status_code OR target.completed_at IS DISTINCT FROM staged.completed_at "
        "OR target.window_start IS DISTINCT FROM staged.window_start OR target.window_end IS DISTINCT FROM staged.window_end",
    )
    failures.extend(f"{name}: {count} invalid staged references/readbacks" for name, count in checks.items() if count)
    if failures:
        raise RuntimeError("analytics sync verification failed: " + "; ".join(failures))
    return {"status": "passed", "keywordWindow": {"startInclusive": scope.get("keyword_start"),
            "endExclusive": scope.get("keyword_end")}, "tables": tables, "invalidReferences": checks}


def run(env_file: Path, db_path: Path, *, apply: bool, sync_only: bool, window_days: int) -> dict:
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("psycopg is required") from exc
    env = _load_env(env_file)
    dsn = env.get("SUPABASE_DB_URL") or env.get("DATABASE_URL")
    if not dsn:
        raise SystemExit("SUPABASE_DB_URL or DATABASE_URL is missing")
    src = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    try:
        src.execute("BEGIN")
        payload = prepare_payload(build_payload(src, window_days))
    finally:
        src.rollback()
        src.close()
    conn = psycopg.connect(dsn, connect_timeout=20)
    try:
        conn.execute("SET lock_timeout='30s'")
        conn.execute("SET statement_timeout='20min'")
        locked = conn.execute("SELECT pg_try_advisory_xact_lock(%s, %s)", ANALYTICS_SYNC_LOCK).fetchone()[0]
        if not locked:
            raise RuntimeError("another analytics serving sync is already running")
        before = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        if sync_only and before != "3.5.0":
            raise RuntimeError(f"sync-only requires Supabase schema 3.5.0, found {before}")
        current = before
        if not sync_only:
            for path in SECURITY_MIGRATIONS:
                conn.execute(migration_body(path), prepare=False)
            while current != "3.5.0":
                migration = next((item for item in MIGRATIONS if item[0] == current), None)
                if migration is None:
                    raise RuntimeError(f"unsupported Supabase analytics schema {current}")
                _, current, path = migration
                conn.execute(migration_body(path), prepare=False)
        staged = sync_payload(conn, payload)
        after = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        if after != "3.5.0":
            raise RuntimeError(f"analytics migration did not reach 3.5.0, found {after}")
        verification = verify_sync(conn, payload, staged)
        latest_in_transaction = latest_analytics_completion(conn)
        if apply:
            conn.commit()
            status = "applied"
        else:
            conn.rollback()
            status = "rollback_rehearsal"
        persisted = conn.execute("SELECT schema_value FROM market_intelligence.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        persisted_latest = latest_analytics_completion(conn)
        return {"status": status, "schemaBefore": before, "schemaAfterInTransaction": after,
                "persistedSchemaAfter": persisted, "windowDays": window_days, "syncOnly": sync_only,
                "migrationDdlApplied": not sync_only, "advisoryLockAcquired": True,
                "stagedRows": staged,
                "targetCountsInTransaction": {table: row["targetTotal"] for table, row in verification["tables"].items()},
                "verification": verification, "latestAnalyticsCompletionInTransaction": latest_in_transaction,
                "persistedLatestAnalyticsCompletion": persisted_latest,
                "completedAt": datetime.now(timezone.utc).isoformat()}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", type=Path, default=ENV)
    parser.add_argument("--db", type=Path, default=DB)
    parser.add_argument("--window-days", type=int, default=90)
    parser.add_argument("--sync-only", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--report", type=Path, default=REPORT)
    args = parser.parse_args()
    result = run(args.env_file, args.db, apply=args.apply, sync_only=args.sync_only, window_days=max(1, args.window_days))
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({**result, "report": str(args.report)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
