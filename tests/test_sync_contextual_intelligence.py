from datetime import datetime, timezone

from scripts.sync_contextual_intelligence import SYNC_TABLES, canonical_rows_hash, upsert_sql


def test_contextual_sync_order_is_fk_safe_and_additive() -> None:
    assert SYNC_TABLES.index("contextual_processing_campaigns") < SYNC_TABLES.index("contextual_document_runs")
    assert SYNC_TABLES.index("contextual_document_runs") < SYNC_TABLES.index("contextual_event_frames")
    assert SYNC_TABLES.index("contextual_event_frames") < SYNC_TABLES.index("contextual_search_records")

    sql = upsert_sql(
        "contextual_search_records",
        ["search_record_id", "record_mode", "metadata_json"],
        ["search_record_id"],
    )
    assert "INSERT INTO market_intelligence.contextual_search_records" in sql
    assert "ON CONFLICT (search_record_id) DO UPDATE" in sql
    assert "DELETE" not in sql.upper()
    assert "TRUNCATE" not in sql.upper()


def test_canonical_row_hash_normalizes_json_boolean_and_utc_precision() -> None:
    columns = ["rule_scope_json", "is_active", "approved_at"]
    local = [('{"b":2,"a":1}', 1, "2026-09-03T03:26:22.566+00:00")]
    remote = [({"a": 1, "b": 2}, True, datetime(2026, 9, 3, 3, 26, 22, 566000, tzinfo=timezone.utc))]
    assert canonical_rows_hash("contextual_rules", columns, local) == canonical_rows_hash(
        "contextual_rules", columns, remote
    )
