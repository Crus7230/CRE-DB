#!/usr/bin/env python3
"""Migrate, publish, and verify an immutable compact dashboard package.

The script refuses implicit writes: ``migrate`` and ``publish`` require
``--apply``.  A publish holds one PostgreSQL advisory lock and performs every
COPY, parity check, and optional active-version switch in one transaction.
Existing active data therefore remains visible after any failed refresh.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
from decimal import Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from time import perf_counter
from typing import Any, Iterable, Iterator, Mapping, Sequence
from urllib.parse import unquote, urlsplit

try:
    from scripts.export_compact_dashboard_supabase import content_identity_row
except ModuleNotFoundError:  # Direct ``python scripts/...`` execution.
    from export_compact_dashboard_supabase import content_identity_row

try:
    import psycopg
    from psycopg.conninfo import make_conninfo
    from psycopg.types.json import Jsonb
except ImportError:  # Unit tests for package validation do not need psycopg.
    psycopg = None
    make_conninfo = None
    Jsonb = None


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATION = ROOT / "db" / "v2" / "migrations" / "4.0.0_supabase_compact_dashboard.sql"
DEFAULT_AUTH_DB = ROOT / "data" / "local-access.db"
EXPECTED_SCHEMA_VERSION = "1.1.0"
EXPECTED_TABLES = {
    "article_dates",
    "articles",
    "article_topics",
    "article_details",
    "article_search_documents",
    "macro_series",
    "macro_monthly",
    "permit_monthly",
    "market_pulse",
}
DATASET_VERSION_RE = re.compile(r"^cre-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
ADVISORY_LOCK_NAME = "cre-dashboard-compact-publish-v1"


class CompactPublishError(RuntimeError):
    """Raised when target guards or parity checks fail."""


TABLE_SPECS: dict[str, tuple[str, tuple[str, ...], frozenset[str]]] = {
    "article_dates": (
        "cre_news.article_dates",
        (
            "article_date", "article_count", "categorized_count", "summarized_count",
            "last_collected_at", "generated_at",
        ),
        frozenset(),
    ),
    "articles": (
        "cre_news.articles",
        (
            "document_id", "document_version_id", "article_date", "title",
            "publisher_name", "published_at", "collected_at", "summary_text",
            "summary_mode", "summary_generated_at", "canonical_url",
            "document_purpose_code", "document_purpose_label", "evidence_grade_code",
            "evidence_grade_label", "topic_count", "projection_generated_at",
            "evidence_text", "search_text",
        ),
        frozenset(),
    ),
    "article_topics": (
        "cre_news.article_topics",
        (
            "document_id", "document_version_id", "term_code", "term_label",
            "status_code", "provenance_code", "is_primary", "confidence",
            "sort_order", "topic_rank",
        ),
        frozenset(),
    ),
    "article_details": (
        "cre_news.article_details",
        ("document_id", "document_version_id", "payload", "projection_generated_at"),
        frozenset({"payload"}),
    ),
    "article_search_documents": (
        "cre_news.article_search_documents",
        ("document_id", "terms"),
        frozenset(),
    ),
    "macro_series": (
        "cre_timeseries.macro_series",
        (
            "macro_series_id", "series_code", "series_name_ko", "metric_code",
            "source_id", "source_name", "external_series_key", "frequency_code",
            "unit_code", "region_id", "asset_class_id", "adjustment_code",
            "aggregation_code", "definition_text", "valid_from", "valid_to",
            "is_active", "metadata",
        ),
        frozenset({"metadata"}),
    ),
    "macro_monthly": (
        "cre_timeseries.macro_monthly",
        (
            "series_code", "source_id", "region_id", "observation_month",
            "numeric_value", "observation_count", "aggregation_code", "unit_code",
            "source_vintage_at", "published_at",
        ),
        frozenset(),
    ),
    "permit_monthly": (
        "cre_timeseries.permit_monthly",
        (
            "source_id", "event_month", "event_type", "district_name", "asset_type",
            "construction_action", "permit_count", "total_floor_area_m2",
            "missing_area_count", "invalid_area_count",
        ),
        frozenset(),
    ),
    "market_pulse": (
        "cre_timeseries.market_pulse",
        ("as_of_period", "payload", "source_content_sha256", "generated_at"),
        frozenset({"payload"}),
    ),
}
LOAD_ORDER = (
    "article_dates",
    "articles",
    "article_topics",
    "article_details",
    "article_search_documents",
    "macro_series",
    "macro_monthly",
    "permit_monthly",
    "market_pulse",
)
DELTA_CHANGED_TABLES = ("market_pulse",)
DELTA_SERVER_CLONE_TABLES = tuple(
    table for table in LOAD_ORDER if table not in DELTA_CHANGED_TABLES
)
DELTA_MANIFEST_KEYS = {
    "baseDatasetVersion",
    "baseSourceManifestSha256",
    "changedTables",
    "requiredServerCloneTables",
}
MONTH_DATE_COLUMNS = {
    ("macro_series", "valid_from"),
    ("macro_series", "valid_to"),
    ("macro_monthly", "observation_month"),
    ("permit_monthly", "event_month"),
}
TIMESTAMP_COLUMNS = {
    ("article_dates", "last_collected_at"),
    ("article_dates", "generated_at"),
    ("articles", "published_at"),
    ("articles", "collected_at"),
    ("articles", "summary_generated_at"),
    ("articles", "projection_generated_at"),
    ("article_details", "projection_generated_at"),
    ("macro_monthly", "source_vintage_at"),
    ("macro_monthly", "published_at"),
    ("market_pulse", "generated_at"),
}
DECIMAL_COLUMNS = {
    ("macro_monthly", "numeric_value"),
    ("permit_monthly", "total_floor_area_m2"),
}
FLOAT_COLUMNS = {("article_topics", "confidence")}
TABLE_ORDER_BY = {
    "article_dates": "article_date",
    "articles": "document_id",
    "article_topics": "document_id,term_code",
    "article_details": "document_id",
    "article_search_documents": "document_id",
    "macro_series": "macro_series_id",
    "macro_monthly": "series_code,observation_month",
    "permit_monthly": "event_month,event_type,district_name,asset_type,construction_action",
    "market_pulse": "dataset_version",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
        default=_json_default,
    )


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral() else float(value)
    raise TypeError(f"Unsupported JSON type: {type(value).__name__}")


def _assignment_values(text: str, key: str) -> list[str]:
    values: list[str] = []
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
    for line in text.splitlines():
        match = pattern.match(line)
        if match:
            values.append(match.group(1).strip().strip('"').strip("'"))
    return values


def target_connection_info(
    env_path: Path,
    *,
    expected_ref: str,
    pooler_host: str,
) -> tuple[str, dict[str, str]]:
    if make_conninfo is None:
        raise CompactPublishError("psycopg[binary] is required for remote operations")
    if not re.fullmatch(r"[a-z0-9]{20}", expected_ref):
        raise CompactPublishError("Expected Supabase project ref is invalid")
    if not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", pooler_host):
        raise CompactPublishError("Pooler host is not an official Supabase shared pooler")
    text = env_path.expanduser().resolve(strict=True).read_text(encoding="utf-8-sig")
    declared_refs = set(_assignment_values(text, "SUPABASE_PROJECT_REF"))
    url_refs: set[str] = set()
    for value in _assignment_values(text, "SUPABASE_URL"):
        match = re.search(r"https://([a-z0-9]{20})\.supabase\.co", value)
        if match:
            url_refs.add(match.group(1))
    if declared_refs != {expected_ref} or url_refs != {expected_ref}:
        raise CompactPublishError("Personal env project identity does not match --target-ref")
    uri_matches = re.findall(r"postgres(?:ql)?://\S+", text)
    matching = [uri for uri in uri_matches if f"db.{expected_ref}.supabase.co" in uri]
    if len(matching) != 1:
        raise CompactPublishError("Expected exactly one PostgreSQL URI for the target ref")
    parsed = urlsplit(matching[0])
    if not parsed.password:
        raise CompactPublishError("Target PostgreSQL URI has no password")
    dsn = make_conninfo(
        host=pooler_host,
        port=5432,
        dbname=(parsed.path or "/postgres").lstrip("/"),
        user=f"postgres.{expected_ref}",
        password=unquote(parsed.password),
        sslmode="require",
        connect_timeout=15,
        application_name="cre-dashboard-compact-publisher",
    )
    return dsn, {"targetRef": expected_ref, "poolerHost": pooler_host, "database": "postgres"}


def read_manifest(package: Path) -> dict[str, Any]:
    package = package.expanduser().resolve(strict=True)
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompactPublishError(f"Cannot read package manifest: {manifest_path}") from error
    if manifest.get("schemaVersion") != EXPECTED_SCHEMA_VERSION:
        raise CompactPublishError("Package schema version is unsupported")
    if not DATASET_VERSION_RE.fullmatch(str(manifest.get("datasetVersion", ""))):
        raise CompactPublishError("Package dataset version is invalid")
    tables = manifest.get("tables")
    if not isinstance(tables, dict) or set(tables) != EXPECTED_TABLES:
        raise CompactPublishError("Package table set is incomplete or unexpected")
    if not SHA256_RE.fullmatch(str(manifest.get("sourceManifestSha256", ""))):
        raise CompactPublishError("Package source manifest hash is invalid")
    stable_hashes = manifest.get("stableTableHashes")
    if stable_hashes is not None and (
        not isinstance(stable_hashes, dict)
        or set(stable_hashes) != EXPECTED_TABLES
        or any(not SHA256_RE.fullmatch(str(value)) for value in stable_hashes.values())
    ):
        raise CompactPublishError("Package stable table hashes are invalid")
    _validated_delta_manifest(manifest)
    return manifest


def _validated_delta_manifest(manifest: Mapping[str, Any]) -> dict[str, Any] | None:
    """Validate the narrow, immutable one-table delta publication contract."""

    delta = manifest.get("delta")
    if delta is None:
        return None
    if not isinstance(delta, dict) or set(delta) != DELTA_MANIFEST_KEYS:
        raise CompactPublishError("Package delta contract is incomplete or unexpected")
    base_version = str(delta.get("baseDatasetVersion", ""))
    if not DATASET_VERSION_RE.fullmatch(base_version):
        raise CompactPublishError("Package delta base dataset version is invalid")
    if base_version == str(manifest.get("datasetVersion", "")):
        raise CompactPublishError("Package delta base and target versions must differ")
    base_hash = str(delta.get("baseSourceManifestSha256", ""))
    if not SHA256_RE.fullmatch(base_hash):
        raise CompactPublishError("Package delta base manifest hash is invalid")
    if delta.get("changedTables") != list(DELTA_CHANGED_TABLES):
        raise CompactPublishError("Package delta changed-table set is unsupported")
    if delta.get("requiredServerCloneTables") != list(DELTA_SERVER_CLONE_TABLES):
        raise CompactPublishError("Package delta server-clone table set is invalid")
    return {
        "baseDatasetVersion": base_version,
        "baseSourceManifestSha256": base_hash,
        "changedTables": list(DELTA_CHANGED_TABLES),
        "requiredServerCloneTables": list(DELTA_SERVER_CLONE_TABLES),
    }


def iter_package_rows(package: Path, table: str) -> Iterator[dict[str, Any]]:
    manifest = read_manifest(package)
    report = manifest["tables"][table]
    filename = report.get("file")
    if not isinstance(filename, str) or Path(filename).name != filename:
        raise CompactPublishError(f"Unsafe package filename for {table}")
    path = package / filename
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise CompactPublishError(f"Invalid JSON in {filename}:{line_number}") from error
            if not isinstance(value, dict):
                raise CompactPublishError(f"Non-object row in {filename}:{line_number}")
            yield value


def verify_package(package: Path) -> dict[str, Any]:
    package = package.expanduser().resolve(strict=True)
    manifest = read_manifest(package)
    verified: dict[str, Any] = {}
    for table in LOAD_ORDER:
        digest = hashlib.sha256()
        stable_digest = hashlib.sha256()
        row_count = 0
        uncompressed_bytes = 0
        for row in iter_package_rows(package, table):
            encoded = (canonical_json(row) + "\n").encode("utf-8")
            digest.update(encoded)
            stable_digest.update(
                (canonical_json(content_identity_row(table, row)) + "\n").encode("utf-8")
            )
            uncompressed_bytes += len(encoded)
            row_count += 1
        expected = manifest["tables"][table]
        if row_count != int(expected["rowCount"]):
            raise CompactPublishError(f"Package row-count mismatch for {table}")
        if digest.hexdigest() != expected["contentSha256"]:
            raise CompactPublishError(f"Package content-hash mismatch for {table}")
        if uncompressed_bytes != int(expected["uncompressedBytes"]):
            raise CompactPublishError(f"Package byte-count mismatch for {table}")
        stable_expected = expected.get("stableContentSha256")
        if stable_expected is not None and stable_digest.hexdigest() != stable_expected:
            raise CompactPublishError(f"Package stable-content hash mismatch for {table}")
        manifest_stable = manifest.get("stableTableHashes")
        if manifest_stable is not None:
            if not isinstance(manifest_stable, dict) or set(manifest_stable) != EXPECTED_TABLES:
                raise CompactPublishError("Package stable table-hash set is incomplete")
            if stable_digest.hexdigest() != manifest_stable.get(table):
                raise CompactPublishError(f"Package stable table-hash mismatch for {table}")
        verified[table] = {
            "rowCount": row_count,
            "contentSha256": digest.hexdigest(),
            "stableContentSha256": stable_digest.hexdigest(),
            "uncompressedBytes": uncompressed_bytes,
        }
    return {"verified": True, "tables": verified}


def read_auth_subjects(auth_db: Path) -> list[dict[str, Any]]:
    resolved = auth_db.expanduser().resolve(strict=True)
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        rows = [
            dict(row)
            for row in connection.execute(
                """SELECT access_subject_id,email_normalized,is_enabled,approved_at,
                          approved_by,revoked_at,revoked_by,access_expires_at
                   FROM dashboard_access_allowlist ORDER BY access_subject_id"""
            )
        ]
    finally:
        connection.close()
    if len(rows) != 3 or any(not row["access_subject_id"] or not row["email_normalized"] for row in rows):
        raise CompactPublishError("Expected exactly three established dashboard auth subjects")
    return rows


def _connect(dsn: str, *, autocommit: bool = False):
    if psycopg is None:
        raise CompactPublishError("psycopg[binary] is required for remote operations")
    return psycopg.connect(dsn, autocommit=autocommit)


def inspect_target(dsn: str, identity: Mapping[str, str]) -> dict[str, Any]:
    with _connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='15s'")
            row = connection.execute(
                """SELECT current_database(),current_user,current_setting('server_version'),
                          pg_database_size(current_database()),
                          has_database_privilege(current_user,current_database(),'CREATE'),
                          has_schema_privilege(current_user,'public','CREATE')"""
            ).fetchone()
            schemas = connection.execute(
                """SELECT nspname FROM pg_namespace
                   WHERE nspname IN ('cre_system','cre_news','cre_timeseries')
                   ORDER BY nspname"""
            ).fetchall()
            version_count = 0
            active_version = None
            if any(item[0] == "cre_system" for item in schemas):
                version_count = int(
                    connection.execute("SELECT count(*) FROM cre_system.dataset_versions").fetchone()[0]
                )
                active_row = connection.execute(
                    "SELECT dataset_version FROM cre_system.active_manifest WHERE slot='dashboard'"
                ).fetchone()
                active_version = None if active_row is None else active_row[0]
    return {
        **identity,
        "connected": True,
        "currentDatabase": row[0],
        "currentUser": row[1],
        "serverVersion": row[2],
        "databaseBytes": int(row[3]),
        "canCreateDatabaseObjects": bool(row[4]),
        "canCreateInPublic": bool(row[5]),
        "isolatedSchemas": [item[0] for item in schemas],
        "datasetVersionCount": version_count,
        "activeDatasetVersion": active_version,
    }


def inspect_active_publication(dsn: str) -> dict[str, Any]:
    """Read the active immutable manifest and bounded capacity metadata."""

    with _connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='15s'")
            schema = connection.execute(
                """SELECT schema_value FROM cre_system.schema_meta
                   WHERE schema_key='compact_dashboard_schema_version'"""
            ).fetchone()
            if schema is None or schema[0] != EXPECTED_SCHEMA_VERSION:
                raise CompactPublishError("Apply the compact migration before publishing")
            active = connection.execute(
                """SELECT version.dataset_version,version.status_code,
                          version.source_manifest_sha256,version.row_counts,
                          version.table_hashes,version.source_as_of_at
                   FROM cre_system.active_manifest manifest
                   JOIN cre_system.dataset_versions version USING(dataset_version)
                   WHERE manifest.slot='dashboard'"""
            ).fetchone()
            database_bytes = int(
                connection.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            )
            versions = [
                {
                    "datasetVersion": row[0],
                    "status": row[1],
                    "previouslyActivated": row[2] is not None,
                    "activeReferenced": bool(row[3]),
                }
                for row in connection.execute(
                    """SELECT version.dataset_version,version.status_code,
                              version.activated_at,
                              EXISTS(
                                SELECT 1 FROM cre_system.active_manifest reference
                                WHERE reference.dataset_version=version.dataset_version
                              )
                       FROM cre_system.dataset_versions version
                       ORDER BY version.created_at,version.dataset_version"""
                )
            ]
    return {
        "schemaVersion": schema[0],
        "databaseBytes": database_bytes,
        "active": None
        if active is None
        else {
            "datasetVersion": active[0],
            "status": active[1],
            "sourceManifestSha256": active[2],
            "rowCounts": active[3],
            "tableHashes": active[4],
            "sourceAsOfAt": active[5],
        },
        "versions": versions,
    }


def verify_active_publication(dsn: str, manifest: Mapping[str, Any]) -> dict[str, Any]:
    """Read back the committed pointer and counts after the transactional gate."""

    inspected = inspect_active_publication(dsn)
    active = inspected["active"]
    if active is None:
        raise CompactPublishError("Active publication readback is missing")
    expected_counts = {
        table: int(value) for table, value in manifest["rowCounts"].items()
    }
    if (
        active["datasetVersion"] != manifest["datasetVersion"]
        or active["status"] != "ACTIVE"
        or active["sourceManifestSha256"] != manifest["sourceManifestSha256"]
        or active["tableHashes"] != manifest["tableHashes"]
        or active["rowCounts"] != expected_counts
    ):
        raise CompactPublishError("Active publication manifest readback failed")
    with _connect(dsn) as connection:
        actual_counts = _remote_counts(connection, manifest["datasetVersion"])
    if actual_counts != expected_counts:
        raise CompactPublishError("Active publication row-count readback failed")
    return {
        "verified": True,
        "datasetVersion": manifest["datasetVersion"],
        "sourceManifestSha256": manifest["sourceManifestSha256"],
        "rowCounts": actual_counts,
        "databaseBytes": inspected["databaseBytes"],
        "verificationMode": "post-commit-manifest-and-count-readback",
    }


def apply_migration(dsn: str, migration: Path, identity: Mapping[str, str]) -> dict[str, Any]:
    sql = migration.expanduser().resolve(strict=True).read_text(encoding="utf-8")
    if "compact_dashboard_schema_version" not in sql or "cre_system" not in sql:
        raise CompactPublishError("Migration does not identify the compact dashboard schema")
    before = inspect_target(dsn, identity)
    if not before["canCreateDatabaseObjects"] or not before["canCreateInPublic"]:
        raise CompactPublishError("Target role lacks required DDL authority")
    with _connect(dsn, autocommit=True) as connection:
        connection.execute(sql, prepare=False)
    after = inspect_target(dsn, identity)
    if after["isolatedSchemas"] != ["cre_news", "cre_system", "cre_timeseries"]:
        raise CompactPublishError("Migration did not create all isolated schemas")
    with _connect(dsn) as connection:
        version = connection.execute(
            """SELECT schema_value FROM cre_system.schema_meta
               WHERE schema_key='compact_dashboard_schema_version'"""
        ).fetchone()
    if version is None or version[0] != EXPECTED_SCHEMA_VERSION:
        raise CompactPublishError("Remote schema version readback failed")
    return {"applied": True, "before": before, "after": after, "schemaVersion": version[0]}


def _copy_table(connection: Any, package: Path, dataset_version: str, table: str) -> int:
    target, columns, json_columns = TABLE_SPECS[table]
    qualified_columns = ("dataset_version", *columns)
    copy_sql = f"COPY {target} ({','.join(qualified_columns)}) FROM STDIN"
    count = 0
    with connection.cursor() as cursor:
        with cursor.copy(copy_sql) as copy:
            for row in iter_package_rows(package, table):
                missing = set(columns) - set(row)
                unexpected = set(row) - set(columns)
                if missing or unexpected:
                    raise CompactPublishError(
                        f"Package columns mismatch for {table}: missing={sorted(missing)}, unexpected={sorted(unexpected)}"
                    )
                values = [dataset_version]
                for column in columns:
                    value = row[column]
                    if (
                        (table, column) in MONTH_DATE_COLUMNS
                        and isinstance(value, str)
                        and re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", value)
                    ):
                        value = f"{value}-01"
                    if column in json_columns:
                        value = Jsonb(value)
                    values.append(value)
                copy.write_row(values)
                count += 1
    return count


def _clone_table(
    connection: Any,
    *,
    table: str,
    source_dataset_version: str,
    target_dataset_version: str,
) -> int:
    target, columns, _json_columns = TABLE_SPECS[table]
    selected = ",".join(columns)
    result = connection.execute(
        f"""INSERT INTO {target}(dataset_version,{selected})
            SELECT %s,{selected} FROM {target} WHERE dataset_version=%s""",
        (target_dataset_version, source_dataset_version),
    )
    return int(result.rowcount)


def _server_table_difference_count(
    connection: Any,
    *,
    table: str,
    source_dataset_version: str,
    target_dataset_version: str,
) -> dict[str, int]:
    """Prove exact typed equality in both directions without row egress."""

    target, columns, _json_columns = TABLE_SPECS[table]
    selected = ",".join(columns)
    source_minus_target = int(
        connection.execute(
            f"""SELECT count(*) FROM (
                   SELECT {selected} FROM {target} WHERE dataset_version=%s
                   EXCEPT ALL
                   SELECT {selected} FROM {target} WHERE dataset_version=%s
                 ) difference""",
            (source_dataset_version, target_dataset_version),
        ).fetchone()[0]
    )
    target_minus_source = int(
        connection.execute(
            f"""SELECT count(*) FROM (
                   SELECT {selected} FROM {target} WHERE dataset_version=%s
                   EXCEPT ALL
                   SELECT {selected} FROM {target} WHERE dataset_version=%s
                 ) difference""",
            (target_dataset_version, source_dataset_version),
        ).fetchone()[0]
    )
    return {
        "sourceMinusTarget": source_minus_target,
        "targetMinusSource": target_minus_source,
    }


def _active_table_reuse_plan(
    connection: Any,
    manifest: Mapping[str, Any],
) -> tuple[str | None, tuple[str, ...], tuple[str, ...]]:
    """Select only tables backed by the active version's verified exact hash."""

    active = connection.execute(
        """SELECT version.dataset_version,version.table_hashes,version.row_counts
           FROM cre_system.active_manifest active
           JOIN cre_system.dataset_versions version USING(dataset_version)
           WHERE active.slot='dashboard' AND version.status_code='ACTIVE'
           FOR SHARE OF active,version"""
    ).fetchone()
    if active is None:
        return None, (), tuple(LOAD_ORDER)
    active_hashes = active[1]
    active_counts = active[2]
    if not isinstance(active_hashes, Mapping) or not isinstance(active_counts, Mapping):
        return str(active[0]), (), tuple(LOAD_ORDER)
    reusable = tuple(
        table
        for table in LOAD_ORDER
        if active_hashes.get(table) == manifest["tableHashes"].get(table)
        and int(active_counts.get(table, -1)) == int(manifest["rowCounts"].get(table, -2))
    )
    copied = tuple(table for table in LOAD_ORDER if table not in reusable)
    return str(active[0]), reusable, copied


def _enforce_delta_publish_guard(
    connection: Any,
    manifest: Mapping[str, Any],
    *,
    reuse_source: str | None,
    reused_tables: Sequence[str],
    copied_tables: Sequence[str],
    target_exists: bool,
) -> dict[str, Any] | None:
    """Fail closed unless the locked active base and exact delta plan still match."""

    delta = _validated_delta_manifest(manifest)
    if delta is None:
        return None
    active = connection.execute(
        """SELECT version.dataset_version,version.source_manifest_sha256
           FROM cre_system.active_manifest active
           JOIN cre_system.dataset_versions version USING(dataset_version)
           WHERE active.slot='dashboard' AND version.status_code='ACTIVE'
           FOR SHARE OF active,version"""
    ).fetchone()
    if active is None:
        raise CompactPublishError("Delta publish requires an active base dataset")
    if str(active[0]) != delta["baseDatasetVersion"]:
        raise CompactPublishError("Delta publish base dataset is no longer active")
    if str(active[1]) != delta["baseSourceManifestSha256"]:
        raise CompactPublishError("Delta publish active base manifest hash changed")
    if reuse_source != delta["baseDatasetVersion"]:
        raise CompactPublishError("Delta publish clone source does not match its active base")
    if tuple(reused_tables) != DELTA_SERVER_CLONE_TABLES:
        raise CompactPublishError("Delta publish server-clone plan drifted")
    if tuple(copied_tables) != DELTA_CHANGED_TABLES:
        raise CompactPublishError("Delta publish client-copy plan drifted")
    return {
        "validated": True,
        "baseDatasetVersion": delta["baseDatasetVersion"],
        "baseSourceManifestSha256": delta["baseSourceManifestSha256"],
        "serverCloneTables": list(reused_tables),
        "clientCopyTables": list(copied_tables),
        "targetAlreadyExisted": target_exists,
    }


def _seed_auth(connection: Any, subjects: Sequence[Mapping[str, Any]]) -> None:
    sql = """
      INSERT INTO cre_system.authorized_subjects(
        subject_id,email_normalized,approved,approved_at,approved_by,
        revoked_at,revoked_by,access_expires_at,authz_version,updated_at
      ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,1,clock_timestamp())
      ON CONFLICT(subject_id) DO NOTHING
    """
    for subject in subjects:
        connection.execute(
            sql,
            (
                subject["access_subject_id"],
                str(subject["email_normalized"]).strip().lower(),
                bool(subject["is_enabled"]) and subject["revoked_at"] is None,
                subject["approved_at"],
                subject["approved_by"],
                subject["revoked_at"],
                subject["revoked_by"],
                subject["access_expires_at"],
            ),
        )


def _remote_counts(connection: Any, dataset_version: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for name in LOAD_ORDER:
        table = TABLE_SPECS[name][0]
        counts[name] = int(
            connection.execute(
                f"SELECT count(*) FROM {table} WHERE dataset_version=%s",
                (dataset_version,),
            ).fetchone()[0]
        )
    return counts


def _normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _normalize_decimal(value: Any) -> str | None:
    if value is None:
        return None
    decimal_value = Decimal(str(value))
    if not decimal_value.is_finite():
        raise CompactPublishError("Non-finite numeric value in semantic parity check")
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _normalize_semantic_value(table: str, column: str, value: Any) -> Any:
    if value is None:
        return None
    if (table, column) in TIMESTAMP_COLUMNS:
        return _normalize_timestamp(value)
    if (table, column) in MONTH_DATE_COLUMNS:
        if isinstance(value, date):
            return value.isoformat()
        text = str(value)
        return f"{text}-01" if re.fullmatch(r"[0-9]{4}-(?:0[1-9]|1[0-2])", text) else text
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if (table, column) in DECIMAL_COLUMNS:
        return _normalize_decimal(value)
    if (table, column) in FLOAT_COLUMNS:
        return format(float(value), ".17g")
    if isinstance(value, tuple):
        return list(value)
    return value


def _normalize_semantic_row(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        column: _normalize_semantic_value(table, column, row[column])
        for column in TABLE_SPECS[table][1]
    }


def verify_remote_semantic_parity(
    connection: Any,
    package: Path,
    dataset_version: str,
    *,
    tables: Sequence[str] = LOAD_ORDER,
) -> dict[str, dict[str, Any]]:
    """Compare every stored value with its package row after target-type normalization."""

    parity: dict[str, dict[str, Any]] = {}
    unknown = set(tables) - set(LOAD_ORDER)
    if unknown:
        raise CompactPublishError(f"Unknown semantic parity tables: {sorted(unknown)!r}")
    for table in tables:
        target, columns, _json_columns = TABLE_SPECS[table]
        select_columns = ",".join(columns)
        sql = (
            f"SELECT {select_columns} FROM {target} "
            f"WHERE dataset_version=%s ORDER BY {TABLE_ORDER_BY[table]}"
        )
        package_rows = iter(iter_package_rows(package, table))
        package_digest = hashlib.sha256()
        remote_digest = hashlib.sha256()
        row_count = 0
        semantic_bytes = 0
        with connection.cursor(name=f"semantic_{table}") as cursor:
            cursor.itersize = 2_000
            cursor.execute(sql, (dataset_version,))
            for remote_values in cursor:
                try:
                    package_row = next(package_rows)
                except StopIteration as error:
                    raise CompactPublishError(
                        f"Remote semantic parity has extra row in {table} at position {row_count + 1}"
                    ) from error
                remote_row = dict(zip(columns, remote_values, strict=True))
                normalized_package = _normalize_semantic_row(table, package_row)
                normalized_remote = _normalize_semantic_row(table, remote_row)
                if normalized_package != normalized_remote:
                    differing = [
                        column for column in columns
                        if normalized_package[column] != normalized_remote[column]
                    ]
                    raise CompactPublishError(
                        f"Remote semantic parity mismatch in {table} row {row_count + 1}; "
                        f"columns={differing}"
                    )
                package_encoded = (canonical_json(normalized_package) + "\n").encode("utf-8")
                remote_encoded = (canonical_json(normalized_remote) + "\n").encode("utf-8")
                package_digest.update(package_encoded)
                remote_digest.update(remote_encoded)
                semantic_bytes += len(remote_encoded)
                row_count += 1
        try:
            next(package_rows)
        except StopIteration:
            pass
        else:
            raise CompactPublishError(f"Remote semantic parity is missing rows from {table}")
        if package_digest.digest() != remote_digest.digest():
            raise CompactPublishError(f"Remote semantic hash mismatch for {table}")
        parity[table] = {
            "rowCount": row_count,
            "semanticSha256": remote_digest.hexdigest(),
            "packageSemanticSha256": package_digest.hexdigest(),
            "semanticReadbackBytes": semantic_bytes,
            "matched": True,
        }
    return parity


def preactivation_parity_gate(
    connection: Any,
    package: Path,
    dataset_version: str,
    expected_counts: Mapping[str, int],
    *,
    semantic_tables: Sequence[str] | None = None,
    server_clone_evidence: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[dict[str, int], dict[str, dict[str, Any]]]:
    """Block active-pointer mutation unless counts and every normalized value match."""

    actual_counts = _remote_counts(connection, dataset_version)
    if actual_counts != dict(expected_counts):
        raise CompactPublishError(
            f"Remote count parity failed: expected={dict(expected_counts)!r}, actual={actual_counts!r}"
        )
    if semantic_tables is None:
        semantic_parity = verify_remote_semantic_parity(connection, package, dataset_version)
    else:
        semantic_parity = verify_remote_semantic_parity(
            connection,
            package,
            dataset_version,
            tables=semantic_tables,
        )
    for table, evidence in (server_clone_evidence or {}).items():
        if table in semantic_parity:
            raise CompactPublishError(f"Table has duplicate parity modes: {table}")
        difference = evidence.get("bidirectionalExceptAll")
        if (
            not isinstance(difference, Mapping)
            or int(difference.get("sourceMinusTarget", -1)) != 0
            or int(difference.get("targetMinusSource", -1)) != 0
            or int(evidence.get("rowCount", -1)) != int(expected_counts.get(table, -2))
        ):
            raise CompactPublishError(f"Server clone parity failed for {table}")
        semantic_parity[table] = {
            "matched": True,
            "rowCount": int(evidence["rowCount"]),
            "validationMode": "server-clone-bidirectional-except-all",
            "sourceDatasetVersion": evidence["sourceDatasetVersion"],
            "bidirectionalExceptAll": dict(difference),
            "semanticReadbackBytes": 0,
        }
    for table in semantic_tables or LOAD_ORDER:
        if table in semantic_parity:
            semantic_parity[table].setdefault(
                "validationMode", "client-full-semantic-readback"
            )
    if set(semantic_parity) != set(expected_counts) or any(
        not result.get("matched")
        or int(result.get("rowCount", -1)) != int(expected_counts[table])
        for table, result in semantic_parity.items()
    ):
        raise CompactPublishError("Remote pre-activation semantic parity gate failed")
    return actual_counts, semantic_parity


def publish_package(
    dsn: str,
    package: Path,
    auth_db: Path,
    *,
    activate: bool,
    max_database_bytes: int | None = None,
    seed_auth: bool = True,
) -> dict[str, Any]:
    started = perf_counter()
    package = package.expanduser().resolve(strict=True)
    manifest = read_manifest(package)
    package_verification = verify_package(package)
    delta = _validated_delta_manifest(manifest)
    if delta is not None and seed_auth:
        raise CompactPublishError("Delta publication requires preserved authorization")
    subjects = read_auth_subjects(auth_db) if seed_auth else []
    dataset_version = manifest["datasetVersion"]
    expected_counts = {key: int(value) for key, value in manifest["rowCounts"].items()}
    action = "loaded"
    table_actions: dict[str, dict[str, Any]] = {}
    reused_tables: tuple[str, ...] = ()
    copied_tables: tuple[str, ...] = tuple(LOAD_ORDER)
    uploaded_tables: tuple[str, ...] = ()
    reuse_source: str | None = None
    database_bytes_before = 0
    database_bytes_after_load = 0
    auth_subject_count_before = 0
    auth_subject_count_after = 0
    delta_guard: dict[str, Any] | None = None
    estimated_growth_bytes = int(manifest["estimatedUploadBytes"]) * 2
    if max_database_bytes is not None and max_database_bytes <= 0:
        raise CompactPublishError("Maximum database bytes must be positive")

    with _connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='15min'")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (ADVISORY_LOCK_NAME,),
            )
            schema_version = connection.execute(
                """SELECT schema_value FROM cre_system.schema_meta
                   WHERE schema_key='compact_dashboard_schema_version'"""
            ).fetchone()
            if schema_version is None or schema_version[0] != EXPECTED_SCHEMA_VERSION:
                raise CompactPublishError("Apply the compact migration before publishing")
            auth_subject_count_before = int(
                connection.execute(
                    "SELECT count(*) FROM cre_system.authorized_subjects"
                ).fetchone()[0]
            )
            database_bytes_before = int(
                connection.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            )
            if (
                max_database_bytes is not None
                and database_bytes_before + estimated_growth_bytes > max_database_bytes
            ):
                raise CompactPublishError(
                    "Capacity guard rejected the publish before any dataset write"
                )
            existing = connection.execute(
                """SELECT source_manifest_sha256,schema_version,status_code
                   FROM cre_system.dataset_versions WHERE dataset_version=%s""",
                (dataset_version,),
            ).fetchone()
            if existing is None or delta is not None:
                planned_source, planned_reused, planned_copied = _active_table_reuse_plan(
                    connection, manifest
                )
                delta_guard = _enforce_delta_publish_guard(
                    connection,
                    manifest,
                    reuse_source=planned_source,
                    reused_tables=planned_reused,
                    copied_tables=planned_copied,
                    target_exists=existing is not None,
                )
            if existing is None:
                reuse_source, reused_tables, copied_tables = (
                    planned_source,
                    planned_reused,
                    planned_copied,
                )
                uploaded_tables = copied_tables
                connection.execute(
                    """INSERT INTO cre_system.dataset_versions(
                         dataset_version,schema_version,status_code,source_as_of_at,
                         source_snapshot,source_manifest_sha256,row_counts,table_hashes,
                         facets,package_bytes
                       ) VALUES(%s,%s,'LOADING',%s,%s,%s,%s,%s,%s,%s)""",
                    (
                        dataset_version,
                        manifest["schemaVersion"],
                        manifest["sourceAsOfAt"],
                        Jsonb(manifest["source"]),
                        manifest["sourceManifestSha256"],
                        Jsonb(manifest["rowCounts"]),
                        Jsonb(manifest["tableHashes"]),
                        Jsonb(manifest["facets"]),
                        int(manifest["packageBytes"]),
                    ),
                )
                for lineage in manifest["lineage"]:
                    connection.execute(
                        """INSERT INTO cre_system.dataset_lineage(
                             dataset_version,dataset_code,source_code,source_as_of_date,
                             generated_at,source_status_code,source_row_count,
                             serving_row_count,source_content_sha256,metadata
                           ) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (
                            dataset_version,
                            lineage["dataset_code"],
                            lineage["source_code"],
                            lineage["source_as_of_date"],
                            lineage["generated_at"],
                            lineage["source_status_code"],
                            int(lineage["source_row_count"]),
                            int(lineage["serving_row_count"]),
                            lineage["source_content_sha256"],
                            Jsonb(lineage["metadata"]),
                        ),
                    )
                copied: dict[str, int] = {}
                clone_evidence: dict[str, dict[str, Any]] = {}
                for table in LOAD_ORDER:
                    table_started = perf_counter()
                    if table in reused_tables:
                        if reuse_source is None:
                            raise CompactPublishError("Server clone has no active source version")
                        row_count = _clone_table(
                            connection,
                            table=table,
                            source_dataset_version=reuse_source,
                            target_dataset_version=dataset_version,
                        )
                        difference = _server_table_difference_count(
                            connection,
                            table=table,
                            source_dataset_version=reuse_source,
                            target_dataset_version=dataset_version,
                        )
                        clone_evidence[table] = {
                            "rowCount": row_count,
                            "sourceDatasetVersion": reuse_source,
                            "bidirectionalExceptAll": difference,
                        }
                        table_actions[table] = {
                            "action": "server-clone",
                            "rowCount": row_count,
                            "packageUncompressedBytesSent": 0,
                            "sourceDatasetVersion": reuse_source,
                            "bidirectionalExceptAll": difference,
                            "durationMs": round((perf_counter() - table_started) * 1_000, 3),
                        }
                    else:
                        row_count = _copy_table(connection, package, dataset_version, table)
                        table_actions[table] = {
                            "action": "client-copy",
                            "rowCount": row_count,
                            "packageUncompressedBytesSent": int(
                                manifest["tables"][table]["uncompressedBytes"]
                            ),
                            "durationMs": round((perf_counter() - table_started) * 1_000, 3),
                        }
                    copied[table] = row_count
                if copied != expected_counts:
                    raise CompactPublishError(f"COPY count mismatch: {copied!r}")
                connection.execute(
                    """UPDATE cre_system.dataset_versions
                       SET status_code='READY',ready_at=clock_timestamp()
                       WHERE dataset_version=%s AND status_code='LOADING'""",
                    (dataset_version,),
                )
            else:
                if existing[0] != manifest["sourceManifestSha256"] or existing[1] != manifest["schemaVersion"]:
                    raise CompactPublishError("Existing dataset version has conflicting identity")
                action = "verified-existing"
                clone_evidence = {}
                copied_tables = tuple(LOAD_ORDER)
                uploaded_tables = ()

            if seed_auth:
                _seed_auth(connection, subjects)
            auth_subject_count_after = int(
                connection.execute(
                    "SELECT count(*) FROM cre_system.authorized_subjects"
                ).fetchone()[0]
            )
            if not seed_auth and auth_subject_count_after != auth_subject_count_before:
                raise CompactPublishError(
                    "Automatic publication unexpectedly changed authorization subjects"
                )
            actual_counts, semantic_gate = preactivation_parity_gate(
                connection,
                package,
                dataset_version,
                expected_counts,
                semantic_tables=copied_tables,
                server_clone_evidence=clone_evidence,
            )
            for table in copied_tables:
                if table in table_actions:
                    table_actions[table]["semanticReadbackBytes"] = int(
                        semantic_gate[table]["semanticReadbackBytes"]
                    )
            for table in LOAD_ORDER:
                connection.execute(f"ANALYZE {TABLE_SPECS[table][0]}")
            database_bytes_after_load = int(
                connection.execute("SELECT pg_database_size(current_database())").fetchone()[0]
            )
            if (
                max_database_bytes is not None
                and database_bytes_after_load > max_database_bytes
            ):
                raise CompactPublishError(
                    "Capacity guard rolled back the publish before activation"
                )
            if activate:
                connection.execute(
                    """UPDATE cre_system.dataset_versions SET status_code='RETIRED'
                       WHERE status_code='ACTIVE' AND dataset_version<>%s""",
                    (dataset_version,),
                )
                connection.execute(
                    """INSERT INTO cre_system.active_manifest(slot,dataset_version,switched_at)
                       VALUES('dashboard',%s,clock_timestamp())
                       ON CONFLICT(slot) DO UPDATE SET
                         dataset_version=excluded.dataset_version,switched_at=excluded.switched_at""",
                    (dataset_version,),
                )
                connection.execute(
                    """UPDATE cre_system.dataset_versions
                       SET status_code='ACTIVE',activated_at=COALESCE(activated_at,clock_timestamp())
                       WHERE dataset_version=%s""",
                    (dataset_version,),
                )
            final_status = connection.execute(
                "SELECT status_code FROM cre_system.dataset_versions WHERE dataset_version=%s",
                (dataset_version,),
            ).fetchone()[0]

    return {
        "published": True,
        "action": action,
        "activated": activate,
        "datasetVersion": dataset_version,
        "status": final_status,
        "rowCounts": actual_counts,
        "preactivationSemanticParity": semantic_gate,
        "authSubjectCount": auth_subject_count_after,
        "authSubjectsSeeded": bool(seed_auth),
        "authSubjectCountBefore": auth_subject_count_before,
        "authSubjectCountAfter": auth_subject_count_after,
        "deltaGuard": delta_guard,
        "packageVerification": package_verification,
        "tableActions": table_actions,
        "clientCopiedTables": list(uploaded_tables),
        "semanticReadbackTables": list(copied_tables),
        "serverClonedTables": list(reused_tables),
        "clientCopiedRows": sum(actual_counts[table] for table in uploaded_tables),
        "serverClonedRows": sum(actual_counts[table] for table in reused_tables),
        "packageUncompressedBytesSent": sum(
            int(manifest["tables"][table]["uncompressedBytes"])
            for table in uploaded_tables
        ),
        "semanticReadbackBytes": sum(
            int(semantic_gate[table].get("semanticReadbackBytes", 0))
            for table in LOAD_ORDER
        ),
        "capacity": {
            "databaseBytesBefore": database_bytes_before,
            "databaseBytesAfterLoad": database_bytes_after_load,
            "estimatedGrowthBytesGuarded": estimated_growth_bytes,
            "maximumDatabaseBytes": max_database_bytes,
        },
        "durationMs": round((perf_counter() - started) * 1_000, 3),
    }


def inspect_prune_candidate(dsn: str, dataset_version: str) -> dict[str, Any]:
    if not DATASET_VERSION_RE.fullmatch(dataset_version):
        raise CompactPublishError("Prune dataset version is invalid")
    with _connect(dsn) as connection:
        row = connection.execute(
            """SELECT version.status_code,
                      active.dataset_version IS NOT NULL AS is_active,
                      version.schema_version
               FROM cre_system.dataset_versions version
               LEFT JOIN cre_system.active_manifest active
                 ON active.dataset_version=version.dataset_version
               WHERE version.dataset_version=%s""",
            (dataset_version,),
        ).fetchone()
        if row is None:
            raise CompactPublishError("Prune dataset version does not exist")
        counts = _remote_counts(connection, dataset_version)
        auth_count = int(connection.execute("SELECT count(*) FROM cre_system.authorized_subjects").fetchone()[0])
    return {
        "datasetVersion": dataset_version,
        "status": row[0],
        "active": bool(row[1]),
        "schemaVersion": row[2],
        "rowCounts": counts,
        "authSubjectCount": auth_count,
    }


def prune_dataset_version(
    dsn: str,
    dataset_version: str,
    *,
    compact_storage: bool,
) -> dict[str, Any]:
    before = inspect_prune_candidate(dsn, dataset_version)
    if before["active"] or before["status"] != "RETIRED":
        raise CompactPublishError("Only an explicitly named RETIRED, non-active dataset may be pruned")
    with _connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='15min'")
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (ADVISORY_LOCK_NAME,),
            )
            active = connection.execute(
                "SELECT dataset_version FROM cre_system.active_manifest WHERE slot='dashboard' FOR SHARE"
            ).fetchone()
            if active is None or active[0] == dataset_version:
                raise CompactPublishError("Prune would remove the active dataset")
            deleted = connection.execute(
                """DELETE FROM cre_system.dataset_versions
                   WHERE dataset_version=%s AND status_code='RETIRED'
                     AND NOT EXISTS (
                       SELECT 1 FROM cre_system.active_manifest active
                       WHERE active.dataset_version=cre_system.dataset_versions.dataset_version
                     )""",
                (dataset_version,),
            ).rowcount
            if deleted != 1:
                raise CompactPublishError("Prune target changed state before deletion")
            auth_after_delete = int(
                connection.execute("SELECT count(*) FROM cre_system.authorized_subjects").fetchone()[0]
            )
            if auth_after_delete != before["authSubjectCount"]:
                raise CompactPublishError("Dataset prune unexpectedly changed authorization subjects")

    compacted: list[str] = []
    if compact_storage:
        with _connect(dsn, autocommit=True) as connection:
            connection.execute("SET statement_timeout='15min'")
            for table in LOAD_ORDER:
                target = TABLE_SPECS[table][0]
                connection.execute(f"VACUUM (FULL, ANALYZE) {target}")
                compacted.append(target)
            for target in ("cre_system.dataset_lineage", "cre_system.dataset_versions"):
                connection.execute(f"VACUUM (FULL, ANALYZE) {target}")
                compacted.append(target)

    with _connect(dsn) as connection:
        active = connection.execute(
            "SELECT dataset_version FROM cre_system.active_manifest WHERE slot='dashboard'"
        ).fetchone()[0]
        remaining = [
            {"datasetVersion": row[0], "status": row[1]}
            for row in connection.execute(
                "SELECT dataset_version,status_code FROM cre_system.dataset_versions ORDER BY created_at"
            )
        ]
        auth_after = int(connection.execute("SELECT count(*) FROM cre_system.authorized_subjects").fetchone()[0])
        database_bytes = int(connection.execute("SELECT pg_database_size(current_database())").fetchone()[0])
    return {
        "pruned": True,
        "deletedDatasetVersion": dataset_version,
        "deletedRowCounts": before["rowCounts"],
        "activeDatasetVersion": active,
        "remainingVersions": remaining,
        "authSubjectCountBefore": before["authSubjectCount"],
        "authSubjectCountAfter": auth_after,
        "storageCompacted": compact_storage,
        "compactedRelations": compacted,
        "databaseBytes": database_bytes,
    }


def _plan_summary(plan: Any) -> dict[str, Any]:
    wrapper = plan[0] if isinstance(plan, list) else plan
    root = wrapper["Plan"] if "Plan" in wrapper else wrapper
    indexes: set[str] = set()
    node_types: list[str] = []

    def visit(node: Mapping[str, Any]) -> None:
        node_type = node.get("Node Type")
        if isinstance(node_type, str):
            node_types.append(node_type)
        index_name = node.get("Index Name")
        if isinstance(index_name, str):
            indexes.add(index_name)
        for child in node.get("Plans", []):
            visit(child)

    visit(root)
    result = {"nodeTypes": node_types, "indexes": sorted(indexes), "planRows": root.get("Plan Rows")}
    if "Execution Time" in wrapper:
        result["executionMs"] = float(wrapper["Execution Time"])
    return result


def _fresh_connection_rpc_timing(dsn: str, sql: str, params: Sequence[Any]) -> dict[str, float]:
    started = perf_counter()
    with _connect(dsn) as connection:
        connected = perf_counter()
        connection.execute("SET statement_timeout='10s'")
        query_started = perf_counter()
        connection.execute(sql, params).fetchone()
        finished = perf_counter()
    return {
        "connectMs": round((connected - started) * 1_000, 3),
        "queryMs": round((finished - query_started) * 1_000, 3),
        "totalMs": round((finished - started) * 1_000, 3),
    }


def verify_remote(dsn: str, package: Path) -> dict[str, Any]:
    package = package.expanduser().resolve(strict=True)
    manifest = read_manifest(package)
    dataset_version = manifest["datasetVersion"]
    expected_counts = {key: int(value) for key, value in manifest["rowCounts"].items()}
    pulse_package = next(iter_package_rows(package, "market_pulse"))["payload"]
    article_sample = next(iter_package_rows(package, "articles"))
    two_char_term = next(
        term
        for row in iter_package_rows(package, "article_search_documents")
        for term in row["terms"]
        if len(term) == 2 and re.search(r"[가-힣]", term)
    )
    with _connect(dsn) as connection:
        with connection.transaction():
            connection.execute("SET LOCAL statement_timeout='60s'")
            active = connection.execute(
                "SELECT dataset_version FROM cre_system.active_manifest WHERE slot='dashboard'"
            ).fetchone()
            if active is None or active[0] != dataset_version:
                raise CompactPublishError("Expected package is not the active version")
            counts = _remote_counts(connection, dataset_version)
            if counts != expected_counts:
                raise CompactPublishError("Remote readback count parity failed")
            dataset_versions = [
                {"datasetVersion": row[0], "status": row[1], "schemaVersion": row[2]}
                for row in connection.execute(
                    """SELECT dataset_version,status_code,schema_version
                       FROM cre_system.dataset_versions ORDER BY created_at"""
                )
            ]
            semantic_parity = verify_remote_semantic_parity(
                connection,
                package,
                dataset_version,
            )
            invalid_constraints = int(
                connection.execute(
                    """SELECT count(*) FROM pg_constraint constraint_row
                       JOIN pg_namespace namespace ON namespace.oid=constraint_row.connamespace
                       WHERE namespace.nspname IN ('cre_system','cre_news','cre_timeseries')
                         AND NOT constraint_row.convalidated"""
                ).fetchone()[0]
            )
            rls = {
                f"{row[0]}.{row[1]}": bool(row[2])
                for row in connection.execute(
                    """SELECT namespace.nspname,class.relname,class.relrowsecurity
                       FROM pg_class class JOIN pg_namespace namespace ON namespace.oid=class.relnamespace
                       WHERE namespace.nspname IN ('cre_system','cre_news','cre_timeseries')
                         AND class.relkind='r' ORDER BY namespace.nspname,class.relname"""
                )
            }
            if not rls or not all(rls.values()):
                raise CompactPublishError("At least one private serving table lacks RLS")
            relation_sizes = [
                {
                    "schema": row[0],
                    "relation": row[1],
                    "tableBytes": int(row[2]),
                    "indexBytes": int(row[3]),
                    "totalBytes": int(row[4]),
                }
                for row in connection.execute(
                    """SELECT namespace.nspname,class.relname,
                              pg_relation_size(class.oid),pg_indexes_size(class.oid),
                              pg_total_relation_size(class.oid)
                       FROM pg_class class JOIN pg_namespace namespace ON namespace.oid=class.relnamespace
                       WHERE namespace.nspname IN ('cre_system','cre_news','cre_timeseries')
                         AND class.relkind='r' ORDER BY namespace.nspname,class.relname"""
                )
            ]
            database_bytes = int(connection.execute("SELECT pg_database_size(current_database())").fetchone()[0])
            manifest_payload = connection.execute("SELECT public.dashboard_serving_manifest()").fetchone()[0]
            daily = connection.execute(
                "SELECT public.dashboard_daily_articles(NULL,200,%s)", (dataset_version,)
            ).fetchone()[0]
            detail = connection.execute(
                "SELECT public.dashboard_article_detail(%s,%s)",
                (article_sample["document_id"], dataset_version),
            ).fetchone()[0]
            macro = connection.execute(
                "SELECT public.dashboard_macro_timeseries(%s)", (dataset_version,)
            ).fetchone()[0]
            permit = connection.execute(
                """SELECT public.dashboard_permit_timeseries(
                     'EVENT_TYPE',NULL,NULL,NULL,NULL,NULL,NULL,%s)""",
                (dataset_version,),
            ).fetchone()[0]
            pulse = connection.execute(
                "SELECT public.dashboard_market_pulse(%s)", (dataset_version,)
            ).fetchone()[0]
            evidence = connection.execute(
                """SELECT public.dashboard_contextual_evidence_search(
                     %s,'{}'::jsonb,8,%s)""",
                (two_char_term, dataset_version),
            ).fetchone()[0]
            literal = connection.execute(
                """SELECT public.dashboard_contextual_evidence_search(
                     '%%_','{}'::jsonb,8,%s)""",
                (dataset_version,),
            ).fetchone()[0]
            auth_rows = connection.execute(
                "SELECT subject_id,email_normalized FROM cre_system.authorized_subjects ORDER BY subject_id"
            ).fetchall()
            auth_checks = [
                connection.execute(
                    "SELECT * FROM public.dashboard_authorize_subject(%s)", (row[0],)
                ).fetchone()
                for row in auth_rows
            ]
            unknown_auth = connection.execute(
                "SELECT * FROM public.dashboard_authorize_subject('unknown-subject')"
            ).fetchone()
            connection.execute("SAVEPOINT rate_limit_qa")
            rate_first = connection.execute(
                "SELECT public.dashboard_consume_login_attempts(ARRAY['qa-a','qa-b'])"
            ).fetchone()[0]
            rate_clear = connection.execute(
                "SELECT public.dashboard_clear_login_attempts(ARRAY['qa-a','qa-b'])"
            ).fetchone()[0]
            connection.execute("ROLLBACK TO SAVEPOINT rate_limit_qa")

            plans: dict[str, Any] = {}
            plan_queries = {
                "daily": (
                    """EXPLAIN (FORMAT JSON) SELECT document_id FROM cre_news.articles
                       WHERE dataset_version=%s AND article_date=%s
                       ORDER BY published_at DESC,document_id LIMIT 200""",
                    (dataset_version, daily["selectedDate"]),
                ),
                "macro": (
                    """EXPLAIN (FORMAT JSON) SELECT numeric_value FROM cre_timeseries.macro_monthly
                       WHERE dataset_version=%s AND series_code='BOK_BASE_RATE_MONTHLY'
                         AND observation_month BETWEEN date '2025-01-01' AND date '2026-12-01'
                       ORDER BY observation_month""",
                    (dataset_version,),
                ),
                "permit": (
                    """EXPLAIN (FORMAT JSON) SELECT sum(permit_count) FROM cre_timeseries.permit_monthly
                       WHERE dataset_version=%s AND event_type='PERMIT'
                         AND event_month BETWEEN date '2025-01-01' AND date '2026-12-01'""",
                    (dataset_version,),
                ),
                "twoCharacterEvidenceCandidate": (
                    """EXPLAIN (FORMAT JSON)
                       WITH candidate_ids AS MATERIALIZED (
                         SELECT document_id FROM cre_news.article_search_documents
                         WHERE dataset_version=%s AND terms @> ARRAY[%s]
                       )
                       SELECT article.document_id FROM candidate_ids candidate
                       JOIN cre_news.articles article
                         ON article.dataset_version=%s AND article.document_id=candidate.document_id
                       LIMIT 8""",
                    (dataset_version, two_char_term, dataset_version),
                ),
                "twoCharacterEvidenceRpc": (
                    """EXPLAIN (ANALYZE,FORMAT JSON)
                       SELECT public.dashboard_contextual_evidence_search(%s,'{}'::jsonb,8,%s)""",
                    (two_char_term, dataset_version),
                ),
                "trigramEvidenceCandidate": (
                    """EXPLAIN (FORMAT JSON)
                       WITH candidate_ids AS MATERIALIZED (
                         SELECT document_id FROM cre_news.articles
                         WHERE dataset_version=%s AND search_text ILIKE '%%부동산%%'
                       )
                       SELECT article.document_id FROM candidate_ids candidate
                       JOIN cre_news.articles article
                         ON article.dataset_version=%s AND article.document_id=candidate.document_id
                       LIMIT 8""",
                    (dataset_version, dataset_version),
                ),
                "trigramEvidenceRpc": (
                    """EXPLAIN (ANALYZE,FORMAT JSON)
                       SELECT public.dashboard_contextual_evidence_search('부동산','{}'::jsonb,8,%s)""",
                    (dataset_version,),
                ),
            }
            for name, (sql, params) in plan_queries.items():
                if "Evidence" in name:
                    connection.execute("SET LOCAL enable_seqscan=off")
                plans[name] = _plan_summary(connection.execute(sql, params).fetchone()[0])

    pulse_readback = dict(pulse)
    pulse_readback.pop("datasetVersion", None)
    if canonical_json(pulse_readback) != canonical_json(pulse_package):
        raise CompactPublishError("Market pulse payload parity failed")
    if manifest_payload.get("datasetVersion") != dataset_version:
        raise CompactPublishError("Manifest RPC version mismatch")
    if daily.get("datasetVersion") != dataset_version or int(daily.get("returned", -1)) > 200:
        raise CompactPublishError("Daily article RPC parity failed")
    if detail.get("id") != article_sample["document_id"]:
        raise CompactPublishError("Article detail RPC parity failed")
    if macro.get("datasetVersion") != dataset_version or len(macro.get("series", [])) != 13:
        raise CompactPublishError("Macro RPC parity failed")
    if permit.get("datasetVersion") != dataset_version or not permit.get("series"):
        raise CompactPublishError("Permit RPC parity failed")
    if evidence.get("datasetVersion") != dataset_version or not evidence.get("items"):
        raise CompactPublishError("Two-character evidence RPC failed")
    if int(literal.get("total", -1)) != 0:
        raise CompactPublishError("Evidence wildcard escaping failed")
    if not all(bool(row[0]) for row in auth_checks) or bool(unknown_auth[0]):
        raise CompactPublishError("Authorization RPC parity failed")
    if rate_first.get("blocked") is not False or int(rate_clear.get("cleared", -1)) != 2:
        raise CompactPublishError("Rate-limit RPC parity failed")

    fresh_rpc_timing = {
        "twoCharacter": _fresh_connection_rpc_timing(
            dsn,
            "SELECT public.dashboard_contextual_evidence_search(%s,'{}'::jsonb,8,%s)",
            (two_char_term, dataset_version),
        ),
        "trigram": _fresh_connection_rpc_timing(
            dsn,
            "SELECT public.dashboard_contextual_evidence_search('부동산','{}'::jsonb,8,%s)",
            (dataset_version,),
        ),
        "measurementNote": "Fresh database connections and cold prepared plans; operating-system cache state was not flushed.",
    }

    schema_sizes: dict[str, dict[str, int]] = {}
    for row in relation_sizes:
        current = schema_sizes.setdefault(row["schema"], {"tableBytes": 0, "indexBytes": 0, "totalBytes": 0})
        for key in current:
            current[key] += row[key]
    return {
        "verified": True,
        "datasetVersion": dataset_version,
        "databaseBytes": database_bytes,
        "sourceArchiveBytes": int(manifest["source"]["bytes"]),
        "packageCompressedBytes": int(manifest["packageBytes"]),
        "packageUncompressedBytes": int(manifest["estimatedUploadBytes"]),
        "rowCounts": counts,
        "semanticParity": semantic_parity,
        "invalidConstraints": invalid_constraints,
        "rls": rls,
        "relations": relation_sizes,
        "schemaSizes": schema_sizes,
        "rpc": {
            "dailySelectedDate": daily["selectedDate"],
            "dailyTotal": daily["total"],
            "macroSeries": len(macro["series"]),
            "permitSeries": len(permit["series"]),
            "marketPulseAsOfPeriod": pulse["asOfPeriod"],
            "evidenceProbe": two_char_term,
            "evidenceReturned": evidence["returned"],
            "literalWildcardTotal": literal["total"],
            "authApproved": sum(1 for row in auth_checks if row[0]),
            "unknownAuthApproved": bool(unknown_auth[0]),
            "rateLimitBlockedFirst": rate_first["blocked"],
            "rateLimitCleared": rate_clear["cleared"],
        },
        "queryPlans": plans,
        "freshConnectionRpcTiming": fresh_rpc_timing,
        "retention": {
            "versionCount": len(dataset_versions),
            "versions": dataset_versions,
            "policy": "Never delete ACTIVE. Normally retain one prior verified version; the bootstrap-only v1.0 trial was explicitly pruned after v1.1 full parity.",
            "verificationMutatedRetention": False,
        },
    }


def write_report(path: Path | None, payload: Mapping[str, Any]) -> None:
    if path is None:
        return
    resolved = path.expanduser().resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=_json_default) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _common_target(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--target-ref", required=True)
    parser.add_argument("--pooler-host", required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subparsers.add_parser("inspect")
    _common_target(inspect_parser)

    migrate_parser = subparsers.add_parser("migrate")
    _common_target(migrate_parser)
    migrate_parser.add_argument("--migration", type=Path, default=DEFAULT_MIGRATION)
    migrate_parser.add_argument("--apply", action="store_true")

    package_parser = subparsers.add_parser("verify-package")
    package_parser.add_argument("--package", type=Path, required=True)

    publish_parser = subparsers.add_parser("publish")
    _common_target(publish_parser)
    publish_parser.add_argument("--package", type=Path, required=True)
    publish_parser.add_argument("--auth-db", type=Path, default=DEFAULT_AUTH_DB)
    publish_parser.add_argument("--apply", action="store_true")
    publish_parser.add_argument("--activate", action="store_true")
    publish_parser.add_argument(
        "--preserve-auth",
        action="store_true",
        help="Do not read or seed local authorization subjects during publication",
    )
    publish_parser.add_argument("--max-database-bytes", type=int)
    publish_parser.add_argument("--report", type=Path)

    verify_parser = subparsers.add_parser("verify-remote")
    _common_target(verify_parser)
    verify_parser.add_argument("--package", type=Path, required=True)
    verify_parser.add_argument("--report", type=Path)

    prune_parser = subparsers.add_parser("prune")
    _common_target(prune_parser)
    prune_parser.add_argument("--dataset-version", required=True)
    prune_parser.add_argument("--apply", action="store_true")
    prune_parser.add_argument("--compact-storage", action="store_true")
    prune_parser.add_argument("--report", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "verify-package":
        result = verify_package(args.package)
    else:
        dsn, identity = target_connection_info(
            args.env,
            expected_ref=args.target_ref,
            pooler_host=args.pooler_host,
        )
        if args.command == "inspect":
            result = inspect_target(dsn, identity)
        elif args.command == "migrate":
            if not args.apply:
                result = {
                    "mode": "PLAN",
                    "willWrite": False,
                    "target": inspect_target(dsn, identity),
                    "migration": str(args.migration.resolve()),
                }
            else:
                result = apply_migration(dsn, args.migration, identity)
        elif args.command == "publish":
            if not args.apply:
                package_manifest = read_manifest(args.package)
                result = {
                    "mode": "PLAN",
                    "willWrite": False,
                    "target": inspect_target(dsn, identity),
                    "package": package_manifest,
                    "packageVerification": verify_package(args.package),
                    "authSubjectCount": (
                        None
                        if args.preserve_auth
                        else len(read_auth_subjects(args.auth_db))
                    ),
                    "preserveAuthRequested": bool(args.preserve_auth),
                    "maximumDatabaseBytes": args.max_database_bytes,
                    "activateRequested": bool(args.activate),
                }
            else:
                published = publish_package(
                    dsn,
                    args.package,
                    args.auth_db,
                    activate=bool(args.activate),
                    max_database_bytes=args.max_database_bytes,
                    seed_auth=not bool(args.preserve_auth),
                )
                if not args.activate:
                    verified = None
                elif args.preserve_auth:
                    # The legacy end-to-end verifier deliberately exercises the
                    # login-rate limiter.  A preserve-auth publication instead
                    # performs only bounded pointer/hash/count readback; full
                    # semantic parity already passed before activation.
                    verified = verify_active_publication(
                        dsn, read_manifest(args.package)
                    )
                else:
                    verified = verify_remote(dsn, args.package)
                result = {"publish": published, "verification": verified}
                write_report(args.report, result)
        elif args.command == "verify-remote":
            result = verify_remote(dsn, args.package)
            write_report(args.report, result)
        elif args.command == "prune":
            if not args.apply:
                result = {
                    "mode": "PLAN",
                    "willWrite": False,
                    "target": inspect_target(dsn, identity),
                    "candidate": inspect_prune_candidate(dsn, args.dataset_version),
                    "compactStorageRequested": bool(args.compact_storage),
                }
            else:
                result = prune_dataset_version(
                    dsn,
                    args.dataset_version,
                    compact_storage=bool(args.compact_storage),
                )
                write_report(args.report, result)
        else:
            raise AssertionError(args.command)
    print(json.dumps(result, ensure_ascii=True, sort_keys=True, default=_json_default))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, sqlite3.Error, ValueError, CompactPublishError) as error:
        raise SystemExit(f"compact publish failed: {type(error).__name__}: {error}") from error
