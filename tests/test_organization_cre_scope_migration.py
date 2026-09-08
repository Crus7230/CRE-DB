from pathlib import Path


MIGRATION = Path(__file__).parents[1] / "db" / "v2" / "migrations" / "3.0.0_organization_cre_scope.sql"


def test_organization_scope_migration_is_version_gated_and_version_bound() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "Expected schema 2.9.0" in sql
    assert "organization_scope_assessments" in sql
    assert "organization_id" in sql
    assert "classifier_version" in sql
    assert "CRE_CONFIRMED" in sql
    assert "CRE_CONTEXT_ONLY" in sql
    assert "CRE_REVIEW" in sql
    assert "schema_value = '3.0.0'" in sql
