from pathlib import Path

from scripts.stage_active_serving_archive_index import compact_index_row, deterministic_index_id

ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "stage_active_serving_archive_index.py"


def test_compact_row_is_deterministic_bounded_and_archive_addressable() -> None:
    row = compact_index_row(
        snapshot_id="archive-20260821",
        snapshot_sha256="a" * 64,
        record_kind="EVENT",
        record_id="evt-1",
        title="  종결된   거래  ",
        status="COMPLETED",
        category="SALE",
        date_start="2025-01-01",
        date_end=None,
        publisher="공식기관",
        url="https://example.com/evidence",
        summary="가" * 800,
        source_document_id="doc-1",
        source_document_version_id="dv-1",
        indexed_at="2026-08-21T00:00:00Z",
    )
    assert row["archive_index_id"] == deterministic_index_id("EVENT", "evt-1")
    assert row["canonical_title"] == "종결된 거래"
    assert len(row["summary_text"]) == 500
    assert row["archive_locator"] == "sqlite://archive-20260821#table=events&pk=evt-1"
    assert row["archive_snapshot_sha256"] == "a" * 64


def test_compact_row_rejects_unsupported_kind() -> None:
    try:
        compact_index_row(
            snapshot_id="s",
            snapshot_sha256="a" * 64,
            record_kind="ORGANIZATION",
            record_id="o-1",
            title="x",
            status="INACTIVE",
            category=None,
            date_start=None,
            date_end=None,
            publisher=None,
            url=None,
            summary=None,
            source_document_id=None,
            source_document_version_id=None,
            indexed_at="2026-08-21T00:00:00Z",
        )
    except ValueError as exc:
        assert "unsupported record kind" in str(exc)
    else:
        raise AssertionError("unsupported kind was accepted")


def test_staging_script_contains_no_destructive_statement() -> None:
    source = SCRIPT.read_text(encoding="utf-8").upper()
    assert "DELETE FROM" not in source
    assert "DROP TABLE MARKET_INTELLIGENCE" not in source
