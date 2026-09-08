#!/usr/bin/env python
"""Content-aware, append-safe publication of narrowly scoped serving datasets.

Dry-run is the default.  The Turso adapter is imported only after all pause
gates pass, so a quota pause never opens a remote connection or reads secrets.
"""
from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Mapping, Protocol, Sequence

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ENV = Path(r"C:\10137_WorkSpace\env\.env.personal.txt")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SECRET_KEYS = frozenset({"TURSO_DATABASE_URL", "TURSO_AUTH_TOKEN"})


@dataclass(frozen=True)
class TableSelection:
    name: str
    where: str = ""


DATASETS: dict[str, tuple[TableSelection, ...]] = {
    "DAILY_ARTICLES": (
        TableSelection("serving_daily_article_dates"),
        TableSelection("serving_daily_articles"),
        TableSelection("serving_daily_article_topics"),
        TableSelection("serving_daily_article_details"),
    ),
    "FINANCIAL_MACRO": (
        TableSelection("macro_series"),
        TableSelection("financial_macro_monthly_serving"),
    ),
    "MOLIT_TRANSACTIONS": (
        TableSelection("serving_molit_completed_partitions"),
        TableSelection("serving_molit_current_transactions"),
    ),
    "SEOUL_BUILDING_PERMITS": (
        TableSelection("serving_v2_building_permit_monthly"),
    ),
}
ALLOWED_DATA_TABLES = frozenset(item.name for items in DATASETS.values() for item in items)
METADATA_TABLES = frozenset({"serving_dataset_freshness", "serving_row_fingerprints"})
DERIVED_TABLES = frozenset({
    "serving_daily_article_dates", "serving_daily_articles",
    "serving_daily_article_topics", "serving_daily_article_details",
    "financial_macro_monthly_serving",
    "serving_v2_building_permit_monthly",
    "serving_molit_completed_partitions", "serving_molit_current_transactions",
})


class Remote(Protocol):
    def execute(self, sql: str, args: Sequence[Any] | None = None) -> Any: ...
    def commit(self) -> Any: ...


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def quote_ident(value: str) -> str:
    if not IDENT.fullmatch(value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return f'"{value}"'


def normalize(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite floats cannot be published")
        return {"$float": format(value, ".17g")}
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"$bytes": base64.b64encode(bytes(value)).decode("ascii")}
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _columns_and_pk(conn: sqlite3.Connection, table: str) -> tuple[list[str], list[str]]:
    rows = conn.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    if not rows:
        raise RuntimeError(f"required serving table is absent: {table}")
    columns = [str(row[1]) for row in rows]
    pk = [str(row[1]) for row in sorted((row for row in rows if int(row[5])), key=lambda row: int(row[5]))]
    if not pk:
        raise RuntimeError(f"serving table has no primary key: {table}")
    return columns, pk


def _row_key(table: str, row: Mapping[str, Any], pk: Sequence[str]) -> str:
    if table == "serving_molit_completed_partitions":
        return canonical_json({
            "dealMonth": normalize(row["deal_month"]),
            "districtCode": normalize(row["district_code"]),
        })
    if table == "serving_molit_current_transactions":
        return str(row["transaction_key_json"])
    return canonical_json({column: normalize(row[column]) for column in pk})


def _row_hash(row: Mapping[str, Any], columns: Sequence[str]) -> str:
    return sha256_json({column: normalize(row[column]) for column in columns})


def snapshot_dataset(conn: sqlite3.Connection, dataset_code: str) -> dict[str, Any]:
    if dataset_code not in DATASETS:
        raise ValueError(f"unknown dataset: {dataset_code}")
    conn.row_factory = sqlite3.Row
    freshness = conn.execute(
        """SELECT source_as_of_date,source_status_code,source_row_count,
                  serving_row_count,content_sha256,metadata_json
           FROM serving_dataset_freshness WHERE dataset_code=?""",
        (dataset_code,),
    ).fetchone()
    if not freshness or str(freshness[1]) != "READY":
        raise RuntimeError(f"validated local freshness metadata is absent: {dataset_code}")
    local_fingerprints = {
        (str(row[0]), str(row[1])): str(row[2])
        for row in conn.execute(
            """SELECT table_name,row_key_json,content_sha256
               FROM serving_row_fingerprints
               WHERE dataset_code=? AND state_code='ACTIVE'""",
            (dataset_code,),
        )
    }
    tables: dict[str, Any] = {}
    digest_rows: list[tuple[str, str, str]] = []
    as_of_values: list[str] = []
    for selection in DATASETS[dataset_code]:
        if selection.name not in ALLOWED_DATA_TABLES:
            raise RuntimeError("table is outside the serving publication allowlist")
        columns, pk = _columns_and_pk(conn, selection.name)
        sql = f"SELECT {','.join(quote_ident(c) for c in columns)} FROM {quote_ident(selection.name)}"
        if selection.where:
            sql += " WHERE " + selection.where
        rows: dict[str, dict[str, Any]] = {}
        for raw in conn.execute(sql):
            row = {column: raw[column] for column in columns}
            key = _row_key(selection.name, row, pk)
            fingerprint = local_fingerprints.get((selection.name, key))
            if fingerprint is None:
                raise RuntimeError(f"validated local row fingerprint is absent: {selection.name}")
            if key in rows:
                raise RuntimeError(f"duplicate primary key in {selection.name}")
            rows[key] = {"values": tuple(row[c] for c in columns), "hash": fingerprint}
            digest_rows.append((selection.name, key, fingerprint))
            for candidate in ("source_as_of_date", "source_vintage_at", "published_at", "article_date", "event_month"):
                if candidate in row and row[candidate] is not None:
                    as_of_values.append(str(row[candidate]))
        tables[selection.name] = {"columns": columns, "pk": pk, "rows": rows}
    selected_names = {selection.name for selection in DATASETS[dataset_code]}
    selected_fingerprints = {key for key in local_fingerprints if key[0] in selected_names}
    actual_keys = {(table, key) for table, info in tables.items() for key in info["rows"]}
    if selected_fingerprints != actual_keys:
        raise RuntimeError("local serving rows and active fingerprints are not at parity")
    digest_rows.sort()
    return {
        "datasetCode": dataset_code,
        "tables": tables,
        "rowCount": len(digest_rows),
        "contentSha256": str(freshness[4]),
        "sourceAsOfDate": str(freshness[0]),
        "sourceRowCount": int(freshness[2]),
        "servingRowCount": int(freshness[3]),
        "localMetadataJson": str(freshness[5]),
    }


def _rows(result: Any) -> list[Any]:
    return list(getattr(result, "rows", result.fetchall() if hasattr(result, "fetchall") else []))


def _commit(remote: Any) -> None:
    commit = getattr(remote, "commit", None)
    if callable(commit):
        commit()


def _delete_derived_row(remote: Remote, table: str, pk: Sequence[str], row_key_json: str) -> None:
    if table not in DERIVED_TABLES:
        raise RuntimeError("raw and provenance rows are append-only")
    if table == "serving_molit_completed_partitions":
        values = json.loads(row_key_json)
        remote.execute(
            "DELETE FROM serving_molit_completed_partitions WHERE district_code=? AND deal_month=?",
            [values["districtCode"], values["dealMonth"]],
        )
        return
    if table == "serving_molit_current_transactions":
        remote.execute(
            "DELETE FROM serving_molit_current_transactions WHERE transaction_key=?",
            [hashlib.sha256(row_key_json.encode("utf-8")).hexdigest()],
        )
        return
    values = json.loads(row_key_json)
    if set(values) != set(pk):
        raise RuntimeError("retirement key does not match table primary key")
    sql = f"DELETE FROM {quote_ident(table)} WHERE " + " AND ".join(f"{quote_ident(key)}=?" for key in pk)
    remote.execute(sql, [values[key] for key in pk])


def approved_bootstrap_statements(path: Path) -> list[str]:
    script = path.read_text(encoding="utf-8")
    lowered = script.lower()
    if any(token in lowered for token in ("dashboard_access_", " drop ", "delete from", "alter table")):
        raise RuntimeError("serving bootstrap is not additive or touches security scope")
    statements: list[str] = []
    buffer = ""
    for line in script.splitlines():
        if line.lstrip().startswith("--"):
            continue
        buffer += line + "\n"
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                lead = statement.lower().lstrip()
                approved_schema_marker = (
                    lead.startswith("insert into schema_meta")
                    and any(marker in lead for marker in (
                        "dashboard_serving_schema_version",
                        "molit_current_serving_schema_version",
                    ))
                    and "on conflict(schema_key) do update" in lead
                )
                if not (lead.startswith("create table if not exists") or lead.startswith("create index if not exists") or approved_schema_marker):
                    raise RuntimeError("serving bootstrap contains an unapproved statement")
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise RuntimeError("serving bootstrap SQL is incomplete")
    return statements


def apply_remote_serving_bootstrap(remote: Remote, path: Path | None = None) -> int:
    paths = [path] if path is not None else [
        ROOT / "db" / "turso" / "migrations" / "002_dashboard_serving.sql",
        ROOT / "db" / "turso" / "migrations" / "003_molit_current_serving.sql",
    ]
    count = 0
    for migration in paths:
        for statement in approved_bootstrap_statements(migration):
            remote.execute(statement)
            count += 1
    return count


def _multi_upsert(remote: Remote, table: str, columns: Sequence[str], pk: Sequence[str], values: list[Sequence[Any]]) -> None:
    if not values:
        return
    cols = ",".join(quote_ident(c) for c in columns)
    group = "(" + ",".join("?" for _ in columns) + ")"
    updates = [c for c in columns if c not in pk]
    conflict = ",".join(quote_ident(c) for c in pk)
    action = "DO NOTHING" if not updates else "DO UPDATE SET " + ",".join(
        f"{quote_ident(c)}=excluded.{quote_ident(c)}" for c in updates
    )
    sql = f"INSERT INTO {quote_ident(table)} ({cols}) VALUES {','.join(group for _ in values)} ON CONFLICT ({conflict}) {action}"
    remote.execute(sql, [item for row in values for item in row])


def _read_remote_fingerprints(remote: Remote, dataset_code: str) -> dict[tuple[str, str], tuple[str, str]]:
    result = remote.execute(
        "SELECT table_name,row_key_json,content_sha256,state_code FROM serving_row_fingerprints WHERE dataset_code=?",
        [dataset_code],
    )
    return {(str(r[0]), str(r[1])): (str(r[2]), str(r[3])) for r in _rows(result)}


def _freshness_values(
    snapshot: Mapping[str, Any], *, source_code: str, generated_at: str
) -> tuple[Any, ...]:
    metadata_value = json.loads(str(snapshot.get("localMetadataJson", "{}")))
    if not isinstance(metadata_value, dict):
        raise RuntimeError("local freshness metadata must be an object")
    metadata_value.update({
        "publishedTables": {
            name: len(info["rows"]) for name, info in snapshot["tables"].items()
        },
        "publisherVersion": "content-aware-v1",
    })
    return (
        snapshot["datasetCode"], source_code, snapshot["sourceAsOfDate"],
        generated_at, "READY",
        int(snapshot.get("sourceRowCount", snapshot["rowCount"])),
        int(snapshot.get("servingRowCount", snapshot["rowCount"])),
        snapshot["contentSha256"], canonical_json(metadata_value),
    )


def _upsert_freshness_only(
    remote: Remote, snapshot: Mapping[str, Any], *, source_code: str,
    generated_at: str,
) -> None:
    _multi_upsert(
        remote,
        "serving_dataset_freshness",
        (
            "dataset_code", "source_code", "source_as_of_date", "generated_at",
            "source_status_code", "source_row_count", "serving_row_count",
            "content_sha256", "metadata_json",
        ),
        ("dataset_code",),
        [_freshness_values(snapshot, source_code=source_code, generated_at=generated_at)],
    )


def publish_snapshot(remote: Remote, snapshot: Mapping[str, Any], *, source_code: str, batch_rows: int = 100) -> dict[str, Any]:
    dataset = str(snapshot["datasetCode"])
    current = _rows(remote.execute(
        "SELECT content_sha256,serving_row_count FROM serving_dataset_freshness WHERE dataset_code=?",
        [dataset],
    ))
    generated_at = utc_now()
    if current and str(current[0][0]) == snapshot["contentSha256"]:
        # A newer source snapshot can be byte-identical to the prior release.
        # Advance only governed clocks/metadata, without a fingerprint scan or
        # any serving-row rewrite.
        _upsert_freshness_only(
            remote, snapshot, source_code=source_code, generated_at=generated_at,
        )
        return {
            "status": "UNCHANGED", "datasetCode": dataset, "changedRows": 0,
            "metadataUpdated": True, "remotePending": False,
        }

    remote_fingerprints = _read_remote_fingerprints(remote, dataset)
    local_keys: set[tuple[str, str]] = set()
    changes: list[tuple[str, str, Mapping[str, Any]]] = []
    for table, info in snapshot["tables"].items():
        if table not in ALLOWED_DATA_TABLES:
            raise RuntimeError("refusing non-serving table publication")
        for key, row in info["rows"].items():
            compound = (table, key)
            local_keys.add(compound)
            if remote_fingerprints.get(compound) != (row["hash"], "ACTIVE"):
                changes.append((table, key, row))
    stale = {key for key, value in remote_fingerprints.items() if value[1] == "ACTIVE" and key not in local_keys}
    raw_stale = {key for key in stale if key[0] not in DERIVED_TABLES}
    if raw_stale:
        raise RuntimeError("remote raw/provenance rows cannot be retired by serving publisher")

    for table, info in snapshot["tables"].items():
        changed = [(key, row) for changed_table, key, row in changes if changed_table == table]
        for offset in range(0, len(changed), batch_rows):
            part = changed[offset : offset + batch_rows]
            _multi_upsert(remote, table, info["columns"], info["pk"], [row["values"] for _, row in part])
            fingerprint_values = [
                (dataset, table, key, row["hash"], "ACTIVE", generated_at) for key, row in part
            ]
            _multi_upsert(
                remote,
                "serving_row_fingerprints",
                ("dataset_code", "table_name", "row_key_json", "content_sha256", "state_code", "updated_at"),
                ("dataset_code", "table_name", "row_key_json"),
                fingerprint_values,
            )
    # Exact-key removal is allowed only for pipeline-owned derived serving rows.
    # Raw history and security tables can never reach this path.
    ordered_tables = [selection.name for selection in DATASETS[dataset] if selection.name in snapshot["tables"]]
    for table in reversed(ordered_tables):
        info = snapshot["tables"][table]
        for stale_table, key in sorted(stale):
            if stale_table != table:
                continue
            _delete_derived_row(remote, table, info["pk"], key)
            remote.execute(
                """UPDATE serving_row_fingerprints SET state_code='RETIRED',updated_at=?
                   WHERE dataset_code=? AND table_name=? AND row_key_json=?""",
                [generated_at, dataset, table, key],
            )

    # Fingerprint readback is deliberately limited to rows affected in this run.
    for table, key, row in changes:
        found = _rows(remote.execute(
            "SELECT content_sha256,state_code FROM serving_row_fingerprints WHERE dataset_code=? AND table_name=? AND row_key_json=?",
            [dataset, table, key],
        ))
        if not found or (str(found[0][0]), str(found[0][1])) != (row["hash"], "ACTIVE"):
            raise RuntimeError("affected-row fingerprint readback failed")

    _upsert_freshness_only(
        remote, snapshot, source_code=source_code, generated_at=generated_at,
    )
    return {"status": "PUBLISHED", "datasetCode": dataset, "changedRows": len(changes), "retiredRows": len(stale), "rowCount": snapshot["rowCount"], "remotePending": False}


def load_credentials(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in SECRET_KEYS:
            values[key] = value.strip().strip("\"'")
    if set(values) != SECRET_KEYS or not all(values.values()):
        raise RuntimeError("required Turso credentials are unavailable")
    return values


def publish_turso(db: Path, dataset_code: str, env_file: Path, *, apply: bool, blocked_until: date | None, source_code: str, batch_rows: int = 100, bootstrap: bool = False) -> dict[str, Any]:
    if blocked_until and date.today() < blocked_until:
        return {"status": "PUBLISH_DEFERRED", "reason": "QUOTA_READS", "blockedUntil": blocked_until.isoformat(), "remoteAttempted": False, "remotePending": True}
    with sqlite3.connect(f"file:{db.resolve().as_posix()}?mode=ro", uri=True) as conn:
        snapshot = snapshot_dataset(conn, dataset_code)
    if not apply:
        return {"status": "REHEARSED", "datasetCode": dataset_code, "rowCount": snapshot["rowCount"], "contentSha256": snapshot["contentSha256"], "remoteAttempted": False, "remotePending": True}
    credentials = load_credentials(env_file)
    from libsql_client import create_client_sync
    client = create_client_sync(credentials["TURSO_DATABASE_URL"], auth_token=credentials["TURSO_AUTH_TOKEN"])
    try:
        bootstrap_count = 0
        if bootstrap:
            bootstrap_transaction = client.transaction()
            try:
                bootstrap_count = apply_remote_serving_bootstrap(bootstrap_transaction)
                bootstrap_transaction.commit()
            except Exception:
                bootstrap_transaction.rollback()
                raise
        transaction = client.transaction()
        try:
            result = publish_snapshot(transaction, snapshot, source_code=source_code, batch_rows=batch_rows)
            transaction.commit()
            result["bootstrapStatements"] = bootstrap_count
            return result
        except Exception:
            transaction.rollback()
            raise
    finally:
        client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dataset", choices=sorted(DATASETS), required=True)
    parser.add_argument("--source-code", required=True)
    parser.add_argument("--env-file", type=Path, default=DEFAULT_ENV)
    parser.add_argument("--blocked-until", type=date.fromisoformat)
    parser.add_argument("--batch-rows", type=int, default=100)
    parser.add_argument("--bootstrap", action="store_true", help="Apply approved additive serving DDL before first publication")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.batch_rows < 1:
        parser.error("--batch-rows must be positive")
    try:
        result = publish_turso(args.db, args.dataset, args.env_file, apply=args.apply, blocked_until=args.blocked_until, source_code=args.source_code, batch_rows=args.batch_rows, bootstrap=args.bootstrap)
    except Exception as exc:
        # Never surface provider exceptions: URLs and tokens can be embedded in
        # transport messages. The orchestrator retains only a stable type code.
        result = {"status": "PUBLISH_FAILED", "errorCode": type(exc).__name__, "remotePending": True}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
