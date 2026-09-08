"""Export source-scoped monthly CRE building-permit series and QA summary."""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).parents[1]
DEFAULT_DB = ROOT / "data/market.db"
DEFAULT_CSV = ROOT / "artifacts/building-permits/seoul-cre-building-permits-monthly.csv"
DEFAULT_QA = ROOT / "artifacts/building-permits/seoul-cre-building-permits-qa.json"


def export(db: Path, source_code: str, csv_path: Path, qa_path: Path) -> dict:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        source = conn.execute(
            "SELECT source_id,source_name FROM collection_sources WHERE source_code=?", (source_code,)
        ).fetchone()
        if not source:
            raise RuntimeError(f"unknown source_code: {source_code}")
        completed = conn.execute(
            """SELECT * FROM building_permit_snapshots
               WHERE source_id=? AND status_code='COMPLETED'
               ORDER BY completed_at DESC LIMIT 1""", (source["source_id"],)
        ).fetchone()
        if not completed:
            raise RuntimeError(f"no completed snapshot for {source_code}")
        rows = [dict(row) for row in conn.execute(
            """SELECT source_id,event_month,event_type,district_name,asset_type,scope_status,
                      construction_action,permit_count,total_floor_area_m2,missing_area_count,invalid_area_count
               FROM v_cre_building_permit_monthly WHERE source_id=?
               ORDER BY event_month,event_type,district_name,asset_type,scope_status,construction_action""",
            (source["source_id"],),
        )]
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [
                "source_id", "event_month", "event_type", "district_name", "asset_type",
                "scope_status", "construction_action", "permit_count", "total_floor_area_m2",
                "missing_area_count", "invalid_area_count",
            ])
            writer.writeheader(); writer.writerows(rows)
        qa = {
            "source": dict(source), "snapshot": dict(completed), "monthlyRows": len(rows),
            "eventCoverage": [dict(row) for row in conn.execute(
                """SELECT event_type,min(event_date) min_date,max(event_date) max_date,count(*) permit_count,
                          round(sum(CASE WHEN total_floor_area_m2 BETWEEN 0 AND 2000000 THEN total_floor_area_m2 ELSE 0 END),2) total_floor_area_m2,
                          sum(CASE WHEN total_floor_area_m2<0 OR total_floor_area_m2>2000000 THEN 1 ELSE 0 END) invalid_area_count
                   FROM v_cre_building_permit_events WHERE source_id=?
                   GROUP BY event_type ORDER BY event_type""", (source["source_id"],)
            )],
            "eventDateQuality": [dict(row) for row in conn.execute(
                """SELECT event_type,quality_status,record_count,min_event_date,max_event_date
                   FROM v_building_permit_event_date_quality WHERE source_id=?
                   ORDER BY event_type,quality_status""", (source["source_id"],)
            )],
            "areaQuality": [dict(row) for row in conn.execute(
                """SELECT quality_status,record_count,min_area_m2,max_area_m2,raw_area_m2
                   FROM v_building_permit_area_quality WHERE source_id=?
                   ORDER BY quality_status""", (source["source_id"],)
            )],
            "classification": [dict(row) for row in conn.execute(
                """SELECT scope_status,asset_type,count(*) permit_count,
                          round(sum(CASE WHEN total_floor_area_m2 BETWEEN 0 AND 2000000 THEN total_floor_area_m2 ELSE 0 END),2) total_floor_area_m2,
                          sum(CASE WHEN total_floor_area_m2<0 OR total_floor_area_m2>2000000 THEN 1 ELSE 0 END) invalid_area_count
                   FROM v_current_cre_building_permit_records WHERE source_id=?
                   GROUP BY scope_status,asset_type ORDER BY permit_count DESC""", (source["source_id"],)
            )],
            "constructionAction": [dict(row) for row in conn.execute(
                """SELECT construction_action,count(*) permit_count,
                          round(sum(CASE WHEN total_floor_area_m2 BETWEEN 0 AND 2000000 THEN total_floor_area_m2 ELSE 0 END),2) total_floor_area_m2,
                          sum(CASE WHEN total_floor_area_m2<0 OR total_floor_area_m2>2000000 THEN 1 ELSE 0 END) invalid_area_count
                   FROM v_current_cre_building_permit_records WHERE source_id=?
                   GROUP BY construction_action ORDER BY permit_count DESC""", (source["source_id"],)
            )],
            "integrity": {
                "foreignKeyViolations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
                "duplicateLatestSourceKeys": conn.execute(
                    """SELECT count(*) FROM (SELECT source_record_key,count(*) n
                       FROM v_latest_building_permit_records WHERE source_id=?
                       GROUP BY source_record_key HAVING count(*)>1)""", (source["source_id"],)
                ).fetchone()[0],
                "monthlyViewHasSourceDimension": "source_id" in {
                    row[1] for row in conn.execute("PRAGMA table_info(v_cre_building_permit_monthly)")
                },
            },
            "csv": str(csv_path),
        }
        qa_path.parent.mkdir(parents=True, exist_ok=True)
        qa_path.write_text(json.dumps(qa, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        return qa
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source-code", default="SEOUL_BUILDING_PERMIT")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--qa", type=Path, default=DEFAULT_QA)
    args = parser.parse_args()
    result = export(args.db, args.source_code, args.csv, args.qa)
    print(json.dumps({"source": args.source_code, "monthlyRows": result["monthlyRows"],
                      "csv": str(args.csv), "qa": str(args.qa)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
