import gzip
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import export_compact_dashboard_supabase as exporter


def _schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        CREATE TABLE serving_molit_completed_partitions(
          deal_month TEXT,district_code TEXT,coverage_status TEXT
        );
        CREATE TABLE serving_molit_current_transactions(
          api_payload_sha256 TEXT,district_code TEXT,district_name TEXT,locality TEXT,
          building_use TEXT,building_area_text TEXT,deal_amount_text TEXT,
          deal_year TEXT,deal_month_number TEXT,deal_day TEXT,api_payload_json TEXT
        );
        """
    )
    connection.row_factory = sqlite3.Row


def _coverage(connection: sqlite3.Connection, *months: str) -> None:
    connection.executemany(
        "INSERT INTO serving_molit_completed_partitions VALUES(?,?,?)",
        [
            (month, district, "COMPLETE_FULL_SNAPSHOT")
            for month in months
            for district in exporter.EXPECTED_SEOUL_DISTRICT_CODES
        ],
    )


def _transaction(
    connection: sqlite3.Connection,
    identity: str,
    *,
    month: str,
    day: str,
    area: str,
    amount: str,
    building_use: str = " 업무시설 ",
    building_type: str | None = "일반",
    jibun: str | None = "1**-2",
) -> None:
    year, month_number = month.split("-")
    connection.execute(
        "INSERT INTO serving_molit_current_transactions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            identity,
            "11110",
            "종로구",
            "청진동",
            building_use,
            area,
            amount,
            year,
            month_number,
            day,
            json.dumps({"buildingType": building_type, "jibun": jibun}, ensure_ascii=False),
        ),
    )


def _fixture_connection(path: Path | None = None) -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:" if path is None else path)
    _schema(connection)
    _coverage(connection, "2026-07", "2026-08")
    _transaction(connection, "a" * 64, month="2026-07", day="12", area="20000", amount="100,000")
    _transaction(connection, "a" * 64, month="2026-07", day="12", area="20000", amount="100,000")
    _transaction(connection, "b" * 64, month="2026-07", day="8", area="5000", amount="50,000")
    _transaction(connection, "c" * 64, month="2026-08", day="1", area="4000", amount="1,000")
    connection.commit()
    return connection


def _trend() -> list[dict[str, object]]:
    return [
        {
            "period": "2026-07",
            "transactionCount": 2,
            "amountKrw": "1500000000",
            "areaM2": "25000",
        },
        {
            "period": "2026-08",
            "transactionCount": 1,
            "amountKrw": "10000000",
            "areaM2": "4000",
        },
    ]


def test_large_transaction_envelope_is_bounded_deduplicated_and_zero_honest() -> None:
    connection = _fixture_connection()
    envelope = exporter.build_large_transactions(
        connection,
        _trend(),
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )

    assert envelope["contractVersion"] == 1
    assert envelope["minAreaPyeong"] == 5000
    assert envelope["pageSize"] == 20
    july, august = envelope["months"]
    assert (july["baseTransactionCount"], july["totalCount"]) == (2, 1)
    assert [page["page"] for page in july["pages"]] == [1]
    assert july["pages"][0]["rows"] == [
        {
            "id": "a" * 64,
            "dealDate": "2026-07-12",
            "address": "종로구 청진동 1**-2",
            "buildingUse": " 업무시설 ",
            "buildingType": "일반",
            "areaM2": 20000.0,
            "areaPyeong": 6050.0,
            "amountKrw": "1000000000",
        }
    ]
    assert (august["baseTransactionCount"], august["totalCount"], august["pages"]) == (1, 0, [])
    stats = exporter.large_transactions_stats(envelope)
    assert stats["totalCount"] == 1
    assert stats["serializedUtf8Bytes"] <= stats["maximumUtf8Bytes"]


def test_large_transaction_filter_matches_sql_text_boundaries_and_rejects_stale_totals() -> None:
    connection = sqlite3.connect(":memory:")
    _schema(connection)
    _coverage(connection, "2026-07")
    _transaction(connection, "a" * 64, month="2026-07", day="1", area="20000", amount="100,000")
    _transaction(connection, "b" * 64, month="2026-07", day="001", area="20000", amount="100,000")
    _transaction(connection, "c" * 64, month="2026-07", day="2", area=" 20000", amount="100,000")
    _transaction(connection, "d" * 64, month="2026-07", day="3", area="20000", amount="100,000 ")
    connection.execute(
        "UPDATE serving_molit_current_transactions SET deal_month_number='007' WHERE api_payload_sha256=?",
        ("b" * 64,),
    )
    connection.commit()
    trend = [{"period": "2026-07", "transactionCount": 1, "amountKrw": "1000000000", "areaM2": "20000"}]

    envelope = exporter.build_large_transactions(
        connection, trend, now=datetime(2026, 9, 10, tzinfo=timezone.utc)
    )
    assert envelope["months"][0]["totalCount"] == 1
    with pytest.raises(exporter.CompactExportError, match="base count differs"):
        exporter.build_large_transactions(
            connection,
            [{**trend[0], "transactionCount": 2}],
            now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )


def test_large_transaction_export_rejects_current_month_and_incomplete_coverage() -> None:
    connection = _fixture_connection()
    with pytest.raises(exporter.CompactExportError, match="Current or future"):
        exporter.build_large_transactions(
            connection,
            [{"period": "2026-09", "transactionCount": 0, "amountKrw": "0", "areaM2": "0"}],
            now=datetime(2026, 9, 10, tzinfo=timezone.utc),
        )
    connection.execute(
        "DELETE FROM serving_molit_completed_partitions WHERE deal_month='2026-08' AND district_code='11740'"
    )
    with pytest.raises(exporter.CompactExportError, match="not a complete 25-district"):
        exporter.build_large_transactions(
            connection, _trend(), now=datetime(2026, 9, 10, tzinfo=timezone.utc)
        )


def _base_package(path: Path, trend: list[dict[str, object]]) -> tuple[Path, dict[str, object]]:
    path.mkdir()
    builders = [name for name, _builder in exporter.TABLE_BUILDERS]
    tables: dict[str, dict[str, object]] = {}
    for table in (*builders, "market_pulse"):
        rows = (
            [{
                "as_of_period": "2026-08-01",
                "payload": {"generatedAt": "2026-09-10T00:00:00Z", "asOfPeriod": "2026-08", "trend": trend},
                "source_content_sha256": "9" * 64,
                "generated_at": "2026-09-10T00:00:00Z",
            }]
            if table == "market_pulse"
            else [{"fixture": table}]
        )
        tables[table] = exporter._table_stats(
            table, rows, destination=path / f"{table}.jsonl.gz"
        )
    row_counts = {name: int(value["rowCount"]) for name, value in sorted(tables.items())}
    table_hashes = {name: value["contentSha256"] for name, value in sorted(tables.items())}
    stable_hashes = {name: value["stableContentSha256"] for name, value in sorted(tables.items())}
    lineage = [{
        "dataset_code": "MOLIT_TRANSACTIONS",
        "source_code": "MOLIT_REAL_TRANSACTION",
        "source_as_of_date": "2026-09-08",
        "generated_at": "2026-09-08T00:00:00Z",
        "source_status_code": "READY",
        "source_row_count": 3,
        "serving_row_count": 3,
        "source_content_sha256": "8" * 64,
        "metadata": {},
    }]
    facets = {"marketPulse": {"asOfPeriod": "2026-08"}}
    identity = {
        "schemaVersion": exporter.SCHEMA_VERSION,
        "identityVersion": 2,
        "lineage": [exporter.content_identity_lineage(row) for row in lineage],
        "tableHashes": stable_hashes,
        "rowCounts": row_counts,
        "facets": facets,
        "marketPulseQuerySha256": "7" * 64,
    }
    source_hash = exporter.sha256_json(identity)
    manifest: dict[str, object] = {
        "packageVersion": exporter.PACKAGE_VERSION,
        "schemaVersion": exporter.SCHEMA_VERSION,
        "datasetVersion": f"cre-20260910T000000Z-{source_hash[:12]}",
        "sourceManifestSha256": source_hash,
        "sourceAsOfAt": "2026-09-10T00:00:00Z",
        "contentAsOfDate": "2026-09-10",
        "source": {"path": "fixture"},
        "marketPulseQuerySha256": "7" * 64,
        "tables": tables,
        "rowCounts": row_counts,
        "tableHashes": table_hashes,
        "stableTableHashes": stable_hashes,
        "lineage": lineage,
        "facets": facets,
        "packageBytes": sum(int(value["compressedBytes"]) for value in tables.values()),
        "estimatedUploadBytes": sum(int(value["uncompressedBytes"]) for value in tables.values()),
    }
    (path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return path, manifest


def test_delta_manifest_preserves_eight_tables_and_changes_only_market_pulse(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    connection = _fixture_connection(source)
    connection.close()
    base_path, base = _base_package(tmp_path / "base", _trend())

    manifest = exporter.build_large_transactions_delta_manifest(
        source,
        base_path,
        now=datetime(2026, 9, 10, tzinfo=timezone.utc),
    )

    assert manifest["delta"] == {
        "baseDatasetVersion": base["datasetVersion"],
        "baseSourceManifestSha256": base["sourceManifestSha256"],
        "changedTables": ["market_pulse"],
        "requiredServerCloneTables": [name for name, _builder in exporter.TABLE_BUILDERS],
    }
    for table in manifest["delta"]["requiredServerCloneTables"]:
        assert manifest["tableHashes"][table] == base["tableHashes"][table]
        assert manifest["rowCounts"][table] == base["rowCounts"][table]
    assert manifest["tableHashes"]["market_pulse"] != base["tableHashes"]["market_pulse"]
    assert manifest["largeTransactions"]["monthCount"] == 2
    assert manifest["largeTransactions"]["totalCount"] == 1
    assert manifest["estimatedClientUploadBytes"] == manifest["tables"]["market_pulse"]["uncompressedBytes"]
    assert manifest["datasetVersion"].endswith(f"-{manifest['sourceManifestSha256'][:12]}")


def test_delta_export_copies_non_market_files_byte_for_byte(tmp_path: Path) -> None:
    source = tmp_path / "market.db"
    connection = _fixture_connection(source)
    connection.close()
    base_path, base = _base_package(tmp_path / "base", _trend())

    package, manifest = exporter.export_large_transactions_delta(
        source, base_path, tmp_path / "output"
    )

    for table in manifest["delta"]["requiredServerCloneTables"]:
        filename = base["tables"][table]["file"]
        assert (package / filename).read_bytes() == (base_path / filename).read_bytes()
    with gzip.open(package / "market_pulse.jsonl.gz", "rt", encoding="utf-8") as handle:
        row = json.loads(handle.readline())
    assert row["payload"]["largeTransactions"]["months"][0]["totalCount"] == 1
    assert row["payload"]["largeTransactions"]["months"][1]["pages"] == []
