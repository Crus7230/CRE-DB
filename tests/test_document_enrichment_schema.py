from pathlib import Path
import sqlite3

ROOT = Path(__file__).parents[1]
SCHEMA = ROOT / "db" / "v2" / "schema.sql"


def test_v28_document_enrichment_schema_is_version_bound_and_valid():
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(SCHEMA.read_text(encoding="utf-8"))
    version = connection.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
    ).fetchone()[0]
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(document_enrichments)")
    }
    assert version == "3.5.0"
    assert {
        "document_version_id", "pipeline_version", "summary_text", "safe_excerpt",
        "source_content_sha256", "review_status", "status_code",
    } <= columns
    foreign_keys = connection.execute("PRAGMA foreign_key_list(document_enrichments)").fetchall()
    assert any(row[2] == "document_versions" for row in foreign_keys)
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    connection.close()
