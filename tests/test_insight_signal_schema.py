from pathlib import Path
import sqlite3
import pytest

ROOT = Path(__file__).parents[1]
SQLITE = ROOT / "db/v2/migrations/3.4.1_insight_signals.sqlite.sql"
POSTGRES = ROOT / "db/v2/migrations/3.4.1_insight_signals.sql"
SCHEMA = ROOT / "db/v2/schema.sql"


def migrated() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:"); c.execute("pragma foreign_keys=on")
    c.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.4.0');
      CREATE TABLE keyword_dictionary(keyword_id TEXT PRIMARY KEY);
      CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY);
    """)
    c.executescript(SQLITE.read_text(encoding="utf-8")); return c


def test_migrations_are_additive_version_gated_and_evidence_aware() -> None:
    sq = SQLITE.read_text(encoding="utf-8"); pg = POSTGRES.read_text(encoding="utf-8")
    assert "value='3.4.0'" in sq and "Expected schema 3.4.0" in pg
    for name in ("insight_signals", "insight_signal_evidence"):
        assert f"CREATE TABLE {name}" in sq
        assert f"CREATE TABLE market_intelligence.{name}" in pg
    assert "UNREVIEWED" in sq and "APPROVED" in sq
    assert "strength_score" in sq and "source_diversity_score" in sq
    assert "source_document_version_id" in sq
    assert "ix_insight_signals_keyword" in sq and "ix_insight_signals_keyword" in pg
    assert "schema_value='3.4.1'" in sq and "schema_value = '3.4.1'" in pg


def test_signal_status_confidence_and_evidence_constraints() -> None:
    c = migrated()
    try:
        columns = {row[1] for row in c.execute("pragma table_info('insight_signals')")}
        assert {"review_status", "confidence_score", "strength_score", "evidence_score", "source_diversity_score", "algorithm_version"} <= columns
        assert c.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0] == "3.4.1"
    finally: c.close()

def test_sqlite_migration_fails_closed_for_missing_version_and_normalizes_nullable_identity():
    setups = (
        "CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT);",
        "CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT); INSERT INTO schema_meta VALUES('schema_version','WRONG');",
    )
    for setup in setups:
        c = sqlite3.connect(":memory:")
        c.executescript(setup + " CREATE TABLE keyword_dictionary(keyword_id TEXT PRIMARY KEY); CREATE TABLE document_versions(document_version_id TEXT PRIMARY KEY);")
        try:
            with pytest.raises(sqlite3.IntegrityError):
                c.executescript(SQLITE.read_text(encoding="utf-8"))
        finally:
            c.close()

    c = migrated()
    row = ("s1", "VOLUME_ANOMALY", "2026-08-22", "t", "s", "UNREVIEWED", "LOW", None, .1, .1, .1, .1, "A", "t", "a", "b", "{}")
    c.execute("insert into insight_signals values(" + ",".join("?" * 17) + ")", row)
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("insert into insight_signals values(" + ",".join("?" * 17) + ")", ("s2",) + row[1:])
    c.close()


def test_fresh_schema_contains_signal_contract() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE insight_signals" in sql
    assert "CREATE TABLE insight_signal_evidence" in sql
    assert "CREATE INDEX ix_insight_signals_keyword" in sql
    assert "('schema_version', '3.5.0')" in sql
