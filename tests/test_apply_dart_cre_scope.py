from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "apply_dart_cre_scope.py"
spec = importlib.util.spec_from_file_location("apply_dart_cre_scope", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(module)


def test_assessment_row_is_deterministic_and_version_bound() -> None:
    row1 = module.assessment_row("v1", "CRE_CONFIRMED", ["PROPERTY"], {"assetText": "서울 사옥"}, "2026-08-20T00:00:00Z")
    row2 = module.assessment_row("v1", "CRE_CONFIRMED", ["PROPERTY"], {"assetText": "서울 사옥"}, "2026-08-20T00:00:00Z")
    assert row1 == row2
    assert row1[1] == "v1"
    assert row1[2] == "CRE"
    assert row1[3] == "DART_CRE_SCOPE_RULE_V1"
    assert row1[4] == "CRE_CONFIRMED"


def test_partition_decisions_separates_confirmed_review_and_excluded() -> None:
    decisions = [
        {"document_id": "a", "status": "CRE_CONFIRMED"},
        {"document_id": "b", "status": "CRE_REVIEW"},
        {"document_id": "c", "status": "CRE_REVIEW_PARSE_FAILED"},
        {"document_id": "d", "status": "OUT_OF_SCOPE_NON_CRE"},
        {"document_id": "e", "status": "OUT_OF_SCOPE_RESIDENTIAL"},
    ]
    result = module.partition_decisions(decisions)
    assert result.confirmed_ids == ("a",)
    assert result.review_ids == ("b", "c")
    assert result.excluded_ids == ("d", "e")


def test_live_scope_queries_are_limited_to_opendart() -> None:
    assert "cs.source_code='OPENDART'" in module.LIVE_DISCLOSURES_SQL
    assert "cs.source_code='OPENDART'" in module.REMAINING_DISCLOSURES_SQL


def test_apply_controls_immutable_delete_trigger_transactionally_and_supports_rehearsal() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert "DISABLE TRIGGER document_version_no_delete" in text
    assert "ENABLE TRIGGER document_version_no_delete" in text
    assert "--rollback-after-apply" in text
    assert "document_version_no_delete was not re-enabled" in text


def test_rollback_bundle_must_match_exact_decision_and_closure() -> None:
    decisions = [{
        "document_id": "doc-1", "document_version_id": "ver-1", "content_sha256": "abc",
        "status": "OUT_OF_SCOPE_NON_CRE", "report_kind": "TYPE_ASSET", "reason_codes": ["NON_CRE_ASSET"],
    }]
    dependencies = {"document_versions": 1}
    bundle = {
        "policy": "HARD_DELETE_OUT_OF_SCOPE_KEEP_REVIEW",
        "classifier_version": "DART_CRE_SCOPE_RULE_V1",
        "schema": "market_intelligence",
        "decisions": {"doc-1": {
            "document_version_id": "ver-1", "content_sha256": "abc",
            "status": "OUT_OF_SCOPE_NON_CRE", "report_kind": "TYPE_ASSET", "reason_codes": ["NON_CRE_ASSET"],
        }},
        "excluded_source_documents": [{"document_id": "doc-1"}],
        "excluded_document_versions": [{"document_version_id": "ver-1"}],
        "dependencies": dependencies,
        "closure_manifest_sha256": "closure",
        "dependent_rows": {"run_documents": []},
        "dependent_rows_sha256": module.manifest_sha256({"run_documents": []}),
        "sqlite_latest_hash_mismatches": [],
    }
    module.validate_rollback_bundle(
        bundle, schema="market_intelligence", decisions=decisions,
        excluded_version_ids=["ver-1"], dependency_counts=dependencies,
        closure_manifest_sha256="closure",
        dependent_rows_sha256=module.manifest_sha256({"run_documents": []}),
    )
    bundle["decisions"]["doc-1"]["status"] = "CRE_CONFIRMED"
    with pytest.raises(RuntimeError, match="decision identity mismatch"):
        module.validate_rollback_bundle(
            bundle, schema="market_intelligence", decisions=decisions,
            excluded_version_ids=["ver-1"], dependency_counts=dependencies,
            closure_manifest_sha256="closure",
            dependent_rows_sha256=module.manifest_sha256({"run_documents": []}),
        )


def test_destructive_apply_locks_resolution_and_review_closure() -> None:
    assert "mention_resolutions" in module.LOCK_TABLES
    assert "review_tasks" in module.LOCK_TABLES
