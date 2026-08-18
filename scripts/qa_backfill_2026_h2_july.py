from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/work/market-2026-h2-july-staging.db")
    parser.add_argument("--output", default="artifacts/backfill-2026-h2-july-qa.json")
    args = parser.parse_args()
    con = sqlite3.connect(Path(args.db))
    con.row_factory = sqlite3.Row
    integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())
    source_rows = [dict(row) for row in con.execute(
        """SELECT s.source_code,count(DISTINCT d.document_id) AS documents,
                  count(DISTINCT v.document_version_id) AS versions,
                  max(substr(v.published_at,1,10)) AS max_published_date
             FROM source_documents d
             JOIN collection_sources s ON s.source_id=d.source_id
             JOIN document_versions v ON v.document_id=d.document_id
            WHERE substr(v.published_at,1,10)>='2026-07-01'
              AND substr(v.published_at,1,10)<'2026-08-01'
            GROUP BY s.source_code ORDER BY s.source_code"""
    )]
    campaign_runs = dict(con.execute(
        """SELECT count(*) AS total,
                  sum(CASE WHEN cr.status_code='COMPLETED' THEN 1 ELSE 0 END) AS completed,
                  sum(CASE WHEN cr.status_code='FAILED' THEN 1 ELSE 0 END) AS failed
             FROM collection_runs cr JOIN collection_jobs j ON j.job_id=cr.job_id
            WHERE json_extract(j.config_json,'$.campaign')='BACKFILL_2026_H2'"""
    ).fetchone())
    by_job = [dict(row) for row in con.execute(
        """SELECT j.job_code,count(*) AS runs,sum(cr.discovered_count) AS discovered,
                  sum(cr.inserted_count) AS inserted,sum(cr.updated_count) AS updated
             FROM collection_runs cr JOIN collection_jobs j ON j.job_id=cr.job_id
            WHERE json_extract(j.config_json,'$.campaign')='BACKFILL_2026_H2'
            GROUP BY j.job_code ORDER BY j.job_code"""
    )]
    transaction_max = con.execute(
        """SELECT max(json_extract(v.metadata_json,'$.deal_date'))
             FROM document_versions v JOIN source_documents d ON d.document_id=v.document_id
             JOIN collection_sources s ON s.source_id=d.source_id
            WHERE s.source_code='MOLIT_REAL_TRANSACTION'"""
    ).fetchone()[0]
    krx = dict(con.execute(
        """SELECT count(*) AS snapshots,sum(row_count) AS members,max(snapshot_date) AS snapshot_date
             FROM market_universe_snapshots WHERE snapshot_date='2026-07-31'"""
    ).fetchone())
    total_july_docs = sum(int(row["documents"]) for row in source_rows)
    report = {
        "campaign": "BACKFILL_2026_H2",
        "publicationWindow": {"start": "2026-07-01", "endExclusive": "2026-08-01"},
        "generatedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "databaseSha256": hashlib.sha256(Path(args.db).read_bytes()).hexdigest(),
        "integrityCheck": integrity,
        "foreignKeyViolations": fk,
        "campaignRuns": campaign_runs,
        "sourceCoverage": source_rows,
        "totalJulyDocuments": total_july_docs,
        "latestMolitDealDate": transaction_max,
        "krxUniverse": krx,
        "jobCoverage": by_job,
        "assertions": {
            "integrityOk": integrity == "ok",
            "foreignKeysOk": fk == 0,
            "allRunsCompleted": campaign_runs["total"] > 0 and campaign_runs["total"] == campaign_runs["completed"] and campaign_runs["failed"] == 0,
            "publicationThroughJuly31": all(row["max_published_date"] == "2026-07-31" for row in source_rows),
            "krxJuly31Complete": krx["snapshots"] == 2 and krx["members"] == 1016,
        },
    }
    if not all(report["assertions"].values()):
        raise SystemExit(json.dumps(report, ensure_ascii=False))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    con.close()


if __name__ == "__main__":
    main()
