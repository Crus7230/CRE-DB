"""Execute the V2 SQLite schema with synthetic, non-market test data."""
from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TEXT = (
    "가상 남사 데이터센터 개발사업은 2026년 8월 13일 가상금융과 "
    "6,200억원 규모 본PF 약정을 체결했다. 계획 연면적은 82,430㎡다."
)


def span(value: str) -> tuple[int, int]:
    start = TEXT.index(value)
    return start, start + len(value)


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        db_path = Path(temp_dir) / "validation.db"
        con = sqlite3.connect(db_path, timeout=5)
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA busy_timeout = 5000")
        con.row_factory = sqlite3.Row
        con.executescript((ROOT / "schema.sql").read_text(encoding="utf-8"))
        con.executescript((ROOT / "seed.sql").read_text(encoding="utf-8"))

        con.execute(
            """INSERT INTO collection_jobs
               (job_id, job_code, job_version, job_kind, source_id, query_template,
                cadence_code, valid_from)
               VALUES ('job_pf', 'PF_DISCOVERY', 1, 'CATEGORY_SEARCH',
                       'src_google_news', '부동산 PF 본PF', 'DAILY', '2026-08-01')"""
        )
        con.execute(
            "INSERT INTO collection_job_categories VALUES ('job_pf','cat_pf',1)"
        )
        con.execute(
            """INSERT INTO collection_runs
               (run_id, job_id, started_at, completed_at, status_code,
                query_rendered, discovered_count, inserted_count, runner_version)
               VALUES ('run_1','job_pf','2026-08-14T08:00:00Z','2026-08-14T08:01:00Z',
                       'COMPLETED','부동산 PF 본PF',1,1,'validator-1')"""
        )
        con.execute(
            """INSERT INTO source_documents
               (document_id, source_id, canonical_url, publisher_name, document_type,
                first_seen_at, last_seen_at)
               VALUES ('doc_1','src_google_news','https://example.invalid/fake-pf',
                       '가상 경제매체','ARTICLE','2026-08-14T08:00:00Z','2026-08-14T08:00:00Z')"""
        )
        con.execute(
            """INSERT INTO document_versions
               (document_version_id, document_id, version_no, title, published_at,
                collected_at, content_sha256, stored_text, rights_status)
               VALUES ('dv_1','doc_1',1,'가상 남사 데이터센터 본PF 약정',
                       '2026-08-13T18:00:00Z','2026-08-14T08:00:00Z',
                       'synthetic-sha256',?,'FULL_STORAGE_ALLOWED')""",
            (TEXT,),
        )
        con.execute(
            "INSERT INTO run_documents VALUES ('run_1','dv_1',1,?, '2026-08-14T08:00:00Z')",
            (TEXT[:50],),
        )
        con.execute(
            """INSERT INTO document_fts(document_version_id,title,body)
               VALUES ('dv_1','가상 남사 데이터센터 본PF 약정',?)""",
            (TEXT,),
        )
        con.execute(
            """INSERT INTO extraction_runs
               (extraction_run_id, document_version_id, pipeline_version,
                tokenizer_name, model_name, model_version, status_code)
               VALUES ('ext_1','dv_1','pipeline-v2','synthetic-tokenizer',
                       'synthetic-extractor','1','COMPLETED')"""
        )

        mention_specs = [
            ('m_project','PROJECT','가상 남사 데이터센터 개발사업',0.98),
            ('m_date','DATE','2026년 8월 13일',0.99),
            ('m_org','ORGANIZATION','가상금융',0.96),
            ('m_money','MONEY','6,200억원',0.99),
            ('m_stage','EVENT_STAGE','본PF 약정',0.97),
            ('m_area','AREA','82,430㎡',0.99),
        ]
        for mention_id, mention_type, text, confidence in mention_specs:
            start, end = span(text)
            con.execute(
                """INSERT INTO mentions
                   (mention_id, extraction_run_id, mention_type, sentence_index,
                    char_start, char_end, surface_text, normalized_text, confidence)
                   VALUES (?, 'ext_1', ?, 0, ?, ?, ?, ?, ?)""",
                (mention_id, mention_type, start, end, text, text.replace(',', ''), confidence),
            )

        con.executemany(
            """INSERT INTO mention_values
               (mention_id,value_kind,raw_value,numeric_value,date_start,date_end,
                date_precision,currency_code,unit_code,normalized_json)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                ('m_date','DATE','2026년 8월 13일',None,'2026-08-13','2026-08-13','DAY',None,None,'{}'),
                ('m_money','MONEY','6,200억원',620_000_000_000,None,None,None,'KRW','KRW','{}'),
                ('m_area','AREA','82,430㎡',82430,None,None,None,None,'M2','{}'),
            ],
        )
        con.executemany(
            """INSERT INTO mention_relations
               (mention_relation_id, extraction_run_id, subject_mention_id,
                relation_code, object_mention_id, confidence, extraction_method)
               VALUES (?, 'ext_1', ?, ?, ?, ?, 'MODEL')""",
            [
                ('mr_money','m_project','PF_COMMITMENT_AMOUNT','m_money',0.94),
                ('mr_area','m_project','GROSS_FLOOR_AREA','m_area',0.90),
                ('mr_stage','m_project','HAS_EVENT_STAGE','m_stage',0.96),
            ],
        )

        con.execute(
            """INSERT INTO organizations
               (organization_id,organization_type,canonical_name,status_code)
               VALUES ('org_fake','FINANCIAL_INSTITUTION','가상금융','ACTIVE')"""
        )
        con.execute(
            """INSERT INTO projects
               (project_id,canonical_name,project_type,asset_class_id,region_id,status_code)
               VALUES ('project_fake','가상 남사 데이터센터 개발사업','DEVELOPMENT',
                       'ac_dc','reg_gyeonggi','ACTIVE')"""
        )
        con.executemany(
            """INSERT INTO mention_resolutions
               (mention_resolution_id,mention_id,target_kind,project_id,organization_id,
                resolution_status,match_score,method_code,selected)
               VALUES (?,?,?,?,?,'RESOLVED',?,'COMPOSITE',1)""",
            [
                ('res_project','m_project','PROJECT','project_fake',None,0.97),
                ('res_org','m_org','ORGANIZATION',None,'org_fake',0.98),
            ],
        )

        ev_start, ev_end = span('가상 남사 데이터센터 개발사업')[0], len(TEXT)
        con.execute(
            """INSERT INTO event_mentions
               (event_mention_id,extraction_run_id,extraction_key,event_category_id,
                stage_code_hint,title_raw,summary_raw,evidence_start,evidence_end,
                event_date_start,event_date_end,date_precision,confidence,status_code)
               VALUES ('em_1','ext_1','event-0','cat_pf','MAIN_PF_COMMITTED',
                       '가상 데이터센터 본PF 약정',?, ?, ?, '2026-08-13','2026-08-13',
                       'DAY',0.94,'APPROVED')""",
            (TEXT, ev_start, ev_end),
        )
        con.executemany(
            "INSERT INTO event_mention_members VALUES ('em_1',?,?,?)",
            [
                ('m_project','SUBJECT_PROJECT',1),
                ('m_org','FINANCIAL_ARRANGER',0),
                ('m_money','PF_COMMITMENT_AMOUNT',0),
                ('m_date','EVENT_DATE',0),
                ('m_stage','EVENT_STAGE',0),
                ('m_area','GROSS_FLOOR_AREA',0),
            ],
        )
        con.executemany(
            """INSERT INTO claims
               (claim_id,event_mention_id,predicate_code,subject_mention_id,object_mention_id,
                value_kind,raw_value,numeric_value,date_start,date_end,date_precision,
                currency_code,unit_code,value_qualifier,certainty_code,evidence_start,
                evidence_end,confidence,verification_status,review_status,extraction_method)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ('claim_pf','em_1','PF_COMMITMENT_AMOUNT','m_project','m_money','MONEY',
                 '6,200억원',620_000_000_000,None,None,None,'KRW','KRW','AGREED','REPORTED',
                 *span('6,200억원'),0.94,'VERIFIED','ACCEPTED','MODEL'),
                ('claim_area','em_1','GROSS_FLOOR_AREA','m_project','m_area','AREA',
                 '82,430㎡',82430,None,None,None,None,'M2','PLANNED','REPORTED',
                 *span('82,430㎡'),0.90,'UNVERIFIED','ACCEPTED','MODEL'),
                ('claim_date','em_1','EVENT_DATE','m_project','m_date','DATE',
                 '2026년 8월 13일',None,'2026-08-13','2026-08-13','DAY',None,None,
                 'ACTUAL','REPORTED',*span('2026년 8월 13일'),0.98,'VERIFIED','ACCEPTED','MODEL'),
            ],
        )
        con.executemany(
            """INSERT INTO claim_arguments
               (claim_argument_id,claim_id,role_code,ordinal,argument_kind,mention_id,confidence)
               VALUES (?,?,?,?,?,?,?)""",
            [
                ('arg_project','claim_pf','PROJECT',0,'MENTION','m_project',0.98),
                ('arg_lender','claim_pf','LENDER',0,'MENTION','m_org',0.96),
                ('arg_price','claim_pf','PRICE',0,'MENTION','m_money',0.99),
                ('arg_area','claim_area','AREA',0,'MENTION','m_area',0.99),
                ('arg_date','claim_date','EFFECTIVE_DATE',0,'MENTION','m_date',0.99),
            ],
        )
        con.executemany(
            "INSERT INTO claim_evidence VALUES (?,?,?)",
            [
                ('claim_pf','m_money','DIRECT'),
                ('claim_pf','m_project','CONTEXT'),
                ('claim_pf','m_org','ATTRIBUTION'),
                ('claim_area','m_area','DIRECT'),
                ('claim_date','m_date','DIRECT'),
            ],
        )

        con.execute(
            """INSERT INTO events
               (event_id,canonical_title,primary_category_id,current_stage_code,
                event_date_start,event_date_end,date_precision,lifecycle_status,
                verification_level,overall_confidence,approved_at)
               VALUES ('event_1','가상 남사 데이터센터 본PF 약정','cat_pf',
                       'MAIN_PF_COMMITTED','2026-08-13','2026-08-13','DAY',
                       'ACTIVE','V3',0.94,'2026-08-14T09:00:00Z')"""
        )
        con.execute("INSERT INTO event_mention_links VALUES ('em_1','event_1','PRIMARY','2026-08-14T09:00:00Z')")
        con.execute("INSERT INTO event_projects VALUES ('event_1','project_fake','FINANCED_PROJECT',0.97,'claim_pf')")
        con.execute("INSERT INTO event_participants VALUES ('event_1','org_fake','FINANCIAL_ARRANGER',NULL,NULL,0.98,NULL)")
        con.execute(
            """INSERT INTO event_transitions
               (event_transition_id,event_id,to_stage_code,source_event_mention_id,
                announced_at,effective_date,date_precision,transition_status,
                confidence,review_status,approved_at)
               VALUES ('transition_1','event_1','MAIN_PF_COMMITTED','em_1',
                       '2026-08-13T18:00:00Z','2026-08-13','DAY','VERIFIED',
                       0.94,'APPROVED','2026-08-14T09:00:00Z')"""
        )
        con.execute(
            """INSERT INTO fact_selections
               (fact_selection_id,predicate_code,event_id,selected_claim_id,
                selection_status,selected_by,selected_at)
               VALUES ('fact_pf','PF_COMMITMENT_AMOUNT','event_1','claim_pf',
                       'CURRENT','validator','2026-08-14T09:00:00Z')"""
        )

        # Extensible measurement scenarios: floor hierarchy, logistics, data center,
        # exact unit normalization, conflicting sources and derivation lineage.
        con.execute(
            """INSERT INTO assets
               (asset_id,canonical_name,asset_class_id,region_id,status_code)
               VALUES ('asset_logi','가상 이천 물류센터','ac_logistics','reg_gyeonggi','ACTIVE')"""
        )
        con.executemany(
            """INSERT INTO spatial_units
               (spatial_unit_id,spatial_unit_type_id,parent_spatial_unit_id,asset_id,project_id,
                canonical_name,floor_label,floor_number,is_basement,sort_path)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                ('su_dc_site','sut_site',None,None,'project_fake','가상 데이터센터 부지',None,None,None,'001'),
                ('su_dc_building','sut_building','su_dc_site',None,None,'A동',None,None,None,'001.001'),
                ('su_dc_b1','sut_floor','su_dc_building',None,None,'A동 B1','B1',-1,1,'001.001.001'),
                ('su_dc_1f','sut_floor','su_dc_building',None,None,'A동 1F','1F',1,0,'001.001.002'),
                ('su_dc_2f','sut_floor','su_dc_building',None,None,'A동 2F','2F',2,0,'001.001.003'),
                ('su_dc_hall','sut_data_hall','su_dc_1f',None,None,'데이터홀 1',None,None,None,'001.001.002.001'),
                ('su_dc_elec','sut_electrical','su_dc_b1',None,None,'주전기실',None,None,None,'001.001.001.001'),
                ('su_logi_site','sut_site',None,'asset_logi',None,'가상 물류센터 부지',None,None,None,'002'),
                ('su_logi_building','sut_building','su_logi_site',None,None,'물류동',None,None,None,'002.001'),
                ('su_logi_1f','sut_floor','su_logi_building',None,None,'물류동 1F','1F',1,0,'002.001.001'),
                ('su_logi_ambient','sut_storage','su_logi_1f',None,None,'상온 적재구역',None,None,None,'002.001.001.001'),
                ('su_logi_cold','sut_cold','su_logi_1f',None,None,'저온 보관구역',None,None,None,'002.001.001.002'),
                ('su_logi_ramp','sut_ramp','su_logi_building',None,None,'차량 램프',None,None,None,'002.001.002'),
            ],
        )
        con.executemany(
            """INSERT INTO measurement_facts
               (measurement_fact_id,measurement_definition_id,asset_id,project_id,spatial_unit_id,
                source_claim_id,source_mention_id,raw_value,comparator_code,value_decimal_text,
                source_unit_code,normalized_value_decimal_text,normalized_numeric_value,
                normalized_unit_code,normalization_version,measurement_status,
                measurement_basis_code,observed_on,confidence,verification_status,review_status)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ('mf_dc_project_gfa','md_gfa',None,'project_fake',None,'claim_area','m_area','82,430㎡','EXACT','82430','M2','82430',82430,'M2','identity-v1','PLANNED','DESIGN_DOCUMENT','2026-08-13',0.90,'UNVERIFIED','ACCEPTED'),
                ('mf_dc_b1','md_floor_area',None,None,'su_dc_b1',None,None,'15,000㎡','EXACT','15000','M2','15000',15000,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.99,'VERIFIED','ACCEPTED'),
                ('mf_dc_1f','md_floor_area',None,None,'su_dc_1f',None,None,'17,000㎡','EXACT','17000','M2','17000',17000,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.99,'VERIFIED','ACCEPTED'),
                ('mf_dc_2f','md_floor_area',None,None,'su_dc_2f',None,None,'16,000㎡','EXACT','16000','M2','16000',16000,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.99,'VERIFIED','ACCEPTED'),
                ('mf_dc_building_gfa','md_gfa',None,None,'su_dc_building',None,None,'층별 합계 48,000㎡','EXACT','48000','M2','48000',48000,'M2','sum-v1','CALCULATED','CALCULATED','2026-08-14',1.0,'VERIFIED','ACCEPTED'),
                ('mf_dc_hall','md_data_hall',None,None,'su_dc_hall',None,None,'2,500㎡','EXACT','2500','M2','2500',2500,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.98,'VERIFIED','ACCEPTED'),
                ('mf_dc_electrical','md_electrical_room',None,None,'su_dc_elec',None,None,'1,200㎡','EXACT','1200','M2','1200',1200,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.98,'VERIFIED','ACCEPTED'),
                ('mf_logi_ambient','md_ambient_storage',None,None,'su_logi_ambient',None,None,'10,000평','EXACT','10000','PYEONG','33057.85',33057.85,'M2','pyeong-to-m2-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.95,'VERIFIED','ACCEPTED'),
                ('mf_logi_cold','md_cold_storage',None,None,'su_logi_cold',None,None,'5,000㎡','EXACT','5000','M2','5000',5000,'M2','identity-v1','ACTUAL','OPERATIONAL_MEASURED','2026-08-14',0.95,'VERIFIED','ACCEPTED'),
                ('mf_logi_ramp','md_ramp_area',None,None,'su_logi_ramp',None,None,'약 800㎡','ABOUT','800','M2','800',800,'M2','identity-v1','REPORTED','SOURCE_REPORTED','2026-08-14',0.80,'UNVERIFIED','UNREVIEWED'),
                ('mf_logi_site_article','md_site_area','asset_logi',None,None,None,None,'약 30,000㎡','ABOUT','30000','M2','30000',30000,'M2','identity-v1','REPORTED','SOURCE_REPORTED','2026-08-13',0.70,'UNVERIFIED','ACCEPTED'),
                ('mf_logi_site_register','md_site_area','asset_logi',None,None,None,None,'31,000㎡','EXACT','31000','M2','31000',31000,'M2','identity-v1','REGISTERED','LEGAL_REGISTER','2026-08-14',0.99,'VERIFIED','ACCEPTED'),
            ],
        )
        con.executemany(
            """INSERT INTO measurement_fact_dimensions
               (measurement_fact_dimension_id,measurement_fact_id,measurement_dimension_id,
                ordinal,option_id,text_value,source_text)
               VALUES (?,?,?,?,?,?,?)""",
            [
                ('mfd_gfa_std','mf_dc_project_gfa','dim_standard',0,'mdo_std_design',None,'계획 설계도면'),
                ('mfd_b1_floor','mf_dc_b1','dim_floor_label',0,None,'B1','B1'),
                ('mfd_1f_floor','mf_dc_1f','dim_floor_label',0,None,'1F','1F'),
                ('mfd_2f_floor','mf_dc_2f','dim_floor_label',0,None,'2F','2F'),
                ('mfd_hall_std','mf_dc_hall','dim_standard',0,'mdo_std_operation',None,'운영자료'),
                ('mfd_ambient_temp','mf_logi_ambient','dim_temperature',0,'mdo_temp_ambient',None,'상온'),
                ('mfd_ambient_std','mf_logi_ambient','dim_standard',0,'mdo_std_operation',None,'운영자료'),
                ('mfd_cold_temp','mf_logi_cold','dim_temperature',0,'mdo_temp_chilled',None,'저온'),
                ('mfd_ramp_std','mf_logi_ramp','dim_standard',0,'mdo_std_design',None,'설계도면'),
            ],
        )
        con.execute(
            """INSERT INTO measurement_derivations
               (measurement_derivation_id,output_measurement_fact_id,method_code,expression_text,
                calculation_version,rounding_rule,calculated_at,calculated_by)
               VALUES ('mder_dc_gfa','mf_dc_building_gfa','SUM',
                       'B1 FLOOR_AREA + 1F FLOOR_AREA + 2F FLOOR_AREA',
                       'area-sum-v1','0.01 M2','2026-08-14T10:00:00Z','validator')"""
        )
        con.executemany(
            "INSERT INTO measurement_derivation_inputs VALUES ('mder_dc_gfa',?,'ADDEND',?,NULL)",
            [('mf_dc_b1',0),('mf_dc_1f',1),('mf_dc_2f',2)],
        )
        con.execute(
            """INSERT INTO measurement_fact_selections
               (measurement_fact_selection_id,measurement_definition_id,asset_id,
                selected_measurement_fact_id,selection_status,selected_by,selected_at,selection_reason)
               VALUES ('mfs_logi_site','md_site_area','asset_logi','mf_logi_site_register',
                       'CURRENT','validator','2026-08-14T10:00:00Z','법정 대장값 우선')"""
        )

        con.executemany(
            """INSERT INTO macro_releases
               (macro_release_id,source_id,publisher_release_key,release_title,released_at,
                artifact_sha256,publisher_revision_no,revises_release_id,first_collected_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [
                ('release_v0','src_molit_rt','synthetic-2026-07','가상 2026년 7월 거래통계',
                 '2026-08-05','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                 '0',None,'2026-08-05'),
                ('release_v1','src_molit_rt','synthetic-2026-07','가상 2026년 7월 거래통계 수정',
                 '2026-08-12','bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb',
                 '1','release_v0','2026-08-12'),
            ],
        )
        con.executemany(
            """INSERT INTO macro_observations
               (macro_observation_id,macro_series_id,macro_release_id,period_start,period_end,
                period_label,observed_on,numeric_value,value_decimal_text,unit_code,
                collected_at,vintage_at,revision_no,observation_status,raw_value,row_sha256,
                supersedes_observation_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            [
                ('mo_v0','ms_txn_count','release_v0','2026-07-01','2026-07-31',
                 '2026년 7월',None,110,'110','COUNT','2026-08-05','2026-08-05',0,
                 'PRELIMINARY','110','cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc',None),
                ('mo_v1','ms_txn_count','release_v1','2026-07-01','2026-07-31',
                 '2026년 7월',None,112,'112','COUNT','2026-08-12','2026-08-12',1,
                 'REVISED','112','dddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddddd','mo_v0'),
            ],
        )
        con.execute(
            """INSERT INTO snapshots
               (snapshot_id,snapshot_type,as_of_at,collection_run_id,generator_version,
                status_code,row_count,checksum_sha256,completed_at)
               VALUES ('snap_1','WEEKLY','2026-08-14T23:59:59Z','run_1','snapshot-v1',
                       'COMPLETE',2,'synthetic-checksum','2026-08-15T00:01:00Z')"""
        )
        con.execute("INSERT INTO snapshot_macro_items VALUES ('snap_1','mo_v1')")
        con.execute(
            """INSERT INTO snapshot_event_states
               VALUES ('snap_1','event_1','MAIN_PF_COMMITTED','ACTIVE','V3',0.94,
                       '2026-08-13','2026-08-14T23:59:59Z')"""
        )
        con.execute(
            """INSERT INTO snapshot_metrics
               (snapshot_metric_id,snapshot_id,metric_code,event_category_id,region_id,
                asset_class_id,numeric_value,unit_code,calculation_version)
               VALUES ('metric_1','snap_1','EVENT_COUNT','cat_pf','reg_gyeonggi',
                       'ac_dc',1,'COUNT','metric-v1')"""
        )
        con.commit()

        append_only_guard = False
        try:
            con.execute(
                "UPDATE macro_observations SET numeric_value=999 WHERE macro_observation_id='mo_v0'"
            )
        except sqlite3.DatabaseError:
            append_only_guard = True
            con.rollback()

        unit_dimension_guard = False
        try:
            con.execute(
                """INSERT INTO measurement_facts
                   (measurement_fact_id,measurement_definition_id,asset_id,raw_value,
                    value_decimal_text,source_unit_code,normalized_unit_code,
                    measurement_status,measurement_basis_code)
                   VALUES ('mf_bad_unit','md_site_area','asset_logi','100원','100',
                           'KRW','KRW','REPORTED','SOURCE_REPORTED')"""
            )
        except sqlite3.DatabaseError:
            unit_dimension_guard = True
            con.rollback()

        dimension_kind_guard = False
        try:
            con.execute(
                """INSERT INTO measurement_fact_dimensions
                   (measurement_fact_id,measurement_dimension_id,text_value)
                   VALUES ('mf_logi_ambient','dim_temperature','상온')"""
            )
        except sqlite3.DatabaseError:
            dimension_kind_guard = True
            con.rollback()

        selection_target_guard = False
        try:
            con.execute(
                """INSERT INTO measurement_fact_selections
                   (measurement_definition_id,asset_id,selected_measurement_fact_id,
                    selected_by,selected_at)
                   VALUES ('md_data_hall','asset_logi','mf_logi_site_register',
                           'validator','2026-08-14T11:00:00Z')"""
            )
        except sqlite3.DatabaseError:
            selection_target_guard = True
            con.rollback()

        checks = {
            'integrity': con.execute('PRAGMA integrity_check').fetchone()[0],
            'foreign_key_violations': len(con.execute('PRAGMA foreign_key_check').fetchall()),
            'mention_count': con.execute('SELECT count(*) FROM mentions').fetchone()[0],
            'claim_count': con.execute('SELECT count(*) FROM claims').fetchone()[0],
            'claim_argument_count': con.execute('SELECT count(*) FROM claim_arguments').fetchone()[0],
            'claim_evidence_count': con.execute('SELECT count(*) FROM claim_evidence').fetchone()[0],
            'event_feed_count': con.execute('SELECT count(*) FROM v_event_feed').fetchone()[0],
            'pf_amount_krw': con.execute(
                "SELECT numeric_value FROM claims WHERE claim_id='claim_pf'"
            ).fetchone()[0],
            'latest_macro_value': con.execute(
                "SELECT numeric_value FROM v_latest_macro_observation WHERE macro_series_id='ms_txn_count'"
            ).fetchone()[0],
            'macro_release_count': con.execute('SELECT count(*) FROM macro_releases').fetchone()[0],
            'macro_supersedes': con.execute(
                "SELECT supersedes_observation_id FROM macro_observations WHERE macro_observation_id='mo_v1'"
            ).fetchone()[0],
            'append_only_guard': append_only_guard,
            'measurement_definition_count': con.execute(
                'SELECT count(*) FROM measurement_definitions'
            ).fetchone()[0],
            'measurement_alias_count': con.execute(
                'SELECT count(*) FROM measurement_definition_aliases'
            ).fetchone()[0],
            'ambiguous_surface_area_aliases': con.execute(
                "SELECT count(*) FROM measurement_definition_aliases WHERE normalized_alias='상면면적'"
            ).fetchone()[0],
            'spatial_unit_count': con.execute('SELECT count(*) FROM spatial_units').fetchone()[0],
            'measurement_fact_count': con.execute('SELECT count(*) FROM measurement_facts').fetchone()[0],
            'measurement_dimension_count': con.execute(
                'SELECT count(*) FROM measurement_fact_dimensions'
            ).fetchone()[0],
            'derived_input_sum': con.execute(
                """SELECT sum(f.normalized_numeric_value)
                   FROM measurement_derivation_inputs i
                   JOIN measurement_facts f
                     ON f.measurement_fact_id=i.input_measurement_fact_id
                   WHERE i.measurement_derivation_id='mder_dc_gfa'"""
            ).fetchone()[0],
            'derived_output_value': con.execute(
                "SELECT normalized_numeric_value FROM measurement_facts WHERE measurement_fact_id='mf_dc_building_gfa'"
            ).fetchone()[0],
            'normalized_pyeong_m2': con.execute(
                "SELECT normalized_numeric_value FROM measurement_facts WHERE measurement_fact_id='mf_logi_ambient'"
            ).fetchone()[0],
            'selected_site_area': con.execute(
                """SELECT f.normalized_numeric_value
                   FROM measurement_fact_selections s
                   JOIN measurement_facts f
                     ON f.measurement_fact_id=s.selected_measurement_fact_id
                   WHERE s.measurement_fact_selection_id='mfs_logi_site'"""
            ).fetchone()[0],
            'current_measurement_view_count': con.execute(
                'SELECT count(*) FROM v_current_measurements'
            ).fetchone()[0],
            'current_measurement_view_value': con.execute(
                "SELECT normalized_numeric_value FROM v_current_measurements WHERE subject_id='asset_logi'"
            ).fetchone()[0],
            'unit_dimension_guard': unit_dimension_guard,
            'dimension_kind_guard': dimension_kind_guard,
            'selection_target_guard': selection_target_guard,
            'snapshot_event_count': con.execute(
                "SELECT count(*) FROM snapshot_event_states WHERE snapshot_id='snap_1'"
            ).fetchone()[0],
            'fts_hit_count': con.execute(
                "SELECT count(*) FROM document_fts WHERE document_fts MATCH '데이터센터'"
            ).fetchone()[0],
        }
        assert checks == {
            'integrity': 'ok',
            'foreign_key_violations': 0,
            'mention_count': 6,
            'claim_count': 3,
            'claim_argument_count': 5,
            'claim_evidence_count': 5,
            'event_feed_count': 1,
            'pf_amount_krw': 620_000_000_000,
            'latest_macro_value': 112,
            'macro_release_count': 2,
            'macro_supersedes': 'mo_v0',
            'append_only_guard': True,
            'measurement_definition_count': 70,
            'measurement_alias_count': 40,
            'ambiguous_surface_area_aliases': 2,
            'spatial_unit_count': 13,
            'measurement_fact_count': 12,
            'measurement_dimension_count': 9,
            'derived_input_sum': 48_000,
            'derived_output_value': 48_000,
            'normalized_pyeong_m2': 33_057.85,
            'selected_site_area': 31_000,
            'current_measurement_view_count': 1,
            'current_measurement_view_value': 31_000,
            'unit_dimension_guard': True,
            'dimension_kind_guard': True,
            'selection_target_guard': True,
            'snapshot_event_count': 1,
            'fts_hit_count': 1,
        }, checks
        print(json.dumps(checks, ensure_ascii=False, indent=2))
        con.close()


if __name__ == '__main__':
    main()
