from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT))

from scripts.backfill_record_classifications import archived_market_code, backfill_classifications  # noqa: E402


def test_archived_category_code_is_interpreted_by_record_kind() -> None:
    assert archived_market_code("EVENT", "NEW_SUPPLY") == "SUPPLY"
    assert archived_market_code("LP_MANDATE", "CLOSED") == "LP_MANDATE"
    assert archived_market_code("SALE_PROCESS", "CLOSED") == "SALE"
    assert archived_market_code("DOCUMENT", "RSS_ITEM") is None

SCHEMA = ROOT / "db" / "v2" / "schema.sql"
SEED = ROOT / "db" / "v2" / "seed.sql"


def test_event_category_backfill_is_deterministic_and_idempotent(tmp_path: Path) -> None:
    db = tmp_path / "classification.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.execute("""insert into events(event_id,canonical_title,primary_category_id,lifecycle_status,verification_level)
      values('event-sale-1','테스트 매각','cat_sale','ACTIVE','V2')""")
    conn.commit()

    first = backfill_classifications(conn, apply=True)
    second = backfill_classifications(conn, apply=True)
    assert first["assignments_inserted"] >= 1
    assert second["assignments_inserted"] == 0
    row = conn.execute("""select s.scheme_code,t.term_code,r.assignment_role,r.is_primary,
             r.classifier_version,r.evidence_status,r.review_status
      from record_classifications r
      join classification_schemes s using(classification_scheme_id)
      join classification_terms t using(classification_scheme_id,classification_term_id)
      where r.target_kind='EVENT' and r.target_id='event-sale-1'""").fetchone()
    assert row == (
        "MARKET_CATEGORY", "SALE", "LEGACY_BACKFILL", 1,
        "EVENT_CATEGORY_V1", "DIRECT_STRUCTURED", "APPROVED",
    )
    conn.close()


def test_backfill_dry_run_rolls_back(tmp_path: Path) -> None:
    db = tmp_path / "classification-dry.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.execute("""insert into events(event_id,canonical_title,primary_category_id)
      values('event-sale-2','드라이런 매각','cat_sale')""")
    conn.commit()
    result = backfill_classifications(conn, apply=False)
    assert result["assignments_planned"] >= 1
    assert conn.execute("select count(*) from record_classifications").fetchone()[0] == 0
    conn.close()


def test_backfill_can_defer_commit_for_atomic_migration_runner(tmp_path: Path) -> None:
    db = tmp_path / "classification-atomic.db"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(SCHEMA.read_text(encoding="utf-8"))
    conn.executescript(SEED.read_text(encoding="utf-8"))
    conn.execute("""insert into events(event_id,canonical_title,primary_category_id)
      values('event-sale-atomic','원자적 매각','cat_sale')""")
    conn.commit()

    result = backfill_classifications(conn, apply=True, commit=False)
    inside = conn.execute("select count(*) from record_classifications").fetchone()[0]
    conn.rollback()
    persisted = conn.execute("select count(*) from record_classifications").fetchone()[0]
    conn.close()

    assert result["assignments_inserted"] > 0
    assert inside > 0
    assert persisted == 0
