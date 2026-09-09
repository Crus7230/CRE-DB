import hashlib
from pathlib import Path

from scripts import export_compact_dashboard_supabase as exporter
from scripts import publish_compact_dashboard_supabase as publisher


ROOT = Path(__file__).resolve().parents[1]
BASE_MIGRATION = ROOT / "db" / "v2" / "migrations" / "4.0.0_supabase_compact_dashboard.sql"
SEARCH_MIGRATION = ROOT / "db" / "v2" / "migrations" / "4.0.1_compact_search_document_terms.sql"


def test_compact_schema_is_private_bounded_versioned_and_lexically_indexed() -> None:
    sql = BASE_MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()

    for schema in ("CRE_SYSTEM", "CRE_NEWS", "CRE_TIMESERIES"):
        assert f"CREATE SCHEMA IF NOT EXISTS {schema}" in upper
    assert "TERMS TEXT[] NOT NULL" in upper
    assert "USING GIN (TERMS)" in upper
    assert "IX_CRE_ARTICLES_SEARCH_TRGM" in upper
    assert "SEARCH_DOCUMENT.TERMS @> ARRAY[LOWER(V_Q)]" in upper
    assert "SET ENABLE_SEQSCAN = OFF" in upper
    assert "ILIKE V_LIKE_PATTERN ESCAPE '\\'" in upper
    assert "COALESCE(BOOL_OR(COALESCE(BLOCKED_UNTIL > V_NOW, FALSE)), FALSE)" in upper
    assert "VALUES ('COMPACT_DASHBOARD_SCHEMA_VERSION', '1.1.0')" in upper
    assert "REVOKE ALL ON ALL TABLES IN SCHEMA" in upper
    assert "FROM PUBLIC, ANON, AUTHENTICATED" in upper
    assert "VECTOR" not in upper
    for rpc in (
        "dashboard_serving_manifest",
        "dashboard_daily_articles",
        "dashboard_article_detail",
        "dashboard_macro_timeseries",
        "dashboard_permit_timeseries",
        "dashboard_market_pulse",
        "dashboard_contextual_evidence_search",
        "dashboard_authorize_subject",
        "dashboard_find_authorized_subject",
        "dashboard_consume_login_attempts",
        "dashboard_clear_login_attempts",
    ):
        assert f"FUNCTION PUBLIC.{rpc.upper()}" in upper


def test_search_compaction_migration_only_drops_the_superseded_posting_table() -> None:
    sql = SEARCH_MIGRATION.read_text(encoding="utf-8")
    upper = sql.upper()

    assert "ARRAY_AGG(TERM ORDER BY TERM)" in upper
    assert "DROP TABLE IF EXISTS CRE_NEWS.ARTICLE_SEARCH_TERMS;" in upper
    assert "DROP TABLE IF EXISTS CRE_NEWS.ARTICLE_SEARCH_TERMS CASCADE" not in upper
    assert upper.count("DROP TABLE") == 1
    assert "DELETE FROM" not in upper


def test_search_export_has_one_sorted_unique_term_array_per_document(monkeypatch) -> None:
    monkeypatch.setattr(
        exporter,
        "article_rows",
        lambda _connection: [
            {"document_id": "doc-b", "search_text": "매각 매각 PF"},
            {"document_id": "doc-a", "search_text": "임대차 물류센터"},
        ],
    )

    rows = exporter.article_search_document_rows(object())

    assert [row["document_id"] for row in rows] == ["doc-a", "doc-b"]
    assert all(row["terms"] == sorted(set(row["terms"])) for row in rows)
    assert "매각" in rows[1]["terms"]
    assert "임대" in rows[0]["terms"]


def test_serving_identity_uses_schema_and_content_not_source_file_metadata() -> None:
    inputs = {
        "lineages": [{"dataset_code": "DAILY_ARTICLES", "generated_at": "2026-09-09T00:00:00Z"}],
        "table_hashes": {"articles": "a" * 64},
        "row_counts": {"articles": 1},
        "facets": {"news": {"availableThrough": "2026-09-09"}},
        "pulse_query_sha256": "b" * 64,
    }
    first = exporter.serving_identity(**inputs)
    second = exporter.serving_identity(**inputs)

    assert first == second
    assert first["schemaVersion"] == "1.1.0"
    assert not {"path", "mtimeNs", "bytes", "pageCount"} & set(first)
    assert exporter.sha256_json(first) == exporter.sha256_json(second)
    changed = exporter.serving_identity(**{**inputs, "table_hashes": {"articles": "c" * 64}})
    assert exporter.sha256_json(first) != exporter.sha256_json(changed)


def test_immutable_export_reuses_same_content_version_as_no_op(tmp_path, monkeypatch) -> None:
    source = tmp_path / "source.db"
    source.write_bytes(b"source")
    output = tmp_path / "packages"
    dataset_version = "cre-20260909T000000Z-" + hashlib.sha256(b"same").hexdigest()[:12]

    def fake_manifest(_source: Path, staging: Path | None = None):
        assert staging is not None
        (staging / "payload.jsonl.gz").write_bytes(b"payload")
        return {
            "datasetVersion": dataset_version,
            "sourceManifestSha256": hashlib.sha256(b"same").hexdigest(),
            "mode": "EXPORT",
        }

    monkeypatch.setattr(exporter, "build_manifest", fake_manifest)
    first_path, first_manifest = exporter.export_package(source, output)
    second_path, second_manifest = exporter.export_package(source, output)

    assert first_path == second_path
    assert first_manifest == second_manifest
    assert [path.name for path in output.iterdir()] == [dataset_version]


def test_remote_semantic_normalization_is_type_stable() -> None:
    assert publisher._normalize_semantic_value("macro_monthly", "observation_month", "2026-09") == "2026-09-01"
    assert publisher._normalize_semantic_value("macro_monthly", "numeric_value", 1.2300) == "1.23"
    assert publisher._normalize_timestamp("2026-09-09T06:04:07Z") == "2026-09-09T06:04:07.000000Z"


def test_publisher_never_overwrites_existing_authorization_and_prune_is_guarded() -> None:
    source = (ROOT / "scripts" / "publish_compact_dashboard_supabase.py").read_text(encoding="utf-8")

    assert "ON CONFLICT(subject_id) DO NOTHING" in source
    assert "Only an explicitly named RETIRED, non-active dataset may be pruned" in source
    assert "Prune would remove the active dataset" in source
    assert "auth_after_delete != before[\"authSubjectCount\"]" in source


def test_preactivation_gate_runs_full_semantic_parity_before_pointer_switch(monkeypatch) -> None:
    calls: list[str] = []
    expected = {table: 1 for table in publisher.LOAD_ORDER}

    monkeypatch.setattr(
        publisher,
        "_remote_counts",
        lambda _connection, _version: calls.append("counts") or dict(expected),
    )
    monkeypatch.setattr(
        publisher,
        "verify_remote_semantic_parity",
        lambda _connection, _package, _version: calls.append("semantic") or {
            table: {"matched": True, "rowCount": 1, "semanticSha256": table}
            for table in publisher.LOAD_ORDER
        },
    )

    counts, semantic = publisher.preactivation_parity_gate(
        object(),
        Path("unused-package"),
        "cre-20260909T000000Z-aaaaaaaaaaaa",
        expected,
    )

    assert calls == ["counts", "semantic"]
    assert counts == expected
    assert all(result["matched"] for result in semantic.values())
    source = (ROOT / "scripts" / "publish_compact_dashboard_supabase.py").read_text(encoding="utf-8")
    publish_body = source[source.index("def publish_package("):source.index("def inspect_prune_candidate(")]
    assert publish_body.index("preactivation_parity_gate(") < publish_body.index("if activate:")
