#!/usr/bin/env python
"""Materialize a correction-safe MOLIT current-state serving projection.

Only documents linked to completed collection runs are read. Runs are replayed
chronologically at district-month grain because refresh runs may link only
changed rows. A completed run with discovered_count=0 is the sole authoritative
empty-partition signal. Raw archive tables are never updated or deleted.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "market.db"
DEFAULT_MIGRATION = ROOT / "db" / "turso" / "migrations" / "003_molit_current_serving.sql"
SOURCE_CODE = "MOLIT_REAL_TRANSACTION"
DATASET_CODE = "MOLIT_TRANSACTIONS"
PARTITION_TABLE = "serving_molit_completed_partitions"
TRANSACTION_TABLE = "serving_molit_current_transactions"
PARTITION_PATTERN = re.compile(
    r"(?:LAWD_CD|lawd_cd)\s*=\s*(?P<district>[0-9]{5}).*?"
    r"(?:DEAL_YMD|deal_ymd)\s*=\s*(?P<month>[0-9]{6})",
    re.IGNORECASE,
)
MUTABLE_CORRECTION_FIELDS = frozenset({"dealAmount", "cdealDay", "cdealType"})
EXPECTED_SEOUL_DISTRICTS = frozenset({
    "11110", "11140", "11170", "11200", "11215", "11230", "11260",
    "11290", "11305", "11320", "11350", "11380", "11410", "11440",
    "11470", "11500", "11530", "11545", "11560", "11590", "11620",
    "11650", "11680", "11710", "11740",
})
AVAILABLE_COVERAGE_STATUSES = frozenset({
    "COMPLETE_FULL_SNAPSHOT",
    "COMPLETE_EMPTY",
    "COMPLETE_BASELINE_WITH_CHANGES",
})


@dataclass(frozen=True)
class CompletedRun:
    run_id: str
    partition_key: str
    district_code: str
    deal_month: str
    completed_at: str
    created_at: str
    discovered_count: int | None


@dataclass(frozen=True)
class CurrentRecord:
    transaction_key: str
    transaction_key_json: str
    partition_key: str
    source_run_id: str
    source_document_id: str
    document_version_id: str
    api_payload_json: str
    api_payload_sha256: str
    duplicate_occurrence: int
    district_code: str
    district_name: str
    locality: str
    building_use: str
    building_area_text: str
    deal_amount_text: str
    deal_year: str
    deal_month_number: str
    deal_day: str


@dataclass(frozen=True)
class Projection:
    partitions: tuple[dict[str, Any], ...]
    records: tuple[CurrentRecord, ...]
    metadata: dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_text(canonical_json(value))


def partition_from_query(query: str | None) -> tuple[str, str] | None:
    if not query:
        return None
    match = PARTITION_PATTERN.search(query)
    if not match:
        raise RuntimeError(f"completed MOLIT run has no district-month partition: {query!r}")
    district = match.group("district")
    raw_month = match.group("month")
    month_number = int(raw_month[4:])
    if not 1 <= month_number <= 12:
        raise RuntimeError(f"completed MOLIT run has invalid month: {raw_month}")
    if district not in EXPECTED_SEOUL_DISTRICTS:
        return None
    return district, f"{raw_month[:4]}-{raw_month[4:]}"


def inclusive_months(start: str, end: str) -> list[str]:
    year, month = map(int, start.split("-"))
    end_year, end_month = map(int, end.split("-"))
    result: list[str] = []
    while (year, month) <= (end_year, end_month):
        result.append(f"{year:04d}-{month:02d}")
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
    return result


def load_completed_runs(conn: sqlite3.Connection) -> list[CompletedRun]:
    rows = conn.execute(
        """SELECT r.run_id,r.query_rendered,r.completed_at,r.created_at,r.discovered_count
             FROM collection_runs r
             JOIN collection_jobs j ON j.job_id=r.job_id
             JOIN collection_sources s ON s.source_id=j.source_id
            WHERE s.source_code=? AND r.status_code='COMPLETED'
            ORDER BY r.completed_at,r.created_at,r.run_id""",
        (SOURCE_CODE,),
    ).fetchall()
    result: list[CompletedRun] = []
    for row in rows:
        parsed = partition_from_query(row[1])
        if parsed is None:
            continue
        if not row[2]:
            raise RuntimeError(f"completed MOLIT run has no completed_at: {row[0]}")
        district, deal_month = parsed
        result.append(CompletedRun(
            run_id=str(row[0]),
            partition_key=f"{district}:{deal_month}",
            district_code=district,
            deal_month=deal_month,
            completed_at=str(row[2]),
            created_at=str(row[3]),
            discovered_count=None if row[4] is None else int(row[4]),
        ))
    if not result:
        raise RuntimeError("no completed Seoul MOLIT collection partition is available")
    return result


def _chunks(values: list[str], size: int = 400) -> Iterable[list[str]]:
    for offset in range(0, len(values), size):
        yield values[offset:offset + size]


def load_linked_documents(
    conn: sqlite3.Connection,
    run_ids: list[str],
) -> dict[str, list[sqlite3.Row]]:
    previous_row_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    by_run: dict[str, list[sqlite3.Row]] = defaultdict(list)
    try:
        for part in _chunks(run_ids):
            marks = ",".join("?" for _ in part)
            rows = conn.execute(
                f"""SELECT rd.run_id,rd.result_rank,sd.document_id,dv.document_version_id,
                           dv.metadata_json
                      FROM run_documents rd
                      JOIN document_versions dv ON dv.document_version_id=rd.document_version_id
                      JOIN source_documents sd ON sd.document_id=dv.document_id
                     WHERE rd.run_id IN ({marks})
                     ORDER BY rd.run_id,coalesce(rd.result_rank,2147483647),dv.document_version_id""",
                part,
            ).fetchall()
            for row in rows:
                by_run[str(row["run_id"])].append(row)
    finally:
        conn.row_factory = previous_row_factory
    return by_run


def _positive_occurrence(value: Any, document_version_id: str) -> int:
    if isinstance(value, bool):
        raise RuntimeError(f"invalid duplicate occurrence: {document_version_id}")
    try:
        occurrence = int(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid duplicate occurrence: {document_version_id}") from exc
    if occurrence < 1:
        raise RuntimeError(f"invalid duplicate occurrence: {document_version_id}")
    return occurrence


def record_from_link(run: CompletedRun, row: sqlite3.Row) -> tuple[CurrentRecord, bool]:
    try:
        metadata = json.loads(str(row["metadata_json"]))
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid MOLIT metadata: {row['document_version_id']}") from exc
    api_record = metadata.get("api_record") if isinstance(metadata, dict) else None
    if not isinstance(api_record, dict):
        raise RuntimeError(f"missing MOLIT api_record: {row['document_version_id']}")
    occurrence = _positive_occurrence(metadata.get("duplicate_occurrence", 1), str(row["document_version_id"]))
    natural_record = {
        key: value for key, value in api_record.items()
        if key not in MUTABLE_CORRECTION_FIELDS
    }
    transaction_key_json = canonical_json({
        "districtCode": run.district_code,
        "dealMonth": run.deal_month,
        "duplicateOccurrence": occurrence,
        "record": natural_record,
    })
    api_payload_json = canonical_json(api_record)
    text = lambda key: str(api_record.get(key) or "").strip()
    current = CurrentRecord(
        transaction_key=sha256_text(transaction_key_json),
        transaction_key_json=transaction_key_json,
        partition_key=run.partition_key,
        source_run_id=run.run_id,
        source_document_id=str(row["document_id"]),
        document_version_id=str(row["document_version_id"]),
        api_payload_json=api_payload_json,
        api_payload_sha256=sha256_text(api_payload_json),
        duplicate_occurrence=occurrence,
        district_code=run.district_code,
        district_name=text("sggNm"),
        locality=text("umdNm"),
        building_use=text("buildingUse"),
        building_area_text=text("buildingAr"),
        deal_amount_text=text("dealAmount"),
        deal_year=text("dealYear"),
        deal_month_number=text("dealMonth"),
        deal_day=text("dealDay"),
    )
    return current, bool(text("cdealDay"))


def build_projection(conn: sqlite3.Connection) -> Projection:
    runs = load_completed_runs(conn)
    links = load_linked_documents(conn, [run.run_id for run in runs])
    states: dict[str, dict[str, CurrentRecord]] = defaultdict(dict)
    has_baseline: dict[str, bool] = defaultdict(bool)
    latest: dict[str, CompletedRun] = {}
    latest_linked: dict[str, int] = {}
    latest_status: dict[str, str] = {}
    unmatched_cancellations = 0
    for run in runs:
        rows = links.get(run.run_id, [])
        linked_count = len(rows)
        if run.discovered_count is not None and run.discovered_count < linked_count:
            raise RuntimeError(
                f"completed run links exceed discovered_count: {run.run_id} "
                f"({linked_count}>{run.discovered_count})"
            )
        if run.discovered_count == 0:
            if rows:
                raise RuntimeError(f"authoritative empty partition has linked rows: {run.run_id}")
            states[run.partition_key].clear()
            has_baseline[run.partition_key] = True
            coverage_status = "COMPLETE_EMPTY"
        elif run.discovered_count is not None and run.discovered_count == linked_count:
            # Every discovered row is linked, so this run is an authoritative
            # full snapshot. Clear the prior partition before applying it.
            states[run.partition_key].clear()
            for row in rows:
                record, cancelled = record_from_link(run, row)
                if not cancelled:
                    states[run.partition_key][record.transaction_key] = record
            has_baseline[run.partition_key] = True
            coverage_status = "COMPLETE_FULL_SNAPSHOT"
        elif has_baseline[run.partition_key]:
            # A completed run may link only changed documents. It can safely be
            # overlaid only after an authoritative full/empty baseline exists.
            for row in rows:
                record, cancelled = record_from_link(run, row)
                if cancelled:
                    if states[run.partition_key].pop(record.transaction_key, None) is None:
                        unmatched_cancellations += 1
                else:
                    states[run.partition_key][record.transaction_key] = record
            coverage_status = "COMPLETE_BASELINE_WITH_CHANGES"
        else:
            # Change-only linkage cannot establish a baseline. Keep the
            # partition visible for coverage audit, but do not serve its rows.
            states[run.partition_key].clear()
            coverage_status = "UNAVAILABLE_NO_BASELINE"
        latest[run.partition_key] = run
        latest_linked[run.partition_key] = linked_count
        latest_status[run.partition_key] = coverage_status

    partitions: list[dict[str, Any]] = []
    records: list[CurrentRecord] = []
    coverage: dict[str, dict[str, int]] = defaultdict(lambda: {
        "partitionCount": 0, "availablePartitionCount": 0,
        "unavailablePartitionCount": 0, "emptyPartitionCount": 0,
        "discoveredCount": 0, "linkedDocumentCount": 0,
        "activeRecordCount": 0,
    })
    month_districts: dict[str, set[str]] = defaultdict(set)
    month_statuses: dict[str, list[str]] = defaultdict(list)
    partition_states: dict[str, list[CurrentRecord]] = {}
    for partition_key in sorted(latest):
        run = latest[partition_key]
        active = sorted(states[partition_key].values(), key=lambda item: item.transaction_key)
        linked_count = latest_linked[partition_key]
        coverage_status = latest_status[partition_key]
        available = coverage_status in AVAILABLE_COVERAGE_STATUSES
        partition_states[partition_key] = active if available else []
        partitions.append({
            "partitionKey": partition_key,
            "districtCode": run.district_code,
            "dealMonth": run.deal_month,
            "latestRunId": run.run_id,
            "latestCompletedAt": run.completed_at,
            "discoveredCount": run.discovered_count,
            "linkedDocumentCount": linked_count,
            "activeRecordCount": len(active) if available else None,
            "coverageStatus": coverage_status,
        })
        month = coverage[run.deal_month]
        month["partitionCount"] += 1
        month["availablePartitionCount"] += int(available)
        month["unavailablePartitionCount"] += int(not available)
        month["emptyPartitionCount"] += int(coverage_status == "COMPLETE_EMPTY")
        month["discoveredCount"] += run.discovered_count or 0
        month["linkedDocumentCount"] += linked_count
        month["activeRecordCount"] += len(active) if available else 0
        month_districts[run.deal_month].add(run.district_code)
        month_statuses[run.deal_month].append(coverage_status)

    observed_months = sorted(coverage)
    months = inclusive_months(observed_months[0], observed_months[-1])
    complete_months = {
        month for month in months
        if month_districts[month] == EXPECTED_SEOUL_DISTRICTS
        and all(status in AVAILABLE_COVERAGE_STATUSES for status in month_statuses[month])
    }
    for item in partitions:
        if item["dealMonth"] in complete_months:
            records.extend(partition_states[item["partitionKey"]])

    coverage_by_month: list[dict[str, Any]] = []
    caveat_partitions = 0
    for month in months:
        missing = len(EXPECTED_SEOUL_DISTRICTS - month_districts[month])
        caveat_partitions += missing + coverage[month]["unavailablePartitionCount"]
        coverage_by_month.append({
            "month": month,
            "expectedPartitionCount": len(EXPECTED_SEOUL_DISTRICTS),
            "missingPartitionCount": missing,
            "completeMonth": month in complete_months,
            **coverage[month],
        })

    latest_completed_at = max(run.completed_at for run in latest.values())
    queryable_months = sorted(complete_months)
    excluded_months = [month for month in months if month not in complete_months]
    metadata = {
        "projectionBasis": "COMPLETE_BASELINE_THEN_CHRONOLOGICAL_CHANGE_OVERLAY",
        "authoritativeEmptyRule": "LATEST_COMPLETED_DISCOVERED_COUNT_ZERO",
        "expectedDistrictCount": len(EXPECTED_SEOUL_DISTRICTS),
        "observedFrom": months[0],
        "observedThrough": months[-1],
        "availableFrom": queryable_months[0] if queryable_months else None,
        "availableThrough": queryable_months[-1] if queryable_months else None,
        "latestCompletedAt": latest_completed_at,
        "completedPartitionCount": len(partitions),
        "completedEmptyPartitionCount": sum(item["discoveredCount"] == 0 for item in partitions),
        "activeRecordCount": len(records),
        "excludedIncompleteMonthRecordCount": sum(
            coverage[month]["activeRecordCount"] for month in excluded_months
        ),
        "completeMonthCount": len(queryable_months),
        "excludedMonthCount": len(excluded_months),
        "coverageComplete": not excluded_months,
        "missingHistoricalMonths": excluded_months,
        "coverageCaveatPartitionCount": caveat_partitions,
        "unmatchedCancellationCount": unmatched_cancellations,
        "correctionWindow": {
            "from": months[0],
            "through": months[-1],
            "grain": "DISTRICT_MONTH",
            "acceptedRunStatus": "COMPLETED",
        },
        "coverageByMonth": coverage_by_month,
    }
    return Projection(tuple(partitions), tuple(records), metadata)


def apply_migration(conn: sqlite3.Connection, path: Path = DEFAULT_MIGRATION) -> None:
    conn.executescript(path.read_text(encoding="utf-8"))


def _record_content(record: CurrentRecord) -> dict[str, Any]:
    return {
        "transactionKey": record.transaction_key,
        "transactionKeyJson": record.transaction_key_json,
        "partitionKey": record.partition_key,
        "sourceRunId": record.source_run_id,
        "sourceDocumentId": record.source_document_id,
        "documentVersionId": record.document_version_id,
        "apiPayloadJson": record.api_payload_json,
        "apiPayloadSha256": record.api_payload_sha256,
        "duplicateOccurrence": record.duplicate_occurrence,
        "districtCode": record.district_code,
        "districtName": record.district_name,
        "locality": record.locality,
        "buildingUse": record.building_use,
        "buildingAreaText": record.building_area_text,
        "dealAmountText": record.deal_amount_text,
        "dealYear": record.deal_year,
        "dealMonthNumber": record.deal_month_number,
        "dealDay": record.deal_day,
    }


def refresh_molit_current_serving(
    conn: sqlite3.Connection,
    *,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    projection = build_projection(conn)
    previous = {
        (str(row[0]), str(row[1])): str(row[2])
        for row in conn.execute(
            """SELECT table_name,row_key_json,content_sha256
                 FROM serving_row_fingerprints
                WHERE dataset_code=? AND state_code='ACTIVE'
                  AND table_name IN (?,?)""",
            (DATASET_CODE, PARTITION_TABLE, TRANSACTION_TABLE),
        )
    }

    conn.execute(f"DELETE FROM {TRANSACTION_TABLE}")
    conn.execute(f"DELETE FROM {PARTITION_TABLE}")
    conn.executemany(
        f"""INSERT INTO {PARTITION_TABLE}(
              partition_key,district_code,deal_month,latest_run_id,latest_completed_at,
              discovered_count,linked_document_count,active_record_count,coverage_status,
              projection_generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?)""",
        [(
            item["partitionKey"], item["districtCode"], item["dealMonth"],
            item["latestRunId"], item["latestCompletedAt"], item["discoveredCount"],
            item["linkedDocumentCount"], item["activeRecordCount"],
            item["coverageStatus"], generated_at,
        ) for item in projection.partitions],
    )
    conn.executemany(
        f"""INSERT INTO {TRANSACTION_TABLE}(
              transaction_key,transaction_key_json,partition_key,source_run_id,
              source_document_id,document_version_id,api_payload_json,api_payload_sha256,
              duplicate_occurrence,district_code,district_name,locality,building_use,
              building_area_text,deal_amount_text,deal_year,deal_month_number,deal_day,
              projection_generated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        [(
            record.transaction_key, record.transaction_key_json, record.partition_key,
            record.source_run_id, record.source_document_id, record.document_version_id,
            record.api_payload_json, record.api_payload_sha256, record.duplicate_occurrence,
            record.district_code, record.district_name, record.locality,
            record.building_use, record.building_area_text, record.deal_amount_text,
            record.deal_year, record.deal_month_number, record.deal_day, generated_at,
        ) for record in projection.records],
    )

    fingerprints: dict[tuple[str, str], str] = {}
    for item in projection.partitions:
        key = canonical_json({
            "dealMonth": item["dealMonth"],
            "districtCode": item["districtCode"],
        })
        fingerprints[(PARTITION_TABLE, key)] = sha256_json(item)
    for record in projection.records:
        fingerprints[(TRANSACTION_TABLE, record.transaction_key_json)] = sha256_json(_record_content(record))
    for (table, key), content_hash in fingerprints.items():
        conn.execute(
            """INSERT INTO serving_row_fingerprints(
                   dataset_code,table_name,row_key_json,content_sha256,state_code,updated_at
               ) VALUES (?,?,?,?, 'ACTIVE',?)
               ON CONFLICT(dataset_code,table_name,row_key_json) DO UPDATE SET
                 content_sha256=excluded.content_sha256,
                 state_code='ACTIVE',updated_at=excluded.updated_at""",
            (DATASET_CODE, table, key, content_hash, generated_at),
        )
    stale = set(previous) - set(fingerprints)
    for table, key in sorted(stale):
        conn.execute(
            """UPDATE serving_row_fingerprints
                  SET state_code='RETIRED',updated_at=?
                WHERE dataset_code=? AND table_name=? AND row_key_json=?""",
            (generated_at, DATASET_CODE, table, key),
        )

    digest_rows = sorted((table, key, content_hash) for (table, key), content_hash in fingerprints.items())
    content_sha256 = sha256_json(digest_rows)
    source_row_count = sum(item["discoveredCount"] or 0 for item in projection.partitions)
    serving_row_count = len(projection.partitions) + len(projection.records)
    source_status = "READY" if projection.metadata["completeMonthCount"] > 0 else "PARTIAL_COVERAGE"
    conn.execute(
        """INSERT INTO serving_dataset_freshness(
             dataset_code,source_code,source_as_of_date,generated_at,source_status_code,
             source_row_count,serving_row_count,content_sha256,metadata_json
           ) VALUES (?,?,?,?,?,?,?,?,?)
           ON CONFLICT(dataset_code) DO UPDATE SET
             source_code=excluded.source_code,
             source_as_of_date=excluded.source_as_of_date,
             generated_at=excluded.generated_at,
             source_status_code=excluded.source_status_code,
             source_row_count=excluded.source_row_count,
             serving_row_count=excluded.serving_row_count,
             content_sha256=excluded.content_sha256,
             metadata_json=excluded.metadata_json""",
        (
            DATASET_CODE, SOURCE_CODE,
            str(projection.metadata["latestCompletedAt"])[:10], generated_at, source_status,
            source_row_count, serving_row_count, content_sha256,
            canonical_json(projection.metadata),
        ),
    )
    return {
        "status": source_status,
        "datasetCode": DATASET_CODE,
        "completedPartitions": len(projection.partitions),
        "activeRecords": len(projection.records),
        "sourceRows": source_row_count,
        "servingRows": serving_row_count,
        "retiredRows": len(stale),
        "contentSha256": content_sha256,
        "metadata": projection.metadata,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--migration", type=Path, default=DEFAULT_MIGRATION)
    parser.add_argument("--apply", action="store_true", help="write only the derived projection and serving metadata")
    args = parser.parse_args()
    if args.apply:
        conn = sqlite3.connect(args.db)
        try:
            conn.execute("PRAGMA foreign_keys=ON")
            apply_migration(conn, args.migration)
            conn.execute("BEGIN IMMEDIATE")
            report = refresh_molit_current_serving(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        conn = sqlite3.connect(f"file:{args.db.resolve().as_posix()}?mode=ro", uri=True)
        try:
            projection = build_projection(conn)
            report = {
                "status": "DRY_RUN",
                "completedPartitions": len(projection.partitions),
                "activeRecords": len(projection.records),
                "metadata": projection.metadata,
            }
        finally:
            conn.close()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
