from pathlib import Path
import sqlite3

ROOT=Path(__file__).parents[1]
SQLITE=ROOT/"db/v2/migrations/3.5.0_model_interpretations.sqlite.sql"
POSTGRES=ROOT/"db/v2/migrations/3.5.0_model_interpretations.sql"
SCHEMA=ROOT/"db/v2/schema.sql"


def migrated() -> sqlite3.Connection:
    c=sqlite3.connect(":memory:"); c.execute("pragma foreign_keys=on")
    c.executescript("""
      CREATE TABLE schema_meta(schema_key TEXT PRIMARY KEY,schema_value TEXT NOT NULL);
      INSERT INTO schema_meta VALUES('schema_version','3.4.1');
      CREATE TABLE insight_signals(insight_signal_id TEXT PRIMARY KEY);
      CREATE TABLE insight_signal_evidence(insight_signal_evidence_id TEXT PRIMARY KEY,insight_signal_id TEXT NOT NULL REFERENCES insight_signals(insight_signal_id));
    """)
    c.executescript(SQLITE.read_text(encoding="utf-8")); return c


def test_model_migrations_are_additive_versioned_and_reviewable() -> None:
    sq=SQLITE.read_text(encoding="utf-8"); pg=POSTGRES.read_text(encoding="utf-8")
    assert "value='3.4.1'" in sq and "Expected schema 3.4.1" in pg
    for table in ("analytics_model_registry","analytics_model_runs","insight_interpretations","insight_interpretation_evidence"):
        assert f"CREATE TABLE {table}" in sq
        assert f"CREATE TABLE market_intelligence.{table}" in pg
    for provenance in ("model_version","embedding_version","prompt_version","prompt_hash","input_hash","output_hash"):
        assert provenance in sq and provenance in pg
    assert "APPROVED" in sq and "DRAFT" in sq
    assert "schema_value='3.5.0'" in sq and "schema_value = '3.5.0'" in pg


def test_constraints_prevent_unversioned_model_outputs_and_auto_approval() -> None:
    c=migrated()
    try:
        c.execute("insert into insight_signals values('s1')")
        with __import__('pytest').raises(sqlite3.IntegrityError):
            c.execute("insert into analytics_model_registry(model_registry_id,task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash,status_code,created_at) values('m1','TOPIC_INTERPRETATION','P','M','','E','V',?, 'DISABLED','2026')",('0'*64,))
        c.execute("insert into analytics_model_registry(model_registry_id,task_code,provider_code,model_name,model_version,embedding_version,prompt_version,prompt_hash,status_code,created_at) values('m1','TOPIC_INTERPRETATION','P','M','M1','E1','P1',?,'DISABLED','2026')",('0'*64,))
        c.execute("insert into analytics_model_runs(model_run_id,model_registry_id,status_code,input_count,output_count,started_at,metadata_json) values('r1','m1','COMPLETED',1,1,'2026','{}')")
        c.execute("insert into insight_interpretations(interpretation_id,insight_signal_id,model_registry_id,model_run_id,headline,narrative_text,input_hash,output_hash,generated_at) values('i1','s1','m1','r1','h','n',?,?, '2026')",('1'*64,'2'*64))
        assert c.execute("select interpretation_status from insight_interpretations").fetchone()[0] == "DRAFT"
        assert c.execute("select schema_value from schema_meta where schema_key='schema_version'").fetchone()[0] == "3.5.0"
    finally: c.close()


def test_fresh_schema_contains_model_boundary() -> None:
    sql=SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE analytics_model_registry" in sql
    assert "CREATE TABLE insight_interpretations" in sql
    assert "('schema_version', '3.5.0')" in sql
