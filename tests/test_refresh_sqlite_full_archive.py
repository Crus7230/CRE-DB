import pytest

from scripts.refresh_sqlite_sub_from_supabase import (
    ensure_full_refresh_allowed,
    ensure_replica_schema_allowed,
    validate_table_coverage,
)


def test_replica_refresh_rejects_missing_application_tables() -> None:
    with pytest.raises(RuntimeError, match="missing Supabase application tables"):
        validate_table_coverage(
            sqlite_tables={"source_documents", "document_versions"},
            postgres_tables={"source_documents", "document_versions", "document_scope_assessments", "_migration_meta"},
        )


def test_replica_refresh_ignores_only_migration_bookkeeping_table() -> None:
    validate_table_coverage(
        sqlite_tables={"source_documents", "document_versions"},
        postgres_tables={"source_documents", "document_versions", "_migration_meta"},
    )


def test_overwrite_refresh_is_blocked_after_active_serving_cutover() -> None:
    with pytest.raises(RuntimeError, match="merge_supabase_active_into_full_archive"):
        ensure_full_refresh_allowed(current_archive_snapshots=1)
    ensure_full_refresh_allowed(current_archive_snapshots=0)


@pytest.mark.parametrize("schema", ["app_security", "APP_SECURITY", " app_security "])
def test_access_control_schema_is_never_copied_to_sqlite(schema: str) -> None:
    with pytest.raises(SystemExit, match="access-control PII"):
        ensure_replica_schema_allowed(schema)

    ensure_replica_schema_allowed("market_intelligence")
