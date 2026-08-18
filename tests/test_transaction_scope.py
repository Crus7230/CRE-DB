import copy
import sqlite3
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.backfill_2025 import extract_title_candidates, ingest_partition, parse_molit_nrg_trade_xml
from collector.transaction_scope import apply_molit_transaction_scope, classify_molit_transaction_scope


MOLIT_SCOPE_FIXTURE = """<?xml version='1.0' encoding='UTF-8'?>
<response><header><resultCode>000</resultCode><resultMsg>OK</resultMsg></header><body>
<items><item><dealYear>2025</dealYear><dealMonth>1</dealMonth><dealDay>15</dealDay>
<dealAmount>120,000</dealAmount><buildingAr>100</buildingAr><buildingUse>업무</buildingUse>
<buildingType>일반</buildingType><sggCd>11110</sggCd><sggNm>서울특별시 종로구</sggNm>
<umdNm>청운동</umdNm><jibun>1-1</jibun><floor>1</floor><buildYear>2000</buildYear></item></items>
<totalCount>1</totalCount></body></response>""".encode("utf-8")


class MolitTransactionScopeTest(unittest.TestCase):
    def test_excludes_residential_use_before_area_evaluation(self):
        decision = classify_molit_transaction_scope(
            {"buildingUse": "공동주택(아파트)", "buildingAr": "5000"}
        )
        self.assertEqual(decision.status, "EXCLUDED")
        self.assertEqual(decision.reason_code, "OUT_OF_SCOPE_RESIDENTIAL_USE")

    def test_excludes_area_equal_to_auto_exclusion_threshold(self):
        decision = classify_molit_transaction_scope(
            {"buildingUse": "업무", "buildingAr": "1000"}
        )
        self.assertEqual(decision.status, "EXCLUDED")
        self.assertEqual(decision.reason_code, "OUT_OF_SCOPE_AREA_LE_1000_M2")

    def test_routes_area_between_thresholds_to_review(self):
        for area in ("1000.01", "3300"):
            with self.subTest(area=area):
                decision = classify_molit_transaction_scope(
                    {"buildingUse": "업무", "buildingAr": area}
                )
                self.assertEqual(decision.status, "REVIEW_REQUIRED")
                self.assertEqual(
                    decision.reason_code, "SCOPE_REVIEW_AREA_1000_3300_M2"
                )

    def test_keeps_non_residential_area_above_threshold(self):
        decision = classify_molit_transaction_scope(
            {"buildingUse": "판매", "buildingAr": "3300.01"}
        )
        self.assertEqual(decision.status, "IN_SCOPE")
        self.assertIsNone(decision.reason_code)

    def test_excludes_missing_or_invalid_area(self):
        for value in (None, "", "not-a-number"):
            with self.subTest(value=value):
                decision = classify_molit_transaction_scope(
                    {"buildingUse": "업무", "buildingAr": value}
                )
                self.assertEqual(decision.status, "EXCLUDED")
                self.assertEqual(decision.reason_code, "OUT_OF_SCOPE_AREA_MISSING")

    def test_applies_scope_filter_to_existing_molit_event_mentions(self):
        root = ET.fromstring(MOLIT_SCOPE_FIXTURE)
        items = root.find(".//items")
        high = copy.deepcopy(items[0])
        high.find("buildingAr").text = "3300.01"
        high.find("jibun").text = "1-2"
        items.append(high)
        root.find(".//totalCount").text = "2"
        docs = parse_molit_nrg_trade_xml(
            ET.tostring(root, encoding="utf-8"), lawd_cd="11110", deal_ym="202501"
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            ingest_partition(
                db_path=db_path,
                source_code="MOLIT_REAL_TRANSACTION",
                job_code="BACKFILL_2025_MOLIT_RTMS_NRG_TRADE_11110",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                query_rendered="scope test",
                documents=docs,
                runner_version="test",
            )
            extract_title_candidates(
                db_path=db_path, year=2025, pipeline_version="title-rule-test"
            )
            con = sqlite3.connect(db_path)
            immediate = con.execute(
                """SELECT em.status_code, em.rejection_code
                   FROM event_mentions em
                   JOIN extraction_runs er ON er.extraction_run_id = em.extraction_run_id
                   JOIN document_versions v ON v.document_version_id = er.document_version_id
                   WHERE json_extract(v.metadata_json, '$.api_record.buildingAr') = '100'"""
            ).fetchone()
            con.close()
            self.assertEqual(immediate, ("REJECTED", "OUT_OF_SCOPE_AREA_LE_1000_M2"))

            result = apply_molit_transaction_scope(db_path=db_path)
            second = apply_molit_transaction_scope(db_path=db_path)

            con = sqlite3.connect(db_path)
            rows = con.execute(
                """SELECT em.status_code, em.rejection_code,
                          json_extract(v.metadata_json, '$.api_record.buildingAr')
                   FROM event_mentions em
                   JOIN extraction_runs er ON er.extraction_run_id = em.extraction_run_id
                   JOIN document_versions v ON v.document_version_id = er.document_version_id
                   ORDER BY CAST(json_extract(v.metadata_json, '$.api_record.buildingAr') AS REAL)"""
            ).fetchall()
            con.close()
            self.assertEqual(result.in_scope, 1)
            self.assertEqual(result.excluded_small_area, 1)
            self.assertEqual(second.mentions_updated, 0)
            self.assertEqual(
                rows,
                [
                    ("REJECTED", "OUT_OF_SCOPE_AREA_LE_1000_M2", "100"),
                    ("EXTRACTED", None, "3300.01"),
                ],
            )

    def test_promotes_small_rows_to_review_when_transaction_group_sum_exceeds_3300(self):
        root = ET.fromstring(MOLIT_SCOPE_FIXTURE)
        items = root.find(".//items")
        items[0].find("buildingAr").text = "527.17"
        items[0].find("floor").text = "7"
        for floor in range(8, 14):
            row = copy.deepcopy(items[0])
            row.find("floor").text = str(floor)
            items.append(row)
        root.find(".//totalCount").text = "7"
        docs = parse_molit_nrg_trade_xml(
            ET.tostring(root, encoding="utf-8"), lawd_cd="11110", deal_ym="202501"
        )
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "market.db"
            con = sqlite3.connect(db_path)
            con.executescript((ROOT / "db" / "v2" / "schema.sql").read_text(encoding="utf-8"))
            con.executescript((ROOT / "db" / "v2" / "seed.sql").read_text(encoding="utf-8"))
            con.close()
            ingest_partition(
                db_path=db_path,
                source_code="MOLIT_REAL_TRANSACTION",
                job_code="BACKFILL_2025_MOLIT_RTMS_NRG_TRADE_11110",
                category_code="SALE",
                window_start="2025-01-01T00:00:00Z",
                window_end="2025-02-01T00:00:00Z",
                query_rendered="scope group test",
                documents=docs,
                runner_version="test",
            )
            extract_title_candidates(
                db_path=db_path, year=2025, pipeline_version="title-rule-test"
            )

            result = apply_molit_transaction_scope(db_path=db_path)

            con = sqlite3.connect(db_path)
            statuses = dict(con.execute(
                "SELECT status_code, count(*) FROM event_mentions GROUP BY status_code"
            ))
            tasks = con.execute(
                """SELECT count(*), min(reason_code)
                   FROM review_tasks
                   WHERE review_type = 'MOLIT_TRANSACTION_SCOPE'"""
            ).fetchone()
            con.close()
            self.assertEqual(result.review_group_count, 1)
            self.assertEqual(result.review_group_rows, 7)
            self.assertEqual(statuses, {"REVIEW_READY": 7})
            self.assertEqual(tasks, (7, "SCOPE_REVIEW_GROUP_SUM_GT_3300_M2"))


if __name__ == "__main__":
    unittest.main()
