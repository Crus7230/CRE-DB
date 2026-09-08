#!/usr/bin/env python
"""Stage a compact historical search index from an immutable SQLite archive.

This command is intentionally non-destructive: it only inserts/updates archive
snapshot metadata and compact index rows in Supabase.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
SUPPORTED_KINDS = {"DOCUMENT", "EVENT", "SALE_PROCESS", "LP_MANDATE", "MACRO_OBSERVATION"}
TABLE_BY_KIND = {
    "DOCUMENT": "source_documents",
    "EVENT": "events",
    "SALE_PROCESS": "sale_processes",
    "LP_MANDATE": "lp_mandates",
    "MACRO_OBSERVATION": "macro_observations",
}
ACTIVE_SALE = {"OPEN", "MARKETED", "BIDDING", "DUE_DILIGENCE", "PREFERRED_NEGOTIATION", "SPA_NEGOTIATION", "REAUCTION", "SUSPENDED"}
ACTIVE_MANDATE = {"OPEN", "UNKNOWN", "REVIEW"}


def deterministic_index_id(record_kind: str, record_id: str) -> str:
    return hashlib.sha256(f"archive-index:{record_kind}:{record_id}".encode()).hexdigest()[:32]


def _clean_text(value: str | None, limit: int | None = None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned[:limit] if limit is not None else cleaned


def compact_index_row(
    *, snapshot_id: str, snapshot_sha256: str, record_kind: str, record_id: str,
    title: str, status: str | None, category: str | None, date_start: str | None,
    date_end: str | None, publisher: str | None, url: str | None, summary: str | None,
    source_document_id: str | None, source_document_version_id: str | None,
    indexed_at: str,
) -> dict[str, Any]:
    if record_kind not in SUPPORTED_KINDS:
        raise ValueError(f"unsupported record kind: {record_kind}")
    title_clean = _clean_text(title) or f"{record_kind} {record_id}"
    return {
        "archive_index_id": deterministic_index_id(record_kind, record_id),
        "archive_snapshot_id": snapshot_id,
        "record_kind": record_kind,
        "record_id": record_id,
        "canonical_title": title_clean,
        "lifecycle_status": status,
        "category_code": category,
        "event_date_start": date_start,
        "event_date_end": date_end,
        "publisher_name": _clean_text(publisher, 200),
        "canonical_url": url,
        "summary_text": _clean_text(summary, 500),
        "source_document_id": source_document_id,
        "source_document_version_id": source_document_version_id,
        "archive_locator": f"sqlite://{snapshot_id}#table={TABLE_BY_KIND[record_kind]}&pk={record_id}",
        "archive_snapshot_sha256": snapshot_sha256,
        "indexed_at": indexed_at,
        "metadata_json": "{}",
    }


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        text = raw.strip()
        if text and not text.startswith("#") and "=" in text:
            key, value = text.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def validate_snapshot(path: Path) -> dict[str, Any]:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        version = conn.execute("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        row_count = sum(conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables if not t.startswith("document_fts"))
    finally:
        conn.close()
    if integrity != "ok" or fk:
        raise RuntimeError(f"archive validation failed: integrity={integrity}, fk={len(fk)}")
    if version not in {"3.2.0", "3.3.0", "3.4.0", "3.4.1", "3.5.0"}:
        raise RuntimeError(f"archive schema must be 3.2.0, 3.3.0, 3.4.0, 3.4.1 or 3.5.0, found {version}")
    return {"sha256": digest, "schema_version": version, "table_count": len(tables), "row_count": row_count, "integrity": integrity, "foreign_key_violations": len(fk)}


def _prepare_keep_sets(conn: sqlite3.Connection) -> None:
    conn.executescript("""
    CREATE TEMP TABLE keep_events AS SELECT event_id FROM events WHERE lifecycle_status='ACTIVE';
    CREATE TEMP TABLE keep_sales AS SELECT sale_process_id,event_id,source_claim_id FROM sale_processes WHERE process_status IN ('OPEN','MARKETED','BIDDING','DUE_DILIGENCE','PREFERRED_NEGOTIATION','SPA_NEGOTIATION','REAUCTION','SUSPENDED');
    CREATE TEMP TABLE keep_mandates AS SELECT mandate_id,event_id,source_claim_id FROM lp_mandates WHERE mandate_status IN ('OPEN','UNKNOWN','REVIEW');
    CREATE TEMP TABLE keep_runs AS SELECT run_id FROM (SELECT r.run_id,row_number() over(partition by r.job_id order by r.started_at desc) rn FROM collection_runs r JOIN collection_jobs j ON j.job_id=r.job_id AND j.is_active=1) WHERE rn=1;
    CREATE TEMP TABLE keep_mentions(event_mention_id TEXT PRIMARY KEY);
    INSERT OR IGNORE INTO keep_mentions SELECT event_mention_id FROM event_mentions WHERE status_code IN ('REVIEW_READY','EXTRACTED');
    INSERT OR IGNORE INTO keep_mentions SELECT target_id FROM review_tasks WHERE status_code IN ('PENDING','IN_PROGRESS') AND target_kind='EVENT_MENTION';
    INSERT OR IGNORE INTO keep_mentions SELECT l.event_mention_id FROM event_mention_links l JOIN keep_events e USING(event_id);
    INSERT OR IGNORE INTO keep_mentions SELECT c.event_mention_id FROM claims c WHERE c.claim_id IN (SELECT source_claim_id FROM keep_sales WHERE source_claim_id IS NOT NULL UNION SELECT source_claim_id FROM keep_mandates WHERE source_claim_id IS NOT NULL);
    CREATE TEMP TABLE keep_claims AS SELECT DISTINCT c.claim_id,c.event_mention_id FROM claims c WHERE c.verification_status='PENDING' OR c.event_mention_id IN (SELECT event_mention_id FROM keep_mentions) OR c.claim_id IN (SELECT target_id FROM review_tasks WHERE status_code IN ('PENDING','IN_PROGRESS') AND target_kind='CLAIM') OR c.claim_id IN (SELECT source_claim_id FROM keep_sales WHERE source_claim_id IS NOT NULL UNION SELECT source_claim_id FROM keep_mandates WHERE source_claim_id IS NOT NULL);
    INSERT OR IGNORE INTO keep_mentions SELECT event_mention_id FROM keep_claims WHERE event_mention_id IS NOT NULL;
    CREATE TEMP TABLE latest_versions AS SELECT document_version_id,document_id FROM (SELECT document_version_id,document_id,row_number() over(partition by document_id order by version_no desc,document_version_id desc) rn FROM document_versions) WHERE rn=1;
    CREATE TEMP TABLE keep_versions(document_version_id TEXT PRIMARY KEY);
    INSERT OR IGNORE INTO keep_versions SELECT DISTINCT lv.document_version_id FROM latest_versions lv JOIN document_scope_assessments a USING(document_version_id) WHERE a.status_code LIKE 'CRE_REVIEW%';
    INSERT OR IGNORE INTO keep_versions SELECT DISTINCT er.document_version_id FROM extraction_runs er JOIN event_mentions em USING(extraction_run_id) JOIN keep_mentions km USING(event_mention_id);
    INSERT OR IGNORE INTO keep_versions SELECT DISTINCT rd.document_version_id FROM run_documents rd JOIN keep_runs kr USING(run_id);
    INSERT OR IGNORE INTO keep_versions SELECT source_document_version_id FROM macro_observations WHERE macro_observation_id IN (SELECT macro_observation_id FROM (SELECT o.macro_observation_id,row_number() over(partition by o.macro_series_id order by o.revision_no desc,o.vintage_at desc) rn FROM macro_observations o JOIN macro_series s USING(macro_series_id) WHERE s.is_active=1) WHERE rn=1) AND source_document_version_id IS NOT NULL;
    INSERT OR IGNORE INTO keep_versions SELECT source_document_version_id FROM market_universe_snapshots WHERE universe_snapshot_id IN (SELECT universe_snapshot_id FROM (SELECT universe_snapshot_id,row_number() over(partition by market_code,universe_code order by snapshot_date desc) rn FROM market_universe_snapshots) WHERE rn=1) AND source_document_version_id IS NOT NULL;
    CREATE TEMP TABLE keep_documents AS SELECT DISTINCT v.document_id FROM document_versions v JOIN keep_versions k USING(document_version_id);
    """)


def _source_for_claim(conn: sqlite3.Connection, claim_id: str | None) -> sqlite3.Row | None:
    if not claim_id:
        return None
    return conn.execute("""SELECT sd.document_id,dv.document_version_id,sd.publisher_name,sd.canonical_url,dv.title,dv.snippet_text
      FROM claims c JOIN event_mentions em ON em.event_mention_id=c.event_mention_id
      JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
      JOIN document_versions dv ON dv.document_version_id=er.document_version_id
      JOIN source_documents sd ON sd.document_id=dv.document_id WHERE c.claim_id=? LIMIT 1""", (claim_id,)).fetchone()


def build_rows(path: Path, snapshot_id: str, sha256: str, indexed_at: str) -> list[dict[str, Any]]:
    conn = sqlite3.connect(f"file:{path.resolve().as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    try:
        _prepare_keep_sets(conn)
        for r in conn.execute("""SELECT sd.document_id,sd.publisher_name,sd.canonical_url,sd.document_type,dv.document_version_id,dv.title,dv.snippet_text,dv.published_at,dv.collected_at
          FROM source_documents sd JOIN latest_versions lv ON lv.document_id=sd.document_id JOIN document_versions dv ON dv.document_version_id=lv.document_version_id
          WHERE sd.document_id NOT IN (SELECT document_id FROM keep_documents)"""):
            rows.append(compact_index_row(snapshot_id=snapshot_id,snapshot_sha256=sha256,record_kind="DOCUMENT",record_id=r["document_id"],title=r["title"],status="ARCHIVED",category=r["document_type"],date_start=r["published_at"] or r["collected_at"],date_end=None,publisher=r["publisher_name"],url=r["canonical_url"],summary=r["snippet_text"],source_document_id=r["document_id"],source_document_version_id=r["document_version_id"],indexed_at=indexed_at))
        for r in conn.execute("""SELECT e.*,ec.code category_code FROM events e LEFT JOIN event_categories ec ON ec.event_category_id=e.primary_category_id WHERE e.event_id NOT IN (SELECT event_id FROM keep_events)"""):
            src = conn.execute("""SELECT sd.document_id,dv.document_version_id,sd.publisher_name,sd.canonical_url,dv.snippet_text FROM event_mention_links l JOIN event_mentions em USING(event_mention_id) JOIN extraction_runs er USING(extraction_run_id) JOIN document_versions dv USING(document_version_id) JOIN source_documents sd USING(document_id) WHERE l.event_id=? ORDER BY dv.version_no DESC LIMIT 1""",(r["event_id"],)).fetchone()
            rows.append(compact_index_row(snapshot_id=snapshot_id,snapshot_sha256=sha256,record_kind="EVENT",record_id=r["event_id"],title=r["canonical_title"],status=r["lifecycle_status"],category=r["category_code"],date_start=r["event_date_start"],date_end=r["event_date_end"],publisher=src["publisher_name"] if src else None,url=src["canonical_url"] if src else None,summary=src["snippet_text"] if src else None,source_document_id=src["document_id"] if src else None,source_document_version_id=src["document_version_id"] if src else None,indexed_at=indexed_at))
        for r in conn.execute("""SELECT sp.*,e.canonical_title FROM sale_processes sp LEFT JOIN events e USING(event_id) WHERE sp.sale_process_id NOT IN (SELECT sale_process_id FROM keep_sales)"""):
            src=_source_for_claim(conn,r["source_claim_id"])
            rows.append(compact_index_row(snapshot_id=snapshot_id,snapshot_sha256=sha256,record_kind="SALE_PROCESS",record_id=r["sale_process_id"],title=r["canonical_title"] or r["process_code"],status=r["process_status"],category="SALE",date_start=r["launched_at"],date_end=r["closed_at"],publisher=src["publisher_name"] if src else None,url=src["canonical_url"] if src else None,summary=r["process_code"],source_document_id=src["document_id"] if src else None,source_document_version_id=src["document_version_id"] if src else None,indexed_at=indexed_at))
        for r in conn.execute("SELECT * FROM lp_mandates WHERE mandate_id NOT IN (SELECT mandate_id FROM keep_mandates)"):
            src=_source_for_claim(conn,r["source_claim_id"])
            rows.append(compact_index_row(snapshot_id=snapshot_id,snapshot_sha256=sha256,record_kind="LP_MANDATE",record_id=r["mandate_id"],title=r["mandate_name"],status=r["mandate_status"],category="INSTITUTIONAL_CAPITAL",date_start=r["announced_at"],date_end=r["selected_at"],publisher=src["publisher_name"] if src else None,url=src["canonical_url"] if src else None,summary=r["mandate_scope"],source_document_id=src["document_id"] if src else None,source_document_version_id=src["document_version_id"] if src else None,indexed_at=indexed_at))
        for r in conn.execute("""SELECT o.*,s.series_name_ko FROM macro_observations o JOIN macro_series s USING(macro_series_id) WHERE o.macro_observation_id NOT IN (SELECT macro_observation_id FROM (SELECT o2.macro_observation_id,row_number() over(partition by o2.macro_series_id order by o2.revision_no desc,o2.vintage_at desc) rn FROM macro_observations o2 JOIN macro_series s2 USING(macro_series_id) WHERE s2.is_active=1) WHERE rn=1)"""):
            rows.append(compact_index_row(snapshot_id=snapshot_id,snapshot_sha256=sha256,record_kind="MACRO_OBSERVATION",record_id=r["macro_observation_id"],title=f"{r['series_name_ko']} {r['period_label']}",status=r["observation_status"],category="MACRO",date_start=r["period_start"],date_end=r["period_end"],publisher=None,url=None,summary=r["value_decimal_text"] or r["text_value"],source_document_id=None,source_document_version_id=r["source_document_version_id"],indexed_at=indexed_at))
    finally:
        conn.close()
    return rows


def stage(rows: list[dict[str, Any]], snapshot: dict[str, Any], snapshot_id: str, archive_name: str, env_path: Path) -> None:
    import psycopg
    env=load_env(env_path); schema=env.get("SUPABASE_DB_SCHEMA","market_intelligence")
    with psycopg.connect(env["SUPABASE_DB_URL"]) as conn, conn.transaction():
        version=conn.execute(f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
        if version not in {"3.3.0", "3.4.0", "3.4.1", "3.5.0"}: raise RuntimeError(f"Supabase schema must be 3.3.0, 3.4.0, 3.4.1 or 3.5.0, found {version}")
        conn.execute(f"UPDATE {schema}.archive_snapshots SET is_current=0 WHERE is_current=1")
        conn.execute(f"""INSERT INTO {schema}.archive_snapshots(archive_snapshot_id,created_at,schema_version,archive_format,archive_location,archive_snapshot_sha256,table_count,row_count,integrity_status,foreign_key_violations,is_current,metadata_json)
          VALUES(%s,%s,%s,'SQLITE',%s,%s,%s,%s,'VALIDATED',0,1,%s)
          ON CONFLICT(archive_snapshot_id) DO UPDATE SET is_current=1,integrity_status='VALIDATED',metadata_json=excluded.metadata_json""",
          (snapshot_id,datetime.now(timezone.utc).isoformat(),snapshot["schema_version"],f"local-full-archive/{archive_name}",snapshot["sha256"],snapshot["table_count"],snapshot["row_count"],json.dumps({"integrity":"ok"})))
        columns=list(rows[0]) if rows else []
        if columns:
            sql=f"INSERT INTO {schema}.archived_serving_index({','.join(columns)}) VALUES({','.join(['%s']*len(columns))}) ON CONFLICT(record_kind,record_id) DO UPDATE SET " + ','.join(f"{x}=excluded.{x}" for x in columns if x not in {'archive_index_id','record_kind','record_id'})
            with conn.cursor() as cursor:
                cursor.executemany(sql,[tuple(r[x] for x in columns) for r in rows])
        actual=conn.execute(f"SELECT count(*) FROM {schema}.archived_serving_index WHERE archive_snapshot_id=%s",(snapshot_id,)).fetchone()[0]
        if actual != len(rows): raise RuntimeError(f"staged row mismatch: expected {len(rows)}, found {actual}")


def main() -> None:
    ap=argparse.ArgumentParser();ap.add_argument("--snapshot",type=Path,required=True);ap.add_argument("--env",type=Path,default=DEFAULT_ENV);ap.add_argument("--apply",action="store_true");args=ap.parse_args()
    snapshot=validate_snapshot(args.snapshot.resolve());snapshot_id=f"archive-{snapshot['sha256'][:16]}";now=datetime.now(timezone.utc).isoformat();rows=build_rows(args.snapshot.resolve(),snapshot_id,snapshot['sha256'],now)
    report={"snapshot_id":snapshot_id,"snapshot":snapshot,"compact_rows":len(rows),"by_kind":dict(Counter(r['record_kind'] for r in rows)),"apply":args.apply,"persistent_deletions":0}
    if args.apply: stage(rows,snapshot,snapshot_id,args.snapshot.name,args.env.resolve())
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__ == "__main__": main()
