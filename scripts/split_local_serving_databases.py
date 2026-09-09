#!/usr/bin/env python3
"""Plan or build immutable local serving DBs from the canonical market archive.

The command is plan-only unless ``--apply`` is supplied.  It never opens the
source database for writing and only replaces the small activation manifest;
snapshot directories and database files are never overwritten.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
from typing import Any, Iterator, Sequence
import uuid


MANIFEST_VERSION = "1.0.0"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DATASET_TABLE = "serving_dataset_freshness"
FINGERPRINT_TABLE = "serving_row_fingerprints"
ALLOWED_SMALL_PARENTS = frozenset({
    "collection_sources",
    "units",
    "regions",
    "asset_classes",
})
MAX_SMALL_PARENT_ROWS = 10_000


class SplitDatabaseError(RuntimeError):
    """Raised when source schema or parity does not satisfy the split contract."""


@dataclass(frozen=True)
class OutputSpec:
    key: str
    filename: str
    dataset_codes: tuple[str, ...]
    seed_tables: tuple[str, ...]
    fingerprinted_tables: tuple[str, ...]


@dataclass(frozen=True)
class Selection:
    where_sql: str
    params: tuple[str, ...]
    label: str


NEWS_SPEC = OutputSpec(
    key="news",
    filename="news.db",
    dataset_codes=("DAILY_ARTICLES",),
    seed_tables=(
        "serving_daily_article_dates",
        "serving_daily_articles",
        "serving_daily_article_topics",
        "serving_daily_article_details",
        DATASET_TABLE,
        FINGERPRINT_TABLE,
    ),
    fingerprinted_tables=(
        "serving_daily_article_dates",
        "serving_daily_articles",
        "serving_daily_article_topics",
        "serving_daily_article_details",
    ),
)

TIMESERIES_SPEC = OutputSpec(
    key="timeseries",
    filename="timeseries.db",
    dataset_codes=(
        "FINANCIAL_MACRO",
        "MOLIT_TRANSACTIONS",
        "SEOUL_BUILDING_PERMITS",
    ),
    seed_tables=(
        "serving_molit_current_transactions",
        "serving_molit_completed_partitions",
        "financial_macro_monthly_serving",
        "macro_series",
        "serving_v2_building_permit_monthly",
        DATASET_TABLE,
        FINGERPRINT_TABLE,
    ),
    fingerprinted_tables=(
        "serving_molit_current_transactions",
        "serving_molit_completed_partitions",
        "financial_macro_monthly_serving",
        "macro_series",
        "serving_v2_building_permit_monthly",
    ),
)

OUTPUT_SPECS = (NEWS_SPEC, TIMESERIES_SPEC)

# No current web runtime query reads the wide permit detail mart.  It remains
# in the canonical archive and must be added deliberately if a detail route is
# introduced, instead of silently increasing the aggregate serving database.
INTENTIONALLY_EXCLUDED = {
    "serving_v2_building_permit_hot_detail": (
        "Current permit runtime reads serving_v2_building_permit_monthly only."
    ),
}


RUNTIME_SMOKE_SQL = {
    "news": {
        "daily-articles": """
            WITH selected_day AS (
              SELECT article_date
              FROM serving_daily_article_dates
              ORDER BY article_date DESC LIMIT 1
            )
            SELECT a.document_id, a.published_at, count(t.term_code)
            FROM selected_day d
            JOIN serving_daily_articles a ON a.article_date=d.article_date
            LEFT JOIN serving_daily_article_topics t ON t.document_id=a.document_id
            GROUP BY a.document_id, a.published_at
            ORDER BY a.published_at DESC, a.document_id
            LIMIT 1
        """,
        "article-detail": """
            SELECT json_extract(payload_json,'$.id')
            FROM serving_daily_article_details
            ORDER BY document_id LIMIT 1
        """,
    },
    "timeseries": {
        "molit-pulse": """
            SELECT p.deal_month, count(t.transaction_key), f.generated_at
            FROM serving_molit_completed_partitions p
            LEFT JOIN serving_molit_current_transactions t
              ON t.partition_key=p.partition_key
            JOIN serving_dataset_freshness f
              ON f.dataset_code='MOLIT_TRANSACTIONS'
            WHERE p.coverage_status<>'UNAVAILABLE_NO_BASELINE'
            GROUP BY p.deal_month, f.generated_at
            ORDER BY p.deal_month DESC LIMIT 1
        """,
        "macro-timeseries": """
            SELECT f.series_code, s.series_name_ko, cs.source_name, u.name_ko,
                   r.canonical_name, ac.name_ko
            FROM financial_macro_monthly_serving f
            JOIN macro_series s USING(series_code)
            JOIN collection_sources cs ON cs.source_id=f.source_id
            JOIN units u ON u.unit_code=f.unit_code
            LEFT JOIN regions r ON r.region_id=f.region_id
            LEFT JOIN asset_classes ac ON ac.asset_class_id=s.asset_class_id
            ORDER BY f.series_code, f.observation_month LIMIT 1
        """,
        "permit-timeseries": """
            SELECT m.event_month, m.event_type, sum(m.permit_count),
                   sum(m.total_floor_area_m2), f.source_as_of_date
            FROM serving_v2_building_permit_monthly m
            JOIN serving_dataset_freshness f
              ON f.dataset_code='SEOUL_BUILDING_PERMITS'
            WHERE m.source_id='src_seoul_building_permit'
              AND m.scope_status='IN_SCOPE'
            GROUP BY m.event_month, m.event_type, f.source_as_of_date
            ORDER BY m.event_month DESC LIMIT 1
        """,
    },
}


def _quote_identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise SplitDatabaseError(f"Unsafe SQLite identifier: {value!r}")
    return f'"{value}"'


def _selection(spec: OutputSpec, table: str) -> Selection:
    if table in {DATASET_TABLE, FINGERPRINT_TABLE}:
        placeholders = ",".join("?" for _ in spec.dataset_codes)
        return Selection(
            where_sql=f" WHERE dataset_code IN ({placeholders})",
            params=tuple(spec.dataset_codes),
            label=f"dataset_code IN ({', '.join(spec.dataset_codes)})",
        )
    return Selection(where_sql="", params=(), label="FULL_TABLE")


def _validate_paths(source: Path, output_dir: Path) -> tuple[Path, Path]:
    source = source.expanduser().resolve(strict=True)
    if not source.is_file():
        raise SplitDatabaseError(f"Source is not a regular file: {source}")
    output_dir = output_dir.expanduser().resolve(strict=False)
    if output_dir == source:
        raise SplitDatabaseError("Output directory cannot be the source database")
    if output_dir.exists() and not output_dir.is_dir():
        raise SplitDatabaseError(f"Output path is not a directory: {output_dir}")
    return source, output_dir


@contextmanager
def _consistent_source(source: Path) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=30)
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        # Pin a single read snapshot before any destination is created.
        connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _table_ddl(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_schema WHERE type='table' AND name=?",
        (table,),
    ).fetchone()
    if row is None or not isinstance(row[0], str):
        raise SplitDatabaseError(f"Required table is missing: {table}")
    ddl = row[0].strip()
    if not re.match(r"^CREATE\s+TABLE\b", ddl, flags=re.IGNORECASE):
        raise SplitDatabaseError(f"Unsupported table DDL for {table}")
    return ddl


def _index_ddls(connection: sqlite3.Connection, table: str) -> list[tuple[str, str]]:
    rows = connection.execute(
        """SELECT name,sql FROM sqlite_schema
           WHERE type='index' AND tbl_name=? AND sql IS NOT NULL
           ORDER BY name""",
        (table,),
    ).fetchall()
    result: list[tuple[str, str]] = []
    for name, ddl in rows:
        _quote_identifier(str(name))
        if not isinstance(ddl, str) or not re.match(
            r"^CREATE\s+(?:UNIQUE\s+)?INDEX\b", ddl.strip(), flags=re.IGNORECASE
        ):
            raise SplitDatabaseError(f"Unsupported index DDL for {table}: {name}")
        result.append((str(name), ddl.strip()))
    return result


def _trigger_names(connection: sqlite3.Connection, table: str) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_schema WHERE type='trigger' AND tbl_name=? ORDER BY name",
            (table,),
        )
    ]


def _table_xinfo(connection: sqlite3.Connection, table: str) -> list[tuple[Any, ...]]:
    rows = connection.execute(f"PRAGMA table_xinfo({_quote_identifier(table)})").fetchall()
    if not rows:
        raise SplitDatabaseError(f"Cannot inspect columns for {table}")
    hidden = [str(row[1]) for row in rows if int(row[6]) != 0]
    if hidden:
        raise SplitDatabaseError(
            f"Generated or hidden columns require an explicit copy policy in {table}: {hidden}"
        )
    return rows


def _columns(connection: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in _table_xinfo(connection, table)]


def _primary_key_columns(connection: sqlite3.Connection, table: str) -> list[str]:
    keyed = [(int(row[5]), str(row[1])) for row in _table_xinfo(connection, table) if int(row[5])]
    return [name for _, name in sorted(keyed)]


def _foreign_key_parents(connection: sqlite3.Connection, table: str) -> list[str]:
    parents = {
        str(row[2])
        for row in connection.execute(
            f"PRAGMA foreign_key_list({_quote_identifier(table)})"
        )
    }
    return sorted(parents)


def _resolve_table_closure(connection: sqlite3.Connection, spec: OutputSpec) -> tuple[str, ...]:
    selected = set(spec.seed_tables)
    pending = list(spec.seed_tables)
    while pending:
        table = pending.pop()
        if not _table_exists(connection, table):
            raise SplitDatabaseError(f"{spec.key} requires missing table {table}")
        for parent in _foreign_key_parents(connection, table):
            if parent in selected:
                continue
            if parent not in ALLOWED_SMALL_PARENTS:
                raise SplitDatabaseError(
                    f"{spec.key}.{table} has an unapproved FK parent {parent}; "
                    "update the explicit split contract before applying"
                )
            parent_count = int(
                connection.execute(
                    f"SELECT count(*) FROM {_quote_identifier(parent)}"
                ).fetchone()[0]
            )
            if parent_count > MAX_SMALL_PARENT_ROWS:
                raise SplitDatabaseError(
                    f"FK parent {parent} has {parent_count} rows; refusing implicit bulk inclusion"
                )
            selected.add(parent)
            pending.append(parent)
    return tuple(sorted(selected))


def _selected_count(
    connection: sqlite3.Connection,
    table: str,
    selection: Selection,
) -> int:
    sql = f"SELECT count(*) FROM {_quote_identifier(table)}{selection.where_sql}"
    return int(connection.execute(sql, selection.params).fetchone()[0])


def _run_runtime_smokes(connection: sqlite3.Connection, spec: OutputSpec) -> list[str]:
    completed: list[str] = []
    for name, sql in RUNTIME_SMOKE_SQL[spec.key].items():
        try:
            connection.execute(sql).fetchone()
        except sqlite3.Error as error:
            raise SplitDatabaseError(
                f"{spec.key} runtime smoke {name!r} failed: {error}"
            ) from error
        completed.append(name)
    return completed


def _validate_metadata_contract(connection: sqlite3.Connection, spec: OutputSpec) -> dict[str, Any]:
    placeholders = ",".join("?" for _ in spec.dataset_codes)
    freshness_codes = {
        str(row[0])
        for row in connection.execute(
            f"SELECT dataset_code FROM {DATASET_TABLE} WHERE dataset_code IN ({placeholders})",
            spec.dataset_codes,
        )
    }
    if freshness_codes != set(spec.dataset_codes):
        missing = sorted(set(spec.dataset_codes) - freshness_codes)
        raise SplitDatabaseError(f"{spec.key} freshness rows are missing: {missing}")

    unexpected_fingerprint_tables = sorted({
        str(row[0])
        for row in connection.execute(
            f"""SELECT DISTINCT table_name FROM {FINGERPRINT_TABLE}
                WHERE dataset_code IN ({placeholders})""",
            spec.dataset_codes,
        )
        if str(row[0]) not in set(spec.fingerprinted_tables)
    })
    if unexpected_fingerprint_tables:
        raise SplitDatabaseError(
            f"{spec.key} has unassigned fingerprint tables: {unexpected_fingerprint_tables}"
        )

    fingerprint_parity: dict[str, dict[str, int]] = {}
    for table in spec.fingerprinted_tables:
        serving_rows = _selected_count(connection, table, Selection("", (), "FULL_TABLE"))
        active_fingerprints = int(
            connection.execute(
                f"""SELECT count(*) FROM {FINGERPRINT_TABLE}
                    WHERE dataset_code IN ({placeholders})
                      AND table_name=? AND state_code='ACTIVE'""",
                (*spec.dataset_codes, table),
            ).fetchone()[0]
        )
        if serving_rows != active_fingerprints:
            raise SplitDatabaseError(
                f"{spec.key}.{table} has {serving_rows} rows but "
                f"{active_fingerprints} active fingerprints"
            )
        fingerprint_parity[table] = {
            "servingRows": serving_rows,
            "activeFingerprints": active_fingerprints,
        }
    return {
        "freshnessDatasetCodes": sorted(freshness_codes),
        "activeFingerprintParity": fingerprint_parity,
    }


def _source_metadata(connection: sqlite3.Connection, source: Path) -> dict[str, Any]:
    stat = source.stat()
    return {
        "path": str(source),
        "bytes": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "sqliteVersion": sqlite3.sqlite_version,
        "schemaVersion": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
        "pageCount": int(connection.execute("PRAGMA page_count").fetchone()[0]),
        "journalMode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
        "openedMode": "ro",
        "consistentReadTransaction": True,
    }


def _plan_from_connection(
    connection: sqlite3.Connection,
    source: Path,
    output_dir: Path,
) -> dict[str, Any]:
    outputs: dict[str, Any] = {}
    assigned_codes: set[str] = set()
    for spec in OUTPUT_SPECS:
        overlap = assigned_codes.intersection(spec.dataset_codes)
        if overlap:
            raise SplitDatabaseError(f"Dataset assigned to multiple outputs: {sorted(overlap)}")
        assigned_codes.update(spec.dataset_codes)
        tables = _resolve_table_closure(connection, spec)
        metadata = _validate_metadata_contract(connection, spec)
        smokes = _run_runtime_smokes(connection, spec)
        table_plans = []
        for table in tables:
            selection = _selection(spec, table)
            table_plans.append({
                "name": table,
                "selection": selection.label,
                "rowCount": _selected_count(connection, table, selection),
                "foreignKeyParents": _foreign_key_parents(connection, table),
                "explicitIndexes": [name for name, _ in _index_ddls(connection, table)],
                "omittedReadOnlyTriggers": _trigger_names(connection, table),
            })
        outputs[spec.key] = {
            "filename": spec.filename,
            "datasetCodes": list(spec.dataset_codes),
            "tables": table_plans,
            "metadataContract": metadata,
            "runtimeSmokes": smokes,
        }
    return {
        "manifestVersion": MANIFEST_VERSION,
        "mode": "PLAN",
        "willWrite": False,
        "source": _source_metadata(connection, source),
        "outputDirectory": str(output_dir),
        "activationManifest": str(output_dir / "manifest.json"),
        "outputs": outputs,
        "datasetAssignments": {
            code: spec.filename
            for spec in OUTPUT_SPECS
            for code in spec.dataset_codes
        },
        "intentionallyExcluded": [
            {"table": table, "reason": reason}
            for table, reason in sorted(INTENTIONALLY_EXCLUDED.items())
            if _table_exists(connection, table)
        ],
        "limitations": [
            "The canonical archive is retained and is not represented as fully split.",
            "Only serving tables required by current news and timeseries runtime queries are assigned.",
        ],
    }


def inspect_split_plan(source: Path, output_dir: Path) -> dict[str, Any]:
    """Inspect and validate a split without creating any path or file."""
    source, output_dir = _validate_paths(source, output_dir)
    with _consistent_source(source) as connection:
        return _plan_from_connection(connection, source, output_dir)


def _canonical_cell(value: Any) -> list[str]:
    if value is None:
        return ["null", ""]
    if isinstance(value, bytes):
        return ["blob", value.hex()]
    if isinstance(value, memoryview):
        return ["blob", bytes(value).hex()]
    if isinstance(value, int):
        return ["integer", str(value)]
    if isinstance(value, float):
        return ["real", value.hex()]
    if isinstance(value, str):
        return ["text", value]
    raise SplitDatabaseError(f"Unsupported SQLite value type: {type(value).__name__}")


def _hash_header(hasher: Any, columns: Sequence[str]) -> None:
    encoded = json.dumps(list(columns), ensure_ascii=False, separators=(",", ":"))
    hasher.update(encoded.encode("utf-8") + b"\n")


def _hash_row(hasher: Any, row: Sequence[Any]) -> None:
    encoded = json.dumps(
        [_canonical_cell(value) for value in row],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    hasher.update(encoded.encode("utf-8") + b"\n")


def _ordered_select_sql(
    connection: sqlite3.Connection,
    table: str,
    selection: Selection,
) -> tuple[str, list[str]]:
    columns = _columns(connection, table)
    primary_key = _primary_key_columns(connection, table)
    order_columns = primary_key or columns
    selected = ",".join(_quote_identifier(column) for column in columns)
    ordered = ",".join(_quote_identifier(column) for column in order_columns)
    return (
        f"SELECT {selected} FROM {_quote_identifier(table)}"
        f"{selection.where_sql} ORDER BY {ordered}",
        columns,
    )


def _copy_table(
    source: sqlite3.Connection,
    destination: sqlite3.Connection,
    table: str,
    selection: Selection,
) -> tuple[int, str]:
    select_sql, columns = _ordered_select_sql(source, table, selection)
    placeholders = ",".join("?" for _ in columns)
    insert_sql = (
        f"INSERT INTO {_quote_identifier(table)} "
        f"({','.join(_quote_identifier(column) for column in columns)}) "
        f"VALUES ({placeholders})"
    )
    cursor = source.execute(select_sql, selection.params)
    hasher = hashlib.sha256()
    _hash_header(hasher, columns)
    count = 0
    while True:
        rows = cursor.fetchmany(1_000)
        if not rows:
            break
        destination.executemany(insert_sql, rows)
        for row in rows:
            _hash_row(hasher, row)
        count += len(rows)
    return count, hasher.hexdigest()


def _digest_table(
    connection: sqlite3.Connection,
    table: str,
    selection: Selection,
) -> tuple[int, str]:
    select_sql, columns = _ordered_select_sql(connection, table, selection)
    hasher = hashlib.sha256()
    _hash_header(hasher, columns)
    count = 0
    cursor = connection.execute(select_sql, selection.params)
    while True:
        rows = cursor.fetchmany(1_000)
        if not rows:
            break
        for row in rows:
            _hash_row(hasher, row)
        count += len(rows)
    return count, hasher.hexdigest()


def _schema_sha256(connection: sqlite3.Connection, tables: Sequence[str]) -> str:
    hasher = hashlib.sha256()
    for table in sorted(tables):
        hasher.update(table.encode("utf-8") + b"\n")
        hasher.update(_table_ddl(connection, table).encode("utf-8") + b"\n")
        for index_name, ddl in _index_ddls(connection, table):
            hasher.update(index_name.encode("utf-8") + b"\n")
            hasher.update(ddl.encode("utf-8") + b"\n")
    return hasher.hexdigest()


def _create_exclusive_database(path: Path) -> sqlite3.Connection:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite existing database: {path}")
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    return sqlite3.connect(path)


def _build_one_database(
    source: sqlite3.Connection,
    destination_path: Path,
    spec: OutputSpec,
    tables: Sequence[str],
) -> dict[str, Any]:
    destination = _create_exclusive_database(destination_path)
    source_schema_hash = _schema_sha256(source, tables)
    table_reports: dict[str, Any] = {}
    try:
        destination.execute("PRAGMA foreign_keys=OFF")
        destination.execute("BEGIN IMMEDIATE")
        for table in sorted(tables):
            destination.execute(_table_ddl(source, table))
        for table in sorted(tables):
            selection = _selection(spec, table)
            row_count, source_hash = _copy_table(source, destination, table, selection)
            table_reports[table] = {
                "selection": selection.label,
                "sourceRowCount": row_count,
                "sourceContentSha256": source_hash,
            }
        for table in sorted(tables):
            for _, ddl in _index_ddls(source, table):
                destination.execute(ddl)
        destination.commit()
        destination.execute("VACUUM")
        destination.execute("PRAGMA foreign_keys=ON")

        output_schema_hash = _schema_sha256(destination, tables)
        if output_schema_hash != source_schema_hash:
            raise SplitDatabaseError(f"Schema hash mismatch for {spec.filename}")

        for table in sorted(tables):
            output_count, output_hash = _digest_table(
                destination, table, Selection("", (), "FULL_TABLE")
            )
            table_report = table_reports[table]
            table_report.update({
                "outputRowCount": output_count,
                "outputContentSha256": output_hash,
                "parity": (
                    output_count == table_report["sourceRowCount"]
                    and output_hash == table_report["sourceContentSha256"]
                ),
            })
            if not table_report["parity"]:
                raise SplitDatabaseError(f"Row parity mismatch for {spec.filename}.{table}")

        foreign_key_rows = destination.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_rows:
            raise SplitDatabaseError(
                f"Foreign-key violations in {spec.filename}: {len(foreign_key_rows)}"
            )
        integrity = str(destination.execute("PRAGMA integrity_check").fetchone()[0])
        if integrity != "ok":
            raise SplitDatabaseError(f"Integrity check failed for {spec.filename}: {integrity}")
        smokes = _run_runtime_smokes(destination, spec)
        destination.execute("PRAGMA query_only=ON")
    finally:
        if destination.in_transaction:
            destination.rollback()
        destination.close()

    combined_hasher = hashlib.sha256()
    for table, report in sorted(table_reports.items()):
        combined_hasher.update(table.encode("utf-8") + b"\0")
        combined_hasher.update(report["outputContentSha256"].encode("ascii") + b"\n")
    return {
        "filename": spec.filename,
        "bytes": destination_path.stat().st_size,
        "datasetCodes": list(spec.dataset_codes),
        "schemaSha256": source_schema_hash,
        "contentSha256": combined_hasher.hexdigest(),
        "tables": table_reports,
        "foreignKeyViolations": 0,
        "integrity": "ok",
        "runtimeSmokes": smokes,
        "allTableParity": all(report["parity"] for report in table_reports.values()),
    }


def _write_json_exclusive(path: Path, payload: dict[str, Any]) -> None:
    encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())


def _replace_activation_manifest(output_dir: Path, payload: dict[str, Any]) -> None:
    temporary = output_dir / f".manifest-{uuid.uuid4().hex}.tmp"
    try:
        _write_json_exclusive(temporary, payload)
        os.replace(temporary, output_dir / "manifest.json")
    finally:
        if temporary.exists():
            temporary.unlink()


def _snapshot_timestamp(now: datetime) -> str:
    if now.tzinfo is None:
        raise SplitDatabaseError("Snapshot time must be timezone-aware")
    return now.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def build_split_snapshot(
    source: Path,
    output_dir: Path,
    *,
    now: datetime | None = None,
    nonce: str | None = None,
) -> dict[str, Any]:
    """Build, verify and activate one immutable split snapshot."""
    source, output_dir = _validate_paths(source, output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    nonce = nonce or uuid.uuid4().hex[:8]
    if not re.fullmatch(r"[a-zA-Z0-9_-]{4,32}", nonce):
        raise SplitDatabaseError("Snapshot nonce must be 4-32 safe characters")
    snapshot_id = f"{_snapshot_timestamp(now)}-{nonce}"
    final_directory = output_dir / snapshot_id
    if final_directory.exists():
        raise FileExistsError(f"Refusing to overwrite existing snapshot: {final_directory}")

    staging = Path(tempfile.mkdtemp(prefix=".split-staging-", dir=output_dir))
    promoted = False
    try:
        with _consistent_source(source) as connection:
            plan = _plan_from_connection(connection, source, output_dir)
            outputs: dict[str, Any] = {}
            for spec in OUTPUT_SPECS:
                tables = _resolve_table_closure(connection, spec)
                outputs[spec.key] = _build_one_database(
                    connection,
                    staging / spec.filename,
                    spec,
                    tables,
                )

            all_parity = all(output["allTableParity"] for output in outputs.values())
            if not all_parity:
                raise SplitDatabaseError("At least one output failed source row parity")
            content_hasher = hashlib.sha256()
            for key, output in sorted(outputs.items()):
                content_hasher.update(key.encode("utf-8") + b"\0")
                content_hasher.update(output["contentSha256"].encode("ascii") + b"\n")

            created_at = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
            snapshot_manifest = {
                "manifestVersion": MANIFEST_VERSION,
                "complete": True,
                "snapshotId": snapshot_id,
                "createdAt": created_at,
                "source": plan["source"],
                "outputs": outputs,
                "datasetAssignments": plan["datasetAssignments"],
                "intentionallyExcluded": plan["intentionallyExcluded"],
                "limitations": plan["limitations"],
                "crossOutput": {
                    "datasetAssignmentsDisjoint": True,
                    "sourceRowParity": all_parity,
                    "combinedContentSha256": content_hasher.hexdigest(),
                    "sharedMetadataTables": [DATASET_TABLE, FINGERPRINT_TABLE],
                    "sharedMetadataRowsDuplicated": False,
                },
            }
            _write_json_exclusive(staging / "snapshot-manifest.json", snapshot_manifest)

        # A unique immutable directory is published only after both databases
        # and the snapshot-local manifest are closed and verified.
        staging.rename(final_directory)
        promoted = True
        activation_manifest = {
            **snapshot_manifest,
            "currentSnapshot": snapshot_id,
            "snapshotDirectory": str(final_directory),
            "snapshotManifest": str(final_directory / "snapshot-manifest.json"),
        }
        _replace_activation_manifest(output_dir, activation_manifest)
        return activation_manifest
    except Exception:
        if not promoted and staging.exists():
            shutil.rmtree(staging)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create and atomically activate a verified snapshot. Omit for read-only planning.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        result = (
            build_split_snapshot(args.source, args.output_dir)
            if args.apply
            else inspect_split_plan(args.source, args.output_dir)
        )
    except (OSError, sqlite3.Error, SplitDatabaseError) as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
