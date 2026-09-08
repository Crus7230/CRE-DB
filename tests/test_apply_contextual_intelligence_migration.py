from __future__ import annotations

from pathlib import Path
import sqlite3
import sys


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.apply_contextual_intelligence_migration import (  # noqa: E402
    migration_body,
    sqlite_run,
)

SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"
POSTGRES = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sql"


def test_sqlite_fresh_baseline_rehearsal_does_not_change_source_database(tmp_path: Path) -> None:
    db = tmp_path / "market.db"
    conn = sqlite3.connect(db)
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.execute(
        """INSERT INTO source_documents(
             document_id,canonical_url,document_type,first_seen_at,last_seen_at
           ) VALUES('sentinel','https://example.test/sentinel','RSS_ITEM',
                    '2026-09-01T00:00:00Z','2026-09-01T00:00:00Z')"""
    )
    conn.commit()
    conn.close()
    before = db.read_bytes()

    result = sqlite_run(db, apply=False)

    assert result["status"] == "already_installed_rehearsal"
    assert result["verification"]["featureVersion"] == "1.0.0"
    assert result["verification"]["integrity"] == "ok"
    assert db.read_bytes() == before
    source = sqlite3.connect(db)
    assert source.execute(
        "SELECT 1 FROM sqlite_master WHERE name='contextual_event_frames'"
    ).fetchone() == (1,)
    source.close()


def test_postgres_migration_body_removes_only_outer_transaction() -> None:
    body = migration_body(POSTGRES)
    assert not body.lstrip().startswith("BEGIN;")
    assert not body.rstrip().endswith("COMMIT;")
    assert "CREATE TABLE market_intelligence.contextual_event_frames" in body
