from pathlib import Path
import sqlite3

import pytest

ROOT = Path(__file__).parents[1]
SQLITE_MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.3.0_classification_taxonomy.sqlite.sql"
POSTGRES_MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.3.0_classification_taxonomy.sql"
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def migrated_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY, schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.2.0');
    """)
    conn.executescript(SQLITE_MIGRATION.read_text(encoding="utf-8"))
    return conn


def test_migrations_are_additive_version_gated_and_portable() -> None:
    sqlite_sql = SQLITE_MIGRATION.read_text(encoding="utf-8")
    postgres_sql = POSTGRES_MIGRATION.read_text(encoding="utf-8")
    assert "value='3.2.0'" in sqlite_sql
    assert "Expected schema 3.2.0" in postgres_sql
    for name in ("classification_schemes", "classification_terms", "record_classifications"):
        assert f"CREATE TABLE {name}" in sqlite_sql
        assert f"CREATE TABLE market_intelligence.{name}" in postgres_sql
    assert "DROP TABLE source_documents" not in sqlite_sql
    assert "DELETE FROM market_intelligence.source_documents" not in postgres_sql
    assert "schema_value='3.3.0'" in sqlite_sql
    assert "schema_value = '3.3.0'" in postgres_sql


def test_hierarchy_primary_and_lineage_constraints() -> None:
    conn = migrated_connection()
    try:
        assert conn.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0] == "3.3.0"
        schemes = {r[0] for r in conn.execute("select scheme_code from classification_schemes")}
        assert {"MARKET_CATEGORY", "DOCUMENT_PURPOSE", "ASSET_CLASS", "ORGANIZATION_TYPE", "INVESTMENT_STRATEGY"} <= schemes
        sale = conn.execute("""select t.classification_term_id,s.classification_scheme_id
          from classification_terms t join classification_schemes s using(classification_scheme_id)
          where s.scheme_code='MARKET_CATEGORY' and t.term_code='SALE'""").fetchone()
        assert sale
        term_id, scheme_id = sale
        row = ("rc-1", "EVENT", "event-1", scheme_id, term_id, "LEGACY_BACKFILL", 1, 1.0,
               "EVENT_CATEGORY_V1", "DIRECT_STRUCTURED", "APPROVED", "2026-08-21T00:00:00Z", "{}", "{}")
        conn.execute("""insert into record_classifications(
          record_classification_id,target_kind,target_id,classification_scheme_id,classification_term_id,
          assignment_role,is_primary,confidence,classifier_version,evidence_status,review_status,assigned_at,
          lineage_json,metadata_json) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", row)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""insert into record_classifications(
              record_classification_id,target_kind,target_id,classification_scheme_id,classification_term_id,
              assignment_role,is_primary,confidence,classifier_version,evidence_status,review_status,assigned_at,
              lineage_json,metadata_json) values('rc-2','EVENT','event-1',?,?, 'MANUAL',1,.9,
              'MANUAL_V1','MANUAL_REVIEWED','APPROVED','2026-08-21T00:00:00Z','{}','{}')""", (scheme_id, term_id))
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("""insert into record_classifications(
              record_classification_id,target_kind,target_id,classification_scheme_id,classification_term_id,
              assignment_role,is_primary,confidence,classifier_version,evidence_status,review_status,assigned_at,
              lineage_json,metadata_json) values('rc-3','EVENT','event-2',?,?, 'MANUAL',0,1.2,
              'MANUAL_V1','MANUAL_REVIEWED','APPROVED','2026-08-21T00:00:00Z','{}','{}')""", (scheme_id, term_id))
        summary = conn.execute("select primary_market_category_code from v_record_classification_summary where target_kind='EVENT' and target_id='event-1'").fetchone()
        assert summary == ("SALE",)
    finally:
        conn.close()


def test_fresh_schema_contains_classification_contract() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE classification_schemes" in sql
    assert "CREATE TABLE classification_terms" in sql
    assert "CREATE TABLE record_classifications" in sql
    assert "CREATE VIEW v_record_classification_summary" in sql
    assert "('schema_version', '3.5.0')" in sql
