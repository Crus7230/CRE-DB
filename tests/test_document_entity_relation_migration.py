from pathlib import Path

ROOT = Path(__file__).parents[1]
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.1.0_document_entity_relations.sql"
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def test_relation_projection_migration_is_version_gated_and_lineage_preserving() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "Expected schema 3.0.0" in sql
    assert "v_document_entity_relations" in sql
    assert "CANONICAL_EVENT" in sql
    assert "RESOLVED_MENTION" in sql
    assert "VERIFIED_CLAIM" in sql
    assert "SOURCE_CLAIM" in sql
    assert "resolution_status='RESOLVED'" in sql
    assert "selected=1" in sql
    assert "verification_status='VERIFIED'" in sql
    assert "review_status<>'REJECTED'" in sql
    assert "schema_value = '3.1.0'" in sql


def test_fresh_schema_contains_scope_and_relation_projection() -> None:
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE TABLE organization_scope_assessments" in sql
    assert "CREATE VIEW v_document_entity_relations" in sql
    assert "('schema_version', '3.5.0')" in sql
