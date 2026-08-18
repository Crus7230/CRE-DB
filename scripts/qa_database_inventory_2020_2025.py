from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
OUT_JSON = ROOT / "artifacts" / "database-inventory-2020-2025.json"
OUT_MD = ROOT / "artifacts" / "database-inventory-2020-2025.md"
START = "2020-01-01"
END = "2026-01-01"


def disk_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def scalar(con: sqlite3.Connection, sql: str, args: tuple = ()) -> int | str | None:
    row = con.execute(sql, args).fetchone()
    return row[0] if row else None


def main() -> None:
    con = sqlite3.connect(f"file:{DB.resolve().as_posix()}?mode=ro", uri=True)
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA busy_timeout=5000")
    page_size = int(scalar(con, "PRAGMA page_size") or 0)
    page_count = int(scalar(con, "PRAGMA page_count") or 0)
    freelist = int(scalar(con, "PRAGMA freelist_count") or 0)
    schema_version = scalar(con, "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'")
    quick = scalar(con, "PRAGMA quick_check")
    fk = len(con.execute("PRAGMA foreign_key_check").fetchall())

    table_names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    row_counts = {name: int(scalar(con, f'SELECT COUNT(*) FROM "{name}"') or 0) for name in table_names}
    shadow_prefixes = ("document_fts_",)
    logical_rows = sum(v for k, v in row_counts.items() if not k.startswith(shadow_prefixes))
    physical_rows = sum(row_counts.values())

    try:
        con.execute("CREATE VIRTUAL TABLE temp.dbstat_v USING dbstat(main)")
        top_objects = [
            {"name": r[0], "bytes": int(r[1]), "pages": int(r[2])}
            for r in con.execute(
                "SELECT name,SUM(pgsize),COUNT(*) FROM temp.dbstat_v GROUP BY name ORDER BY SUM(pgsize) DESC LIMIT 25"
            )
        ]
    except sqlite3.OperationalError:
        top_objects = []

    period = {
        "document_versions_published": int(scalar(con, "SELECT COUNT(*) FROM document_versions WHERE published_at>=? AND published_at<?", (START, END)) or 0),
        "distinct_documents_published": int(scalar(con, "SELECT COUNT(DISTINCT document_id) FROM document_versions WHERE published_at>=? AND published_at<?", (START, END)) or 0),
        "document_versions_unknown_published_at": int(scalar(con, "SELECT COUNT(*) FROM document_versions WHERE published_at IS NULL") or 0),
        "event_mentions_by_event_date": int(scalar(con, "SELECT COUNT(*) FROM event_mentions WHERE event_date_start>=? AND event_date_start<?", (START, END)) or 0),
        "canonical_events_by_event_date": int(scalar(con, "SELECT COUNT(*) FROM events WHERE event_date_start>=? AND event_date_start<?", (START, END)) or 0),
        "claims_from_period_published_documents": int(scalar(con, "SELECT COUNT(*) FROM claims c JOIN event_mentions em ON em.event_mention_id=c.event_mention_id JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id JOIN document_versions dv ON dv.document_version_id=er.document_version_id WHERE dv.published_at>=? AND dv.published_at<?", (START, END)) or 0),
        "mentions_from_period_published_documents": int(scalar(con, "SELECT COUNT(*) FROM mentions m JOIN extraction_runs er ON er.extraction_run_id=m.extraction_run_id JOIN document_versions dv ON dv.document_version_id=er.document_version_id WHERE dv.published_at>=? AND dv.published_at<?", (START, END)) or 0),
        "sale_processes_launched": int(scalar(con, "SELECT COUNT(*) FROM sale_processes WHERE launched_at>=? AND launched_at<?", (START, END)) or 0),
        "lp_mandates_vintage": int(scalar(con, "SELECT COUNT(*) FROM lp_mandates WHERE vintage_year BETWEEN 2020 AND 2025") or 0),
        "lp_official_selections": int(scalar(con, "SELECT COUNT(*) FROM lp_mandate_selections s JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id JOIN lp_mandates m ON m.mandate_id=t.mandate_id WHERE m.vintage_year BETWEEN 2020 AND 2025 AND s.review_status='APPROVED'") or 0),
    }
    text_volume = {
        "stored_text_characters": int(scalar(con, "SELECT coalesce(SUM(length(stored_text)),0) FROM document_versions") or 0),
        "snippet_characters": int(scalar(con, "SELECT coalesce(SUM(length(snippet_text)),0) FROM document_versions") or 0),
        "event_summary_characters": int(scalar(con, "SELECT coalesce(SUM(length(summary_raw)),0) FROM event_mentions") or 0),
        "claim_raw_value_characters": int(scalar(con, "SELECT coalesce(SUM(length(raw_value)),0) FROM claims") or 0),
    }
    core_counts = {k: row_counts.get(k, 0) for k in [
        "collection_sources", "collection_jobs", "collection_runs", "source_documents", "document_versions",
        "document_families", "extraction_runs", "mentions", "event_mentions", "claims", "claim_evidence",
        "organizations", "assets", "projects", "events", "event_participants", "sale_processes",
        "sale_process_bids", "lp_mandates", "lp_mandate_tracks", "lp_mandate_guidelines",
        "lp_mandate_amounts", "lp_mandate_selections", "lp_mandate_deployments", "macro_observations",
    ]}
    con.close()

    disk = {
        "market_db_bytes": DB.stat().st_size,
        "market_db_wal_bytes": (DB.with_name(DB.name + "-wal").stat().st_size if DB.with_name(DB.name + "-wal").exists() else 0),
        "market_db_shm_bytes": (DB.with_name(DB.name + "-shm").stat().st_size if DB.with_name(DB.name + "-shm").exists() else 0),
        "raw_directory_bytes": disk_bytes(ROOT / "raw"),
        "artifacts_directory_bytes": disk_bytes(ROOT / "artifacts"),
        "backups_directory_bytes": disk_bytes(ROOT / "backups"),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope": {"start_inclusive": START, "end_exclusive": END},
        "database": {
            "path": str(DB), "schema_version": schema_version, "quick_check": quick,
            "foreign_key_violations": fk, "page_size": page_size, "page_count": page_count,
            "freelist_pages": freelist, "allocated_bytes": page_size * page_count,
            "used_page_bytes_estimate": page_size * (page_count - freelist),
        },
        "disk": disk,
        "row_totals": {"logical_non_fts_shadow_rows": logical_rows, "all_physical_table_rows": physical_rows, "table_count": len(table_names)},
        "core_counts": core_counts,
        "period_counts": period,
        "text_volume": text_volume,
        "top_database_objects": top_objects,
        "all_table_counts": row_counts,
        "caveats": [
            "period counts use table-specific business dates and are not additive",
            "assets, organizations and projects are master rows without a single event-period meaning",
            "unknown published_at rows are reported separately and not assumed to be outside the period",
            "FTS shadow rows are excluded from logical row total but included in physical row total and file bytes",
        ],
    }
    OUT_JSON.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    mib = lambda n: f"{n / 1024 / 1024:,.2f} MiB"
    md = [
        "# Market DB inventory — 2020~2025", "",
        f"- 생성시각: `{result['generated_at']}`", f"- schema: `{schema_version}`",
        f"- quick_check: `{quick}` / FK 위반: `{fk}`", "",
        "## 저장용량", "",
        f"- market.db: **{mib(disk['market_db_bytes'])}** ({disk['market_db_bytes']:,} bytes)",
        f"- SQLite allocated: **{mib(page_size * page_count)}** / free-list: **{freelist:,} pages**",
        f"- raw/: **{mib(disk['raw_directory_bytes'])}**",
        f"- artifacts/: **{mib(disk['artifacts_directory_bytes'])}**",
        f"- backups/: **{mib(disk['backups_directory_bytes'])}**", "",
        "## 논리 정보량", "",
        f"- 논리 row(FTS shadow 제외): **{logical_rows:,}**",
        f"- 물리 table row(FTS 포함): **{physical_rows:,}**",
        f"- source document: **{core_counts['source_documents']:,}** / version: **{core_counts['document_versions']:,}**",
        f"- mention: **{core_counts['mentions']:,}** / event mention: **{core_counts['event_mentions']:,}** / claim: **{core_counts['claims']:,}**",
        f"- organization: **{core_counts['organizations']:,}** / asset: **{core_counts['assets']:,}** / project: **{core_counts['projects']:,}**",
        f"- canonical event: **{core_counts['events']:,}** / sale process: **{core_counts['sale_processes']:,}**",
        f"- LP mandate: **{core_counts['lp_mandates']:,}** / official selection: **{core_counts['lp_mandate_selections']:,}**", "",
        "## 2020~2025 기간 필터", "",
    ]
    md += [f"- {k}: **{v:,}**" for k, v in period.items()]
    md += ["", "## 텍스트량", ""] + [f"- {k}: **{v:,} chars**" for k, v in text_volume.items()]
    md += ["", "## 주의", ""] + [f"- {x}" for x in result["caveats"]]
    OUT_MD.write_text("\n".join(md) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(OUT_JSON), "md": str(OUT_MD), "db_bytes": disk["market_db_bytes"], "logical_rows": logical_rows, "quick_check": quick, "fk": fk}, ensure_ascii=False))


if __name__ == "__main__":
    main()
