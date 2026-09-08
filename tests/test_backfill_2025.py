import copy
import json
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import (
    DiscoveredDocument,
    derive_molit_seoul_monthly_macro,
    extract_title_candidates,
    ingest_partition,
    month_windows,
    parse_dart_filings,
    parse_google_news_rss,
    parse_molit_nrg_trade_xml,
    render_google_query,
)


RSS_FIXTURE = b'''<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>2025 January candidate - Publisher A</title>
      <link>https://news.google.com/rss/articles/a</link>
      <guid>guid-a</guid>
      <pubDate>Wed, 15 Jan 2025 03:00:00 GMT</pubDate>
      <description><![CDATA[<a href="https://example.com/a">candidate A</a>]]></description>
      <source url="https://example.com">Publisher A</source>
    </item>
    <item>
      <title>Boundary item - Publisher B</title>
      <link>https://news.google.com/rss/articles/b</link>
      <guid>guid-b</guid>
      <pubDate>Sat, 01 Feb 2025 00:00:00 GMT</pubDate>
      <description>outside the half-open interval</description>
      <source url="https://example.org">Publisher B</source>
    </item>
  </channel>
</rss>'''


MOLIT_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header>
<body><items><item>
<buildYear>1984</buildYear><buildingAr>164.69</buildingAr><buildingType>집합</buildingType>
<buildingUse>업무</buildingUse><buyerGbn>법인</buyerGbn><cdealDay></cdealDay>
<dealAmount>120,000</dealAmount><dealDay>8</dealDay><dealMonth>1</dealMonth><dealYear>2025</dealYear>
<dealingGbn>중개거래</dealingGbn><floor>7</floor><jibun>60</jibun><landUse>일반상업</landUse>
<sggCd>11110</sggCd><sggNm>종로구</sggNm><slerGbn>기타</slerGbn><umdNm>도렴동</umdNm>
</item></items><numOfRows>1000</numOfRows><pageNo>1</pageNo><totalCount>1</totalCount></body></response>""".encode("utf-8")


class ParseMolitTradeTest(unittest.TestCase):
    def test_preserves_full_api_record_and_uses_record_hash_as_external_key(self):
        docs = parse_molit_nrg_trade_xml(MOLIT_FIXTURE, lawd_cd="11110", deal_ym="202501")

        self.assertEqual(len(docs), 1)
        doc = docs[0]
        self.assertTrue(doc.canonical_url.startswith("molit-rtms://nrg-trade/"))
        self.assertEqual(doc.document_type, "API_RECORD")
        self.assertEqual(doc.rights_status, "FULL_STORAGE_ALLOWED")
        self.assertEqual(doc.published_at, "2025-01-08T00:00:00Z")
        self.assertEqual(doc.metadata["api_record"]["dealAmount"], "120,000")
        self.assertEqual(doc.metadata["date_semantics"], "DEAL_DATE_AS_RECORD_DATE")

    def test_preserves_multiplicity_for_identical_api_rows(self):
        root = ET.fromstring(MOLIT_FIXTURE)
        items = root.find(".//items")
        items.append(copy.deepcopy(items[0]))
        duplicate_fixture = ET.tostring(root, encoding="utf-8")

        docs = parse_molit_nrg_trade_xml(duplicate_fixture, lawd_cd="11110", deal_ym="202501")

        self.assertEqual(len(docs), 2)
        self.assertNotEqual(docs[0].external_key, docs[1].external_key)
        self.assertNotEqual(docs[0].canonical_url, docs[1].canonical_url)


class CampaignWindowTest(unittest.TestCase):
    def test_generates_all_2025_months_with_exclusive_end_dates(self):
        windows = month_windows(2025)

        self.assertEqual(len(windows), 12)
        self.assertEqual(windows[0], ("2025-01-01", "2025-02-01"))
        self.assertEqual(windows[-1], ("2025-12-01", "2026-01-01"))
        self.assertEqual(
            render_google_query("asset event", *windows[-1]),
            "asset event after:2025-11-30 before:2026-01-01",
        )


class ParseGoogleNewsRssTest(unittest.TestCase):
    def test_filters_to_half_open_date_window_and_preserves_rss_metadata(self):
        docs = parse_google_news_rss(
            RSS_FIXTURE,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 2, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].external_key, "guid-a")
        self.assertEqual(docs[0].publisher_name, "Publisher A")
        self.assertEqual(docs[0].published_at, "2025-01-15T03:00:00Z")
        self.assertEqual(docs[0].rights_status, "EXCERPT_ALLOWED")
        self.assertIsNone(docs[0].stored_text)
        self.assertIn("candidate A", docs[0].snippet_text)


DART_FIXTURE = {
    "status": "000",
    "message": "정상",
    "list": [
        {
            "corp_code": "001",
            "corp_name": "공시회사",
            "stock_code": "000001",
            "corp_cls": "Y",
            "report_nm": "유형자산 양도 결정",
            "rcept_no": "20250115000123",
            "flr_nm": "공시회사",
            "rcept_dt": "20250115",
            "rm": "",
        },
        {
            "corp_code": "002",
            "corp_name": "다른회사",
            "stock_code": "000002",
            "corp_cls": "K",
            "report_nm": "주주총회소집결의",
            "rcept_no": "20250116000456",
            "flr_nm": "다른회사",
            "rcept_dt": "20250116",
            "rm": "",
        },
    ],
}


class ParseDartFilingsTest(unittest.TestCase):
    def test_filters_report_names_and_builds_stable_disclosure_metadata(self):
        docs = parse_dart_filings(
            DART_FIXTURE,
            start=datetime(2025, 1, 1, tzinfo=timezone.utc),
            end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            report_keywords=("유형자산 양도", "유형자산 취득"),
        )

        self.assertEqual(len(docs), 1)
        self.assertEqual(docs[0].external_key, "20250115000123")
        self.assertEqual(docs[0].document_type, "DISCLOSURE")
        self.assertEqual(docs[0].rights_status, "METADATA_ONLY")
        self.assertIn("rcpNo=20250115000123", docs[0].canonical_url)
        self.assertEqual(docs[0].metadata["corp_code"], "001")


class IngestPartitionTest(unittest.TestCase):
    def test_opendart_ingest_writes_version_bound_cre_scope_assessment(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            doc = DiscoveredDocument(
                canonical_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260820000123",
                external_key="20260820000123",
                title="유형자산 양도 결정",
                publisher_name="공시회사",
                published_at="2026-08-20T00:00:00Z",
                snippet_text="공시회사 | 유형자산 양도 결정",
                document_type="DISCLOSURE",
                rights_status="FULL_STORAGE_ALLOWED",
                stored_text="1. 자산구분 토지 및 건물 자산명 서울 물류센터 2. 양도내역",
                metadata={"provider": "OpenDART"},
            )

            ingest_partition(
                db_path=db_path, source_code="OPENDART",
                job_code="BACKFILL_2026_H2_OPENDART_SALE_DOCUMENT_TEXT_V3",
                category_code="SALE", window_start="2026-08-01T00:00:00Z",
                window_end="2026-09-01T00:00:00Z", query_rendered="OpenDART test",
                documents=[doc], runner_version="test",
            )

            con = sqlite3.connect(db_path)
            row = con.execute("""SELECT a.status_code,a.classifier_version,a.evidence_json,
                                          a.document_version_id=v.document_version_id
                                   FROM document_scope_assessments a
                                   JOIN document_versions v ON v.document_version_id=a.document_version_id""").fetchone()
            con.close()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "CRE_CONFIRMED")
            self.assertEqual(row[1], "DART_CRE_SCOPE_RULE_V1")
            self.assertEqual(row[3], 1)
            self.assertEqual(json.loads(row[2])["assetCategory"], "토지 및 건물")

    def test_repeated_completed_partition_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()

            docs = parse_google_news_rss(
                RSS_FIXTURE,
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
            kwargs = {
                "db_path": db_path,
                "source_code": "GOOGLE_NEWS_RSS",
                "job_code": "BACKFILL_2025_GOOGLE_NEWS_RSS_SALE",
                "category_code": "SALE",
                "window_start": "2025-01-01T00:00:00Z",
                "window_end": "2025-02-01T00:00:00Z",
                "query_rendered": "sale query",
                "documents": docs,
                "runner_version": "test",
            }

            first = ingest_partition(**kwargs)
            second = ingest_partition(**kwargs)

            self.assertEqual(first.inserted_count, 1)
            self.assertFalse(first.skipped_existing_run)
            self.assertTrue(second.skipped_existing_run)

            con = sqlite3.connect(db_path)
            counts = {
                "runs": con.execute("SELECT count(*) FROM collection_runs").fetchone()[0],
                "documents": con.execute("SELECT count(*) FROM source_documents").fetchone()[0],
                "versions": con.execute("SELECT count(*) FROM document_versions").fetchone()[0],
                "links": con.execute("SELECT count(*) FROM run_documents").fetchone()[0],
                "relationship_runs": con.execute("SELECT count(*) FROM relationship_resolution_runs").fetchone()[0],
            }
            con.close()
            self.assertEqual(counts, {"runs": 1, "documents": 1, "versions": 1, "links": 1, "relationship_runs": 2})

    def test_sqlite_ingest_preserves_collection_slot_in_cursor_provenance(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()

            docs = parse_google_news_rss(
                RSS_FIXTURE,
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
            ingest_partition(
                db_path=db_path,
                source_code="GOOGLE_NEWS_RSS",
                job_code="DAILY_GOOGLE_NEWS_RSS_SALE",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                query_rendered="sale query collection_slot=2025-01-15T15:15+09:00",
                documents=docs,
                runner_version="test",
                cursor_metadata={"collection_slot": "2025-01-15T15:15+09:00"},
            )

            con = sqlite3.connect(db_path)
            cursor = json.loads(con.execute("SELECT cursor_in FROM collection_runs").fetchone()[0])
            con.close()
            self.assertEqual(cursor["collection_slot"], "2025-01-15T15:15+09:00")

    def test_campaign_metadata_is_derived_from_2026_half_year_job_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            docs = parse_google_news_rss(
                RSS_FIXTURE,
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
            ingest_partition(
                db_path=db_path,
                source_code="GOOGLE_NEWS_RSS",
                job_code="BACKFILL_2026_H1_GOOGLE_NEWS_RSS_SALE",
                category_code="SALE",
                window_start="2026-01-01T00:00:00Z",
                window_end="2026-02-01T00:00:00Z",
                query_rendered="sale query",
                documents=docs,
                runner_version="test",
            )
            con = sqlite3.connect(db_path)
            campaign = con.execute(
                "SELECT json_extract(config_json, '$.campaign') FROM collection_jobs"
            ).fetchone()[0]
            con.close()
            self.assertEqual(campaign, "BACKFILL_2026_H1")

    def test_title_candidate_extraction_is_idempotent_and_does_not_create_canonical_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            docs = parse_google_news_rss(
                RSS_FIXTURE,
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
            ingest_partition(
                db_path=db_path,
                source_code="GOOGLE_NEWS_RSS",
                job_code="BACKFILL_2025_GOOGLE_NEWS_RSS_SALE",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                query_rendered="sale query",
                documents=docs,
                runner_version="test",
            )

            first = extract_title_candidates(db_path=db_path, year=2025, pipeline_version="title-rule-test")
            second = extract_title_candidates(db_path=db_path, year=2025, pipeline_version="title-rule-test")

            self.assertEqual(first.inserted_extraction_runs, 1)
            self.assertEqual(first.inserted_event_mentions, 1)
            self.assertEqual(second.inserted_extraction_runs, 0)
            self.assertEqual(second.inserted_event_mentions, 0)
            con = sqlite3.connect(db_path)
            counts = {
                "extraction_runs": con.execute("SELECT count(*) FROM extraction_runs").fetchone()[0],
                "event_mentions": con.execute("SELECT count(*) FROM event_mentions").fetchone()[0],
                "events": con.execute("SELECT count(*) FROM events").fetchone()[0],
                "relationship_runs": con.execute("SELECT count(*) FROM relationship_resolution_runs").fetchone()[0],
            }
            status = con.execute("SELECT status_code FROM event_mentions").fetchone()[0]
            con.close()
            self.assertEqual(counts, {"extraction_runs": 1, "event_mentions": 1, "events": 0, "relationship_runs": 3})
            self.assertEqual(status, "EXTRACTED")

    def test_only_latest_document_version_remains_an_active_title_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            docs = parse_google_news_rss(
                RSS_FIXTURE,
                start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                end=datetime(2025, 2, 1, tzinfo=timezone.utc),
            )
            common = dict(
                db_path=db_path,
                source_code="GOOGLE_NEWS_RSS",
                job_code="BACKFILL_2025_GOOGLE_NEWS_RSS_SALE",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                runner_version="test",
            )
            ingest_partition(query_rendered="sale query v1", documents=docs, **common)
            extract_title_candidates(db_path=db_path, year=2025, pipeline_version="title-rule-test")
            updated_docs = [replace(docs[0], title="업데이트된 매각 기사")]
            ingest_partition(query_rendered="sale query v2", documents=updated_docs, **common)

            extract_title_candidates(db_path=db_path, year=2025, pipeline_version="title-rule-test")

            con = sqlite3.connect(db_path)
            rows = con.execute(
                "SELECT title_raw, status_code, rejection_code FROM event_mentions ORDER BY created_at, title_raw"
            ).fetchall()
            con.close()
            self.assertEqual(len(rows), 2)
            self.assertEqual(sum(1 for _title, status, _reason in rows if status == "EXTRACTED"), 1)
            self.assertEqual(sum(1 for _title, status, reason in rows if status == "REJECTED" and reason == "SUPERSEDED_DOCUMENT_VERSION"), 1)
            self.assertIn(("업데이트된 매각 기사", "EXTRACTED", None), rows)

    def test_derives_idempotent_monthly_macro_from_official_trade_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            root = ET.fromstring(MOLIT_FIXTURE)
            items = root.find(".//items")
            items.append(copy.deepcopy(items[0]))
            items[1].find("buildingAr").text = "3300.01"
            items[1].find("jibun").text = "100-2"
            docs = parse_molit_nrg_trade_xml(
                ET.tostring(root, encoding="utf-8"),
                lawd_cd="11110",
                deal_ym="202501",
            )
            ingest_partition(
                db_path=db_path,
                source_code="MOLIT_REAL_TRANSACTION",
                job_code="BACKFILL_2025_MOLIT_RTMS_NRG_TRADE_11110",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                query_rendered="MOLIT test",
                documents=docs,
                runner_version="test",
            )

            first = derive_molit_seoul_monthly_macro(db_path=db_path, year=2025)
            second = derive_molit_seoul_monthly_macro(db_path=db_path, year=2025)

            self.assertEqual(first.inserted_series, 3)
            self.assertEqual(first.inserted_releases, 1)
            self.assertEqual(first.inserted_observations, 3)
            self.assertEqual(second.inserted_series, 0)
            self.assertEqual(second.inserted_releases, 0)
            self.assertEqual(second.inserted_observations, 0)
            con = sqlite3.connect(db_path)
            values = dict(con.execute(
                """SELECT s.series_code, o.value_decimal_text
                   FROM macro_observations o
                   JOIN macro_series s ON s.macro_series_id = o.macro_series_id"""
            ))
            event_count = con.execute("SELECT count(*) FROM events").fetchone()[0]
            con.close()
            self.assertEqual(values["MOLIT_SEOUL_NRG_TRADE_COUNT"], "1")
            self.assertEqual(values["MOLIT_SEOUL_NRG_TRADE_AMOUNT_KRW"], "1200000000")
            self.assertEqual(values["MOLIT_SEOUL_NRG_BUILDING_AREA_M2"], "3300.01")
            self.assertEqual(event_count, 0)


if __name__ == "__main__":
    unittest.main()
