"""Transactional SQLite storage for resumable building-permit snapshots."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
import sqlite3
from typing import Any, Callable

from collector.building_permits import (
    CORE_SCOPE_STATUSES,
    canonical_json,
    classify_cre_permit,
    normalize_buildinghub_record,
    normalize_seoul_record,
    sha256_text,
    stable_id,
    utc_now,
)

SOURCE_DEFINITIONS = {
    "SEOUL_BUILDING_PERMIT": {
        "source_id": "src_seoul_building_permit",
        "source_name": "서울 열린데이터광장 건축인허가 기본개요",
        "source_kind": "OFFICIAL_API",
        "base_url": "https://data.seoul.go.kr/dataList/OA-22404/S/1/datasetView.do",
        "authority_tier": 1,
        "collection_policy": "API_ALLOWED",
        "policy_checked_at": "2026-09-02",
        "config_json": canonical_json({"service": "vBigKcrPmsrgst", "dataset": "OA-22404", "maxRowsPerRequest": 1000}),
    },
    "BUILDING_HUB": {
        "source_id": "src_building_hub",
        "source_name": "국토교통부 건축HUB 건축인허가정보 서비스",
        "source_kind": "OFFICIAL_API",
        "base_url": "https://www.data.go.kr/data/15136267/openapi.do",
        "authority_tier": 1,
        "collection_policy": "API_ALLOWED",
        "policy_checked_at": "2026-09-02",
        "config_json": canonical_json({"service": "ArchPmsHubService", "operation": "getApBasisOulnInfo"}),
    },
}

RECORD_COLUMNS = (
    "source_created_date", "sigungu_code", "bjdong_code", "district_name", "legal_dong_name",
    "parcel_address", "road_address", "parcel_type_code", "main_lot_number", "sub_lot_number",
    "building_name", "construction_type", "main_use_code", "main_use_name", "site_area_m2",
    "building_area_m2", "total_floor_area_m2", "household_count", "unit_count", "family_count",
    "permit_date", "planned_start_date", "delayed_start_date", "actual_start_date", "use_approval_date",
)


@dataclass(frozen=True)
class PageResult:
    fetched: int
    stored: int
    excluded: int
    classification_counts: dict[str, int]
    replayed: bool = False


def ensure_source(conn: sqlite3.Connection, source_code: str) -> str:
    definition = SOURCE_DEFINITIONS[source_code]
    existing = conn.execute(
        "SELECT source_id FROM collection_sources WHERE source_code=?", (source_code,)
    ).fetchone()
    if existing:
        return str(existing[0])
    conn.execute(
        """INSERT INTO collection_sources(
             source_id,source_code,source_name,source_kind,base_url,authority_tier,
             collection_policy,policy_checked_at,config_json,is_active
           ) VALUES(?,?,?,?,?,?,?,?,?,1)""",
        (
            definition["source_id"], source_code, definition["source_name"], definition["source_kind"],
            definition["base_url"], definition["authority_tier"], definition["collection_policy"],
            definition["policy_checked_at"], definition["config_json"],
        ),
    )
    conn.commit()
    return str(definition["source_id"])


def create_snapshot(
    conn: sqlite3.Connection, source_id: str, snapshot_kind: str, page_size: int, started_at: str | None = None,
    *, metadata: dict[str, Any] | None = None,
) -> str:
    started = started_at or utc_now()
    snapshot_id = stable_id("bps", source_id, started, snapshot_kind)
    conn.execute(
        """INSERT INTO building_permit_snapshots(
             snapshot_id,source_id,snapshot_kind,status_code,started_at,page_size,metadata_json
           ) VALUES(?,?,?,'RUNNING',?,?,?)""",
        (snapshot_id, source_id, snapshot_kind, started, page_size, canonical_json(metadata or {})),
    )
    conn.commit()
    return snapshot_id


def _page_receipt(conn: sqlite3.Connection, snapshot_id: str, page_no: int) -> PageResult | None:
    row = conn.execute(
        """SELECT fetched_count,stored_count,excluded_count,classification_counts_json
           FROM building_permit_snapshot_pages WHERE snapshot_id=? AND page_no=?""",
        (snapshot_id, page_no),
    ).fetchone()
    if not row:
        return None
    return PageResult(int(row[0]), int(row[1]), int(row[2]), json.loads(row[3]), True)


def _insert_or_touch_record(
    conn: sqlite3.Connection, source_id: str, normalized: dict[str, Any], raw: dict[str, Any],
    payload_hash: str, observed_at: str,
) -> str:
    key = normalized["source_record_key"]
    existing = conn.execute(
        """SELECT record_version_id FROM building_permit_record_versions
           WHERE source_id=? AND source_record_key=? AND payload_sha256=?""",
        (source_id, key, payload_hash),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE building_permit_record_versions SET last_seen_at=? WHERE record_version_id=?",
            (observed_at, existing[0]),
        )
        return str(existing[0])
    revision = int(conn.execute(
        "SELECT COALESCE(MAX(revision_no),0)+1 FROM building_permit_record_versions WHERE source_id=? AND source_record_key=?",
        (source_id, key),
    ).fetchone()[0])
    record_version_id = stable_id("bpv", source_id, key, payload_hash)
    columns = ",".join(RECORD_COLUMNS)
    placeholders = ",".join("?" for _ in RECORD_COLUMNS)
    values = [normalized.get(column) for column in RECORD_COLUMNS]
    conn.execute(
        f"""INSERT INTO building_permit_record_versions(
              record_version_id,source_id,source_record_key,revision_no,payload_sha256,raw_json,
              {columns},first_seen_at,last_seen_at,created_at
            ) VALUES(?,?,?,?,?,?,{placeholders},?,?,?)""",
        (record_version_id, source_id, key, revision, payload_hash, canonical_json(raw), *values,
         observed_at, observed_at, observed_at),
    )
    return record_version_id


def _ensure_classification(
    conn: sqlite3.Connection, record_version_id: str, classification: dict[str, Any], observed_at: str,
) -> None:
    rule_version = classification["rule_version"]
    existing = conn.execute(
        "SELECT classification_id FROM building_permit_classifications WHERE record_version_id=? AND rule_version=?",
        (record_version_id, rule_version),
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE building_permit_classifications SET is_current=CASE WHEN classification_id=? THEN 1 ELSE 0 END WHERE record_version_id=?",
            (existing[0], record_version_id),
        )
        return
    conn.execute("UPDATE building_permit_classifications SET is_current=0 WHERE record_version_id=?", (record_version_id,))
    classification_id = stable_id("bpc", record_version_id, rule_version)
    conn.execute(
        """INSERT INTO building_permit_classifications(
             classification_id,record_version_id,rule_version,scope_status,asset_type,
             construction_action,confidence_score,is_current,reason_json,classified_at
           ) VALUES(?,?,?,?,?,?,?,1,?,?)""",
        (
            classification_id, record_version_id, rule_version, classification["scope_status"],
            classification["asset_type"], classification["construction_action"],
            classification["confidence_score"], canonical_json(classification["reason"]), observed_at,
        ),
    )


def _refresh_snapshot_totals(conn: sqlite3.Connection, snapshot_id: str) -> None:
    totals = conn.execute(
        """SELECT COALESCE(SUM(fetched_count),0),COALESCE(SUM(stored_count),0),
                  COALESCE(SUM(excluded_count),0),COALESCE(MAX(page_no),0)
           FROM building_permit_snapshot_pages WHERE snapshot_id=?""",
        (snapshot_id,),
    ).fetchone()
    counts: Counter[str] = Counter()
    for (payload,) in conn.execute(
        "SELECT classification_counts_json FROM building_permit_snapshot_pages WHERE snapshot_id=?", (snapshot_id,)
    ):
        counts.update({key: int(value) for key, value in json.loads(payload).items()})
    conn.execute(
        """UPDATE building_permit_snapshots
           SET fetched_count=?,stored_count=?,candidate_count=?,excluded_count=?,request_count=?,
               last_completed_page=?,classification_counts_json=?,cursor_json=?,status_code='RUNNING'
           WHERE snapshot_id=?""",
        (
            int(totals[0]), int(totals[1]), int(totals[1]), int(totals[2]),
            int(totals[3]), int(totals[3]), canonical_json(dict(counts)),
            canonical_json({"nextPage": int(totals[3]) + 1}), snapshot_id,
        ),
    )


def _store_page(
    conn: sqlite3.Connection, snapshot_id: str, source_id: str, rows: list[dict[str, Any]],
    page_no: int, start_row_no: int, normalizer: Callable[[dict[str, Any]], dict[str, Any]],
) -> PageResult:
    replay = _page_receipt(conn, snapshot_id, page_no)
    if replay:
        return replay
    observed_at = conn.execute(
        "SELECT started_at FROM building_permit_snapshots WHERE snapshot_id=? AND source_id=?",
        (snapshot_id, source_id),
    ).fetchone()
    if not observed_at:
        raise ValueError("snapshot/source mismatch")
    timestamp = str(observed_at[0])
    counts: Counter[str] = Counter()
    exclusion: dict[tuple[str, str, str], list[float]] = defaultdict(lambda: [0, 0.0])
    stored = excluded = 0
    try:
        conn.execute("BEGIN IMMEDIATE")
        for offset, raw in enumerate(rows, start=1):
            classification = classify_cre_permit(raw)
            status = classification["scope_status"]
            counts[status] += 1
            normalized = normalizer(raw)
            if status not in CORE_SCOPE_STATUSES:
                excluded += 1
                key = (
                    normalized.get("district_name") or "",
                    normalized.get("main_use_name") or "",
                    status,
                )
                exclusion[key][0] += 1
                exclusion[key][1] += normalized.get("total_floor_area_m2") or 0.0
                continue
            payload = canonical_json(raw)
            payload_hash = sha256_text(payload)
            record_version_id = _insert_or_touch_record(
                conn, source_id, normalized, raw, payload_hash, timestamp
            )
            _ensure_classification(conn, record_version_id, classification, timestamp)
            source_row_no = start_row_no + offset
            conn.execute(
                """INSERT INTO building_permit_snapshot_records(snapshot_id,record_version_id,source_row_no)
                   VALUES(?,?,?) ON CONFLICT(snapshot_id,record_version_id) DO NOTHING""",
                (snapshot_id, record_version_id, source_row_no),
            )
            stored += 1
        for (district, main_use, status), (permit_count, total_area) in exclusion.items():
            conn.execute(
                """INSERT INTO building_permit_exclusion_summary(
                     snapshot_id,district_name,main_use_name,scope_status,permit_count,total_floor_area_m2
                   ) VALUES(?,?,?,?,?,?)
                   ON CONFLICT(snapshot_id,district_name,main_use_name,scope_status) DO UPDATE SET
                     permit_count=permit_count+excluded.permit_count,
                     total_floor_area_m2=total_floor_area_m2+excluded.total_floor_area_m2""",
                (snapshot_id, district, main_use, status, int(permit_count), float(total_area)),
            )
        conn.execute(
            """INSERT INTO building_permit_snapshot_pages(
                 snapshot_id,page_no,start_row_no,fetched_count,stored_count,excluded_count,
                 classification_counts_json,completed_at
               ) VALUES(?,?,?,?,?,?,?,?)""",
            (snapshot_id, page_no, start_row_no, len(rows), stored, excluded, canonical_json(dict(counts)), utc_now()),
        )
        _refresh_snapshot_totals(conn, snapshot_id)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return PageResult(len(rows), stored, excluded, dict(counts), False)


def store_seoul_page(
    conn: sqlite3.Connection, snapshot_id: str, source_id: str, rows: list[dict[str, Any]],
    page_no: int, start_row_no: int,
) -> PageResult:
    return _store_page(conn, snapshot_id, source_id, rows, page_no, start_row_no, normalize_seoul_record)


def store_buildinghub_page(
    conn: sqlite3.Connection, snapshot_id: str, source_id: str, rows: list[dict[str, Any]],
    page_no: int, start_row_no: int,
) -> PageResult:
    return _store_page(conn, snapshot_id, source_id, rows, page_no, start_row_no, normalize_buildinghub_record)


def complete_snapshot(
    conn: sqlite3.Connection, snapshot_id: str, source_total: int, fetched: int, stored: int,
    excluded: int, request_count: int, last_page: int, classification_counts: dict[str, int],
    *, source_as_of_date: str | None = None,
) -> None:
    conn.execute(
        """UPDATE building_permit_snapshots SET status_code='COMPLETED',completed_at=?,source_as_of_date=?,
             source_total_count=?,fetched_count=?,stored_count=?,candidate_count=?,excluded_count=?,
             request_count=?,last_completed_page=?,classification_counts_json=?,cursor_json='{}',error_json='{}'
           WHERE snapshot_id=?""",
        (
            utc_now(), source_as_of_date, source_total, fetched, stored, stored, excluded,
            request_count, last_page, canonical_json(classification_counts), snapshot_id,
        ),
    )
    conn.commit()


def mark_partial(conn: sqlite3.Connection, snapshot_id: str, error: dict[str, Any] | None = None) -> None:
    conn.execute(
        "UPDATE building_permit_snapshots SET status_code='PARTIAL',error_json=? WHERE snapshot_id=?",
        (canonical_json(error or {}), snapshot_id),
    )
    conn.commit()
