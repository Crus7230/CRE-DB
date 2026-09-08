import pytest

from scripts.retire_supabase_collection_history import ensure_retire_gate


def test_retire_requires_current_validated_snapshot_and_matching_index() -> None:
    ensure_retire_gate(
        requested_snapshot_id="archive-abc",
        current_snapshot={"snapshot_id": "archive-abc", "integrity_status": "VALIDATED", "is_current": True},
        staged_rows=735,
        expected_minimum_rows=1,
    )


def test_retire_rejects_wrong_or_unvalidated_snapshot() -> None:
    with pytest.raises(RuntimeError, match="snapshot gate failed"):
        ensure_retire_gate(
            requested_snapshot_id="archive-abc",
            current_snapshot={"snapshot_id": "archive-other", "integrity_status": "VALIDATED", "is_current": True},
            staged_rows=735,
            expected_minimum_rows=1,
        )
    with pytest.raises(RuntimeError, match="snapshot gate failed"):
        ensure_retire_gate(
            requested_snapshot_id="archive-abc",
            current_snapshot={"snapshot_id": "archive-abc", "integrity_status": "RETIRED", "is_current": False},
            staged_rows=0,
            expected_minimum_rows=1,
        )
