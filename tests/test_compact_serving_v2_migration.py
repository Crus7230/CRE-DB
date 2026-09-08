from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.9.0_compact_serving_v2.sql"


def test_compact_serving_v2_migration_is_additive_and_release_scoped() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()

    assert "TRUNCATE" not in upper
    assert "DELETE FROM" not in upper
    assert "DROP TABLE" not in upper
    assert "CREATE TABLE IF NOT EXISTS MARKET_INTELLIGENCE.SERVING_RELEASES" in upper
    assert "CREATE TABLE IF NOT EXISTS MARKET_INTELLIGENCE.SERVING_ACTIVE_RELEASE" in upper
    assert "CREATE TABLE IF NOT EXISTS MARKET_INTELLIGENCE.SERVING_V2_BUILDING_PERMIT_MONTHLY" in upper
    assert "CREATE TABLE IF NOT EXISTS MARKET_INTELLIGENCE.SERVING_V2_BUILDING_PERMIT_HOT_DETAIL" in upper
    assert "REFERENCES MARKET_INTELLIGENCE.SERVING_RELEASES(RELEASE_ID) ON DELETE CASCADE" in upper
    assert "CREATE OR REPLACE VIEW MARKET_INTELLIGENCE.V_SERVING_V2_BUILDING_PERMIT_MONTHLY" in upper
    assert "CREATE OR REPLACE VIEW MARKET_INTELLIGENCE.V_SERVING_V2_BUILDING_PERMIT_HOT_DETAIL" in upper
    assert "SERVING_V2_SCHEMA_VERSION" in upper
