from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys

import pytest

MODULE_PATH = Path(__file__).parents[1] / "scripts" / "enrich_document_content.py"
SPEC = spec_from_file_location("enrich_document_content", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_extractive_summary_uses_body_and_drops_repeated_title():
    title = "서울 오피스 거래 확대"
    body = """서울 오피스 거래 확대
서울 도심 오피스 거래가 올해 들어 크게 늘었다. 주요 거래는 기관투자자가 참여했으며 거래금액은 1조원을 넘어섰다. 시장 관계자는 우량 자산 중심의 경쟁이 이어질 것으로 전망했다."""
    summary = MODULE.extractive_summary(body, title)
    assert summary
    assert summary != title
    assert "기관투자자" in summary
    assert len(summary) <= MODULE.MAX_SUMMARY_CHARS


def test_disclosure_summary_preserves_asset_amount_and_purpose():
    body = """유형자산 양수 결정 회사 명 : 테스트주식회사 대표이사 홍길동 유형자산 양수 결정 1. 자산구분 토지 및 건물 - 자산명 서울특별시 성동구 건물 2. 양수내역 양수금액(원) 10,500,000,000 자산총액(원) 20,000,000,000 3. 양수목적 본사 사옥 확보 4. 양수영향 임차료 절감"""
    summary = MODULE.disclosure_summary(body, "주요사항보고서(유형자산양수결정)")
    assert summary
    assert "테스트주식회사" in summary
    assert "10,500,000,000원" in summary
    assert "본사 사옥 확보" in summary
    assert "2. 양수내역" not in summary
    assert "테스트주식회사는" in summary


def test_enrichment_never_returns_full_publisher_body_for_disclosure_projection():
    stored = (
        "회사는 서울 소재 업무시설을 취득하기로 결정했다. "
        "거래금액은 1,500억원이며 장기 임차비용 절감이 목적이다. "
        "계약 체결과 잔금 지급은 공시된 일정에 따라 진행될 예정이다. "
    ) * 20
    candidate = MODULE.Candidate("v1", "DISCLOSURE", "공시", "https://example.com", None, stored)
    payload = MODULE.enrich(candidate)
    assert "body" not in payload
    assert len(payload["excerpt"]) <= MODULE.MAX_EXCERPT_CHARS
    assert len(payload["summary"]) <= MODULE.MAX_SUMMARY_CHARS


def test_candidate_query_is_parameterized():
    sql, params = MODULE.candidate_sql(["RSS_ITEM", "DISCLOSURE"], 25)
    assert "RSS_ITEM" not in sql
    assert params == ["RSS_ITEM", "DISCLOSURE", MODULE.PIPELINE_VERSION, 25]
    force_sql, force_params = MODULE.candidate_sql(["DISCLOSURE"], 10, force=True)
    assert "NOT EXISTS" not in force_sql
    assert force_params == ["DISCLOSURE", 10]


@pytest.mark.parametrize(("db_value", "expected"), [(True, True), (False, False)])
def test_enrichment_run_uses_a_session_advisory_lock(db_value, expected):
    calls = []

    class Result:
        def fetchone(self):
            return (db_value,)

    class Connection:
        def execute(self, sql, params):
            calls.append((sql, params))
            return Result()

    connection = Connection()
    assert MODULE.try_lock_enrichment_run(connection) is expected
    MODULE.unlock_enrichment_run(connection)

    assert calls == [
        ("SELECT pg_try_advisory_lock(hashtextextended(%s, 0))", (MODULE.ENRICHMENT_LOCK_KEY,)),
        ("SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (MODULE.ENRICHMENT_LOCK_KEY,)),
    ]


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://10.0.0.1/metadata",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "http://localhost/",
        "http://example.com:8080/",
        "file:///etc/passwd",
    ],
)
def test_destination_validation_blocks_private_local_and_non_http_urls(url):
    with pytest.raises(RuntimeError):
        MODULE._validated_destination(url)


def test_destination_validation_rejects_dns_that_resolves_private(monkeypatch):
    monkeypatch.setattr(
        MODULE.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(MODULE.socket.AF_INET, MODULE.socket.SOCK_STREAM, 6, "", ("192.168.1.10", 0))],
    )
    with pytest.raises(RuntimeError, match="NON_PUBLIC_DESTINATION"):
        MODULE._validated_destination("https://publisher.example/article")


def test_destination_validation_accepts_only_resolved_public_address(monkeypatch):
    monkeypatch.setattr(
        MODULE.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(MODULE.socket.AF_INET, MODULE.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))],
    )
    parsed, addresses, port = MODULE._validated_destination("https://publisher.example/article")
    assert parsed.hostname == "publisher.example"
    assert addresses == ["93.184.216.34"]
    assert port == 443


def test_robots_lookup_fails_closed(monkeypatch):
    monkeypatch.setattr(MODULE, "_public_addresses", lambda _hostname: ["93.184.216.34"])
    monkeypatch.setattr(MODULE, "safe_fetch_text", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("FETCH_FAILED")))
    assert MODULE.robots_status("https://publisher.example/article") == (False, "UNAVAILABLE")
