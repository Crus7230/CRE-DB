from pathlib import Path

from scripts.apply_source_cre_scope import SUPPORTED_SOURCES


SCRIPT = Path(__file__).parents[1] / "scripts" / "apply_source_cre_scope.py"


def test_cleanup_supports_only_audited_sources() -> None:
    assert SUPPORTED_SOURCES == {"GOOGLE_NEWS_RSS", "MOLIT_REAL_TRANSACTION"}


def test_cleanup_contract_has_destructive_rehearsal_and_identity_gates() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "--rollback-after-apply" in source
    assert "--expected-manifest-sha256" in source
    assert "SERIALIZABLE" in source
    assert "document_version_no_delete" in source
    assert "DISABLE TRIGGER document_version_no_delete" in source
    assert "ENABLE TRIGGER document_version_no_delete" in source
    assert "SET LOCAL statement_timeout" in source
    assert "for start in range(0, len(excluded), 1000)" in source
