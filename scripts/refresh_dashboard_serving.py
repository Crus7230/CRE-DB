#!/usr/bin/env python
"""Build governed dashboard projections without changing raw archive tables.

The default command is a dry run against a disposable SQLite backup. Pass
``--apply`` only for a database that is already an approved candidate. The
refresh itself is transactional and replaces serving rows only after staging
and parity checks succeed.
"""
from __future__ import annotations

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import tempfile
from typing import Any, Iterable, Sequence


SEOUL_PERMIT_SOURCE = "src_seoul_building_permit"
DAILY_DATASET = "DAILY_ARTICLES"
PERMIT_DATASET = "SEOUL_BUILDING_PERMITS"

DAILY_RAW_TABLES = {
    "source_documents",
    "document_versions",
    "document_scope_assessments",
    "document_enrichments",
    "record_classifications",
    "classification_schemes",
    "classification_terms",
}
PERMIT_RAW_TABLES = {
    "building_permit_snapshots",
    "building_permit_record_versions",
    "building_permit_snapshot_records",
    "building_permit_classifications",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _migration_path() -> Path:
    return Path(__file__).resolve().parents[1] / "db" / "turso" / "migrations" / "002_dashboard_serving.sql"


def apply_dashboard_serving_schema(conn: sqlite3.Connection) -> None:
    """Apply the additive serving schema; raw and security tables are untouched."""
    conn.executescript(_migration_path().read_text(encoding="utf-8"))


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_dict(columns: Sequence[str], row: Sequence[Any]) -> dict[str, Any]:
    return {columns[index]: row[index] for index in range(len(columns))}


def _table_digest(
    conn: sqlite3.Connection,
    table: str,
    columns: Sequence[str],
    order_by: Sequence[str],
) -> str:
    digest = hashlib.sha256()
    projection = ",".join(f'"{column}"' for column in columns)
    ordering = ",".join(f'"{column}"' for column in order_by)
    for row in conn.execute(f'SELECT {projection} FROM "{table}" ORDER BY {ordering}'):
        digest.update(_canonical_json(_row_dict(columns, row)).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _dataset_digest(table_digests: dict[str, str]) -> str:
    return hashlib.sha256(_canonical_json(table_digests).encode("utf-8")).hexdigest()


def _refresh_row_fingerprints(
    conn: sqlite3.Connection,
    *,
    dataset_code: str,
    table: str,
    key_columns: Sequence[str],
    content_columns: Sequence[str],
    generated_at: str,
) -> int:
    columns = tuple(dict.fromkeys((*key_columns, *content_columns)))
    projection = ",".join(f'"{column}"' for column in columns)
    ordering = ",".join(f'"{column}"' for column in key_columns)
    rows: list[tuple[str, str, str, str, str, str]] = []
    for raw in conn.execute(f'SELECT {projection} FROM "{table}" ORDER BY {ordering}'):
        record = _row_dict(columns, raw)
        key_json = _canonical_json({key: record[key] for key in key_columns})
        content = _canonical_json({key: record[key] for key in content_columns})
        rows.append((dataset_code, table, key_json, hashlib.sha256(content.encode("utf-8")).hexdigest(), "ACTIVE", generated_at))

    conn.execute(
        """UPDATE serving_row_fingerprints
           SET state_code='RETIRED',updated_at=?
           WHERE dataset_code=? AND table_name=? AND state_code='ACTIVE'""",
        (generated_at, dataset_code, table),
    )
    conn.executemany(
        """INSERT INTO serving_row_fingerprints(
               dataset_code,table_name,row_key_json,content_sha256,state_code,updated_at
             ) VALUES(?,?,?,?,?,?)
             ON CONFLICT(dataset_code,table_name,row_key_json) DO UPDATE SET
               content_sha256=excluded.content_sha256,
               state_code='ACTIVE',updated_at=excluded.updated_at""",
        rows,
    )
    return len(rows)


def _upsert_freshness(
    conn: sqlite3.Connection,
    *,
    dataset_code: str,
    source_code: str,
    source_as_of_date: str,
    generated_at: str,
    source_row_count: int,
    serving_row_count: int,
    content_sha256: str,
    metadata: dict[str, Any],
) -> None:
    conn.execute(
        """INSERT INTO serving_dataset_freshness(
             dataset_code,source_code,source_as_of_date,generated_at,source_status_code,
             source_row_count,serving_row_count,content_sha256,metadata_json
           ) VALUES(?,?,?,?,'READY',?,?,?,?)
           ON CONFLICT(dataset_code) DO UPDATE SET
             source_code=excluded.source_code,
             source_as_of_date=excluded.source_as_of_date,
             generated_at=excluded.generated_at,
             source_status_code=excluded.source_status_code,
             source_row_count=excluded.source_row_count,
             serving_row_count=excluded.serving_row_count,
             content_sha256=excluded.content_sha256,
             metadata_json=excluded.metadata_json""",
        (
            dataset_code,
            source_code,
            source_as_of_date,
            generated_at,
            source_row_count,
            serving_row_count,
            content_sha256,
            _canonical_json(metadata),
        ),
    )


def refresh_daily_article_serving(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    """Stage the current governed article projection, then swap it atomically."""
    present = _tables(conn)
    if not DAILY_RAW_TABLES.issubset(present):
        return {"status": "SKIPPED", "reason": "daily article raw tables are incomplete"}

    conn.executescript("""
        DROP TABLE IF EXISTS temp._daily_articles_next;
        DROP TABLE IF EXISTS temp._daily_topics_next;
        DROP TABLE IF EXISTS temp._daily_dates_next;
        DROP TABLE IF EXISTS temp._daily_details_next;
        CREATE TEMP TABLE _daily_articles_next AS
        SELECT * FROM serving_daily_articles WHERE 0;
        CREATE TEMP TABLE _daily_topics_next AS
        SELECT * FROM serving_daily_article_topics WHERE 0;
        CREATE TEMP TABLE _daily_dates_next AS
        SELECT * FROM serving_daily_article_dates WHERE 0;
        CREATE TEMP TABLE _daily_details_next AS
        SELECT * FROM serving_daily_article_details WHERE 0;
    """)

    conn.execute(
        """INSERT INTO _daily_articles_next(
             document_id,document_version_id,article_date,title,publisher_name,
             published_at,collected_at,summary_text,summary_mode,summary_generated_at,
             canonical_url,document_purpose_code,document_purpose_label,
             evidence_grade_code,evidence_grade_label,topic_count,projection_generated_at
           )
           WITH latest_versions AS MATERIALIZED (
             SELECT dv.*
             FROM document_versions dv
             WHERE NOT EXISTS (
               SELECT 1 FROM document_versions newer
               WHERE newer.document_id=dv.document_id
                 AND (newer.version_no>dv.version_no OR
                      (newer.version_no=dv.version_no AND
                       newer.document_version_id>dv.document_version_id))
             )
           ), eligible AS MATERIALIZED (
             SELECT lv.*,sd.publisher_name,sd.canonical_url
             FROM latest_versions lv
             JOIN source_documents sd ON sd.document_id=lv.document_id
             WHERE sd.document_type IN ('RSS_ITEM','ARTICLE')
               AND lv.published_at IS NOT NULL
               AND date(lv.published_at,'+9 hours') IS NOT NULL
               AND (
                 SELECT dsa.status_code
                 FROM document_scope_assessments dsa
                 WHERE dsa.document_version_id=lv.document_version_id
                   AND dsa.scope_code='CRE'
                 ORDER BY dsa.assessed_at DESC,dsa.classifier_version DESC,
                          dsa.document_scope_assessment_id DESC
                 LIMIT 1
               )='CRE_CONFIRMED'
           ), selected_enrichments AS MATERIALIZED (
             SELECT de.*
             FROM document_enrichments de
             JOIN eligible e ON e.document_version_id=de.document_version_id
             WHERE de.enrichment_kind='CONTENT_SUMMARY'
               AND de.status_code='COMPLETED' AND de.review_status<>'REJECTED'
               AND de.document_enrichment_id=(
                 SELECT candidate.document_enrichment_id
                 FROM document_enrichments candidate
                 WHERE candidate.document_version_id=de.document_version_id
                   AND candidate.enrichment_kind='CONTENT_SUMMARY'
                   AND candidate.status_code='COMPLETED'
                   AND candidate.review_status<>'REJECTED'
                 ORDER BY CASE WHEN candidate.review_status='APPROVED' THEN 0 ELSE 1 END,
                          candidate.generated_at DESC,candidate.document_enrichment_id DESC
                 LIMIT 1
               )
           ), governed_classifications AS MATERIALIZED (
             SELECT rc.target_id,s.scheme_code,t.term_code,t.term_name_ko,rc.is_primary
             FROM record_classifications rc
             JOIN classification_schemes s
               ON s.classification_scheme_id=rc.classification_scheme_id
             JOIN classification_terms t
               ON t.classification_scheme_id=rc.classification_scheme_id
              AND t.classification_term_id=rc.classification_term_id
             WHERE rc.target_kind='DOCUMENT'
               AND s.scheme_code IN ('DOCUMENT_PURPOSE','EVIDENCE_GRADE')
               AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
               AND (rc.valid_from IS NULL OR rc.valid_from<=?)
               AND (rc.valid_to IS NULL OR rc.valid_to>?)
               AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
               AND (s.valid_from IS NULL OR s.valid_from<=?)
               AND (s.valid_to IS NULL OR s.valid_to>?)
               AND (t.valid_from IS NULL OR t.valid_from<=?)
               AND (t.valid_to IS NULL OR t.valid_to>?)
           ), classification_summary AS (
             SELECT gc.target_id,
               max(CASE WHEN gc.scheme_code='DOCUMENT_PURPOSE' AND gc.is_primary=1
                        THEN gc.term_code END) AS document_purpose_code,
               max(CASE WHEN gc.scheme_code='DOCUMENT_PURPOSE' AND gc.is_primary=1
                        THEN gc.term_name_ko END) AS document_purpose_label,
               max(CASE WHEN gc.scheme_code='EVIDENCE_GRADE' AND gc.is_primary=1
                        THEN gc.term_code END) AS evidence_grade_code,
               max(CASE WHEN gc.scheme_code='EVIDENCE_GRADE' AND gc.is_primary=1
                        THEN gc.term_name_ko END) AS evidence_grade_label
             FROM governed_classifications gc
             JOIN eligible e ON e.document_id=gc.target_id
             GROUP BY gc.target_id
           )
           SELECT e.document_id,e.document_version_id,date(e.published_at,'+9 hours'),
                  coalesce(e.title,'제목 없음'),e.publisher_name,e.published_at,e.collected_at,
                  de.summary_text,
                  CASE WHEN de.summary_method='MODEL' THEN 'MODEL'
                       WHEN de.summary_text IS NOT NULL THEN 'BODY_EXTRACTIVE' ELSE 'NONE' END,
                  de.generated_at,coalesce(de.resolved_url,e.canonical_url),
                  cs.document_purpose_code,cs.document_purpose_label,
                  cs.evidence_grade_code,cs.evidence_grade_label,
                  0,?
           FROM eligible e
           LEFT JOIN selected_enrichments de ON de.document_version_id=e.document_version_id
           LEFT JOIN classification_summary cs ON cs.target_id=e.document_id""",
        (generated_at,) * 7,
    )

    conn.execute(
        """INSERT INTO _daily_topics_next(
             document_id,document_version_id,term_code,term_label,status_code,
             provenance_code,is_primary,confidence,sort_order,topic_rank
           )
           WITH ranked_per_term AS (
             SELECT a.document_id,a.document_version_id,t.term_code,t.term_name_ko,
                    rc.review_status,rc.is_primary,rc.confidence,t.sort_order,
                    row_number() OVER (
                      PARTITION BY a.document_version_id,t.term_code
                      ORDER BY CASE rc.review_status
                                 WHEN 'APPROVED' THEN 0 WHEN 'PENDING' THEN 1 ELSE 2 END,
                               rc.is_primary DESC,rc.confidence IS NULL,rc.confidence DESC,
                               rc.assigned_at DESC,rc.record_classification_id DESC
                    ) AS duplicate_rank
             FROM _daily_articles_next a
             JOIN record_classifications rc
               ON rc.target_kind='DOCUMENT' AND rc.target_id=a.document_id
             JOIN classification_schemes s
               ON s.classification_scheme_id=rc.classification_scheme_id
             JOIN classification_terms t
               ON t.classification_scheme_id=rc.classification_scheme_id
              AND t.classification_term_id=rc.classification_term_id
             WHERE s.scheme_code='MARKET_CATEGORY'
               AND rc.review_status NOT IN ('REJECTED','SUPERSEDED')
               AND (rc.valid_from IS NULL OR rc.valid_from<=?)
               AND (rc.valid_to IS NULL OR rc.valid_to>?)
               AND s.governance_status='ACTIVE' AND t.governance_status='ACTIVE'
               AND t.is_assignable=1
               AND (s.valid_from IS NULL OR s.valid_from<=?)
               AND (s.valid_to IS NULL OR s.valid_to>?)
               AND (t.valid_from IS NULL OR t.valid_from<=?)
               AND (t.valid_to IS NULL OR t.valid_to>?)
           ), selected AS (
             SELECT * FROM ranked_per_term WHERE duplicate_rank=1
           ), ordered AS (
             SELECT selected.*,
                    row_number() OVER (
                      PARTITION BY document_version_id
                      ORDER BY CASE review_status WHEN 'APPROVED' THEN 0 ELSE 1 END,
                               is_primary DESC,confidence IS NULL,confidence DESC,
                               sort_order,term_code
                    ) AS topic_rank
             FROM selected
           )
           SELECT document_id,document_version_id,term_code,term_name_ko,
                  CASE WHEN review_status='APPROVED' THEN 'CONFIRMED' ELSE 'CANDIDATE' END,
                  CASE WHEN review_status='APPROVED'
                       THEN 'APPROVED_CLASSIFICATION' ELSE 'PENDING_CLASSIFICATION' END,
                  is_primary,confidence,sort_order,topic_rank
           FROM ordered""",
        (generated_at,) * 6,
    )
    conn.execute(
        """UPDATE _daily_articles_next
           SET topic_count=(SELECT count(*) FROM _daily_topics_next topic
                            WHERE topic.document_id=_daily_articles_next.document_id)"""
    )
    conn.execute(
        """INSERT INTO _daily_details_next(
             document_id,document_version_id,payload_json,projection_generated_at
           )
           WITH selected_enrichments AS MATERIALIZED (
             SELECT de.*
             FROM document_enrichments de
             JOIN _daily_articles_next article
               ON article.document_version_id=de.document_version_id
             WHERE de.enrichment_kind='CONTENT_SUMMARY'
               AND de.status_code='COMPLETED' AND de.review_status<>'REJECTED'
               AND de.document_enrichment_id=(
                 SELECT candidate.document_enrichment_id
                 FROM document_enrichments candidate
                 WHERE candidate.document_version_id=de.document_version_id
                   AND candidate.enrichment_kind='CONTENT_SUMMARY'
                   AND candidate.status_code='COMPLETED'
                   AND candidate.review_status<>'REJECTED'
                 ORDER BY CASE WHEN candidate.review_status='APPROVED' THEN 0 ELSE 1 END,
                          candidate.generated_at DESC,candidate.document_enrichment_id DESC
                 LIMIT 1
               )
           )
           SELECT article.document_id,article.document_version_id,
             json_object(
               'id',article.document_id,'title',article.title,
               'publisher',article.publisher_name,'documentType',source.document_type,
               'sourceUrl',article.canonical_url,'author',version.author_name,
               'publishedAt',article.published_at,'collectedAt',article.collected_at,
               'rightsStatus',version.rights_status,
               'contentMode',CASE WHEN enrichment.safe_excerpt IS NOT NULL THEN 'SAFE_EXCERPT'
                 WHEN length(trim(coalesce(version.snippet_text,'')))>0 THEN 'SNIPPET'
                 ELSE 'METADATA' END,
               'summaryMode',CASE WHEN article.summary_text IS NOT NULL THEN article.summary_mode
                 WHEN length(trim(coalesce(version.snippet_text,'')))>0
                  AND lower(trim(version.snippet_text))<>lower(trim(article.title))
                 THEN 'SOURCE_SNIPPET' ELSE 'NONE' END,
               'summaryGeneratedAt',article.summary_generated_at,
               'summaryPipeline',enrichment.pipeline_version,
               'summary',coalesce(article.summary_text,
                 CASE WHEN lower(trim(coalesce(version.snippet_text,'')))<>lower(trim(article.title))
                      THEN nullif(version.snippet_text,'') END),
               'safeExcerpt',enrichment.safe_excerpt,
               'snippet',nullif(version.snippet_text,''),
               'storedText',NULL,
               'eventSignals',json('[]'),'keywords',json('[]'),
               'relatedEntities',json('[]'),
               'classifications',json(COALESCE((
                 SELECT json_group_array(json(classification.item))
                 FROM (
                   SELECT topic.topic_rank AS item_order,json_object(
                     'schemeCode','MARKET_CATEGORY','schemeLabel','시장 카테고리',
                     'termCode',topic.term_code,'termLabel',topic.term_label,
                     'parentCode',NULL,'parentLabel',NULL,
                     'isPrimary',json(CASE WHEN topic.is_primary=1 THEN 'true' ELSE 'false' END),
                     'assignmentRole','SERVING_PROJECTION',
                     'evidenceStatus',CASE WHEN topic.status_code='CONFIRMED' THEN 'APPROVED' ELSE 'INFERRED' END,
                     'reviewStatus',CASE WHEN topic.status_code='CONFIRMED' THEN 'APPROVED' ELSE 'PENDING' END,
                     'confidence',topic.confidence
                   ) AS item
                   FROM _daily_topics_next topic
                   WHERE topic.document_id=article.document_id
                   UNION ALL
                   SELECT 1001,json_object(
                     'schemeCode','DOCUMENT_PURPOSE','schemeLabel','문서 목적',
                     'termCode',article.document_purpose_code,
                     'termLabel',article.document_purpose_label,
                     'parentCode',NULL,'parentLabel',NULL,'isPrimary',json('true'),
                     'assignmentRole','SERVING_PROJECTION','evidenceStatus','INFERRED',
                     'reviewStatus','PENDING','confidence',NULL
                   ) WHERE article.document_purpose_code IS NOT NULL
                   UNION ALL
                   SELECT 1002,json_object(
                     'schemeCode','EVIDENCE_GRADE','schemeLabel','근거 등급',
                     'termCode',article.evidence_grade_code,
                     'termLabel',article.evidence_grade_label,
                     'parentCode',NULL,'parentLabel',NULL,'isPrimary',json('true'),
                     'assignmentRole','SERVING_PROJECTION','evidenceStatus','INFERRED',
                     'reviewStatus','PENDING','confidence',NULL
                   ) WHERE article.evidence_grade_code IS NOT NULL
                   ORDER BY item_order
                 ) classification
               ),'[]')),
               'transaction',NULL
             ),?
           FROM _daily_articles_next article
           JOIN document_versions version
             ON version.document_version_id=article.document_version_id
           JOIN source_documents source ON source.document_id=article.document_id
           LEFT JOIN selected_enrichments enrichment
             ON enrichment.document_version_id=article.document_version_id""",
        (generated_at,),
    )
    last_collected_at = conn.execute("SELECT max(collected_at) FROM _daily_articles_next").fetchone()[0]
    conn.execute(
        """INSERT INTO _daily_dates_next(
             article_date,article_count,categorized_count,summarized_count,last_collected_at,generated_at
           )
           WITH counts AS (
             SELECT article_date,count(*) AS article_count,sum(topic_count>0) AS categorized_count,
                    sum(summary_text IS NOT NULL) AS summarized_count
             FROM _daily_articles_next GROUP BY article_date
           ), latest AS (SELECT max(article_date) AS article_date FROM counts)
           SELECT counts.article_date,counts.article_count,counts.categorized_count,
                  counts.summarized_count,
                  CASE WHEN counts.article_date=latest.article_date THEN ? ELSE NULL END,?
           FROM counts CROSS JOIN latest""",
        (last_collected_at, generated_at),
    )

    source_row_count = int(conn.execute("SELECT count(*) FROM _daily_articles_next").fetchone()[0])
    topic_count = int(conn.execute("SELECT count(*) FROM _daily_topics_next").fetchone()[0])
    date_count = int(conn.execute("SELECT count(*) FROM _daily_dates_next").fetchone()[0])
    detail_count = int(conn.execute("SELECT count(*) FROM _daily_details_next").fetchone()[0])
    latest = conn.execute("SELECT max(article_date) FROM _daily_dates_next").fetchone()[0]
    if source_row_count and not latest:
        raise RuntimeError("daily article staging has rows but no valid article date")

    if detail_count != source_row_count:
        raise RuntimeError("daily article detail projection parity failed")
    conn.execute("DELETE FROM serving_daily_article_details")
    conn.execute("DELETE FROM serving_daily_article_topics")
    conn.execute("DELETE FROM serving_daily_articles")
    conn.execute("DELETE FROM serving_daily_article_dates")
    conn.execute("INSERT INTO serving_daily_articles SELECT * FROM _daily_articles_next")
    conn.execute("INSERT INTO serving_daily_article_topics SELECT * FROM _daily_topics_next")
    conn.execute("INSERT INTO serving_daily_article_dates SELECT * FROM _daily_dates_next")
    conn.execute("INSERT INTO serving_daily_article_details SELECT * FROM _daily_details_next")

    article_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(serving_daily_articles)"))
    topic_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(serving_daily_article_topics)"))
    date_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(serving_daily_article_dates)"))
    detail_columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(serving_daily_article_details)"))
    article_content_columns = tuple(column for column in article_columns if column != "projection_generated_at")
    date_content_columns = tuple(column for column in date_columns if column != "generated_at")
    digests = {
        "serving_daily_articles": _table_digest(conn, "serving_daily_articles", article_content_columns, ("document_id",)),
        "serving_daily_article_topics": _table_digest(conn, "serving_daily_article_topics", topic_columns, ("document_id", "topic_rank", "term_code")),
        "serving_daily_article_dates": _table_digest(conn, "serving_daily_article_dates", date_content_columns, ("article_date",)),
        "serving_daily_article_details": _table_digest(
            conn, "serving_daily_article_details",
            tuple(column for column in detail_columns if column != "projection_generated_at"),
            ("document_id",),
        ),
    }
    fingerprint_count = 0
    fingerprint_count += _refresh_row_fingerprints(
        conn, dataset_code=DAILY_DATASET, table="serving_daily_articles",
        key_columns=("document_id",), content_columns=article_content_columns, generated_at=generated_at,
    )
    fingerprint_count += _refresh_row_fingerprints(
        conn, dataset_code=DAILY_DATASET, table="serving_daily_article_topics",
        key_columns=("document_id", "term_code"), content_columns=topic_columns, generated_at=generated_at,
    )
    fingerprint_count += _refresh_row_fingerprints(
        conn, dataset_code=DAILY_DATASET, table="serving_daily_article_dates",
        key_columns=("article_date",), content_columns=date_content_columns, generated_at=generated_at,
    )
    fingerprint_count += _refresh_row_fingerprints(
        conn, dataset_code=DAILY_DATASET, table="serving_daily_article_details",
        key_columns=("document_id",),
        content_columns=tuple(column for column in detail_columns if column != "projection_generated_at"),
        generated_at=generated_at,
    )
    digest = _dataset_digest(digests)
    _upsert_freshness(
        conn,
        dataset_code=DAILY_DATASET,
        source_code="GOVERNED_CRE_DOCUMENTS",
        source_as_of_date=str(latest or generated_at[:10]),
        generated_at=generated_at,
        source_row_count=source_row_count,
        serving_row_count=source_row_count,
        content_sha256=digest,
        metadata={
            "articleRows": source_row_count,
            "topicRows": topic_count,
            "dateRows": date_count,
            "detailRows": detail_count,
            "lastCollectedAt": last_collected_at,
            "latestAvailableDate": latest,
        },
    )
    return {
        "status": "READY",
        "articleRows": source_row_count,
        "topicRows": topic_count,
        "dateRows": date_count,
        "detailRows": detail_count,
        "latestAvailableDate": latest,
        "lastCollectedAt": last_collected_at,
        "contentSha256": digest,
        "activeFingerprints": fingerprint_count,
    }


def _latest_completed_snapshots(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    columns = (
        "source_id", "snapshot_id", "snapshot_kind", "source_as_of_date",
        "completed_at", "candidate_count",
    )
    return [
        _row_dict(columns, row)
        for row in conn.execute(
            """WITH ranked AS (
                 SELECT source_id,snapshot_id,snapshot_kind,source_as_of_date,completed_at,
                        candidate_count,
                        row_number() OVER (
                          PARTITION BY source_id ORDER BY completed_at DESC,snapshot_id DESC
                        ) AS rn
                 FROM building_permit_snapshots
                 WHERE status_code='COMPLETED' AND completed_at IS NOT NULL
               )
               SELECT source_id,snapshot_id,snapshot_kind,source_as_of_date,completed_at,
                      candidate_count
               FROM ranked WHERE rn=1 ORDER BY source_id"""
        )
    ]


def refresh_building_permit_serving(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    """Refresh normalized permit marts from completed snapshots only."""
    present = _tables(conn)
    if not PERMIT_RAW_TABLES.issubset(present):
        return {"status": "SKIPPED", "reason": "building permit raw tables are incomplete"}
    required_views = {"v_current_cre_building_permit_records", "v_cre_building_permit_monthly"}
    views = {str(row[0]) for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'")}
    if not required_views.issubset(views):
        return {"status": "SKIPPED", "reason": "building permit governed views are incomplete"}

    conn.executescript("""
        DROP TABLE IF EXISTS temp._permit_current_next;
        DROP TABLE IF EXISTS temp._permit_monthly_next;
        CREATE TEMP TABLE _permit_current_next AS
        SELECT * FROM building_permit_current_serving WHERE 0;
        CREATE TEMP TABLE _permit_monthly_next AS
        SELECT * FROM building_permit_monthly_serving WHERE 0;
    """)
    conn.execute(
        """INSERT INTO _permit_current_next
           SELECT source_id,snapshot_id,record_version_id,source_record_key,revision_no,
                  source_created_date,sigungu_code,bjdong_code,district_name,legal_dong_name,
                  parcel_address,road_address,parcel_type_code,main_lot_number,sub_lot_number,
                  building_name,construction_type,main_use_code,main_use_name,
                  site_area_m2,building_area_m2,total_floor_area_m2,
                  household_count,unit_count,family_count,
                  permit_date,planned_start_date,delayed_start_date,actual_start_date,use_approval_date,
                  first_seen_at,last_seen_at,rule_version,scope_status,asset_type,
                  construction_action,confidence_score,
                  CASE WHEN permit_date IS NULL THEN 'MISSING'
                       WHEN permit_date<'1900-01-01' THEN 'BEFORE_1900'
                       WHEN permit_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
                  CASE WHEN actual_start_date IS NULL THEN 'MISSING'
                       WHEN actual_start_date<'1900-01-01' THEN 'BEFORE_1900'
                       WHEN actual_start_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
                  CASE WHEN use_approval_date IS NULL THEN 'MISSING'
                       WHEN use_approval_date<'1900-01-01' THEN 'BEFORE_1900'
                       WHEN use_approval_date>date('now') THEN 'FUTURE' ELSE 'VALID' END,
                  CASE WHEN total_floor_area_m2 IS NULL THEN 'MISSING'
                       WHEN total_floor_area_m2<0 THEN 'NEGATIVE'
                       WHEN total_floor_area_m2>2000000 THEN 'ABOVE_2M' ELSE 'VALID' END,
                  ?
           FROM v_current_cre_building_permit_records""",
        (generated_at,),
    )
    conn.execute(
        """INSERT INTO _permit_monthly_next
           WITH latest_snapshots AS (
             SELECT source_id,snapshot_id
             FROM (
               SELECT source_id,snapshot_id,
                      row_number() OVER (
                        PARTITION BY source_id ORDER BY completed_at DESC,snapshot_id DESC
                      ) AS rn
               FROM building_permit_snapshots
               WHERE status_code='COMPLETED' AND completed_at IS NOT NULL
             ) WHERE rn=1
           )
           SELECT monthly.source_id,snapshot.snapshot_id,monthly.event_month,
                  monthly.event_type,monthly.district_name,monthly.asset_type,
                  monthly.scope_status,monthly.construction_action,monthly.permit_count,
                  monthly.total_floor_area_m2,monthly.missing_area_count,
                  monthly.invalid_area_count,?
           FROM v_cre_building_permit_monthly monthly
           JOIN latest_snapshots snapshot ON snapshot.source_id=monthly.source_id
           WHERE monthly.event_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
             AND monthly.event_month BETWEEN '1900-01' AND strftime('%Y-%m','now')""",
        (generated_at,),
    )

    current_by_source = {
        str(row[0]): int(row[1])
        for row in conn.execute("SELECT source_id,count(*) FROM _permit_current_next GROUP BY source_id")
    }
    monthly_by_source = {
        str(row[0]): int(row[1])
        for row in conn.execute("SELECT source_id,count(*) FROM _permit_monthly_next GROUP BY source_id")
    }
    snapshots = _latest_completed_snapshots(conn)
    full_snapshot_parity: dict[str, bool | None] = {}
    for snapshot in snapshots:
        source_id = str(snapshot["source_id"])
        full_snapshot_parity[source_id] = (
            current_by_source.get(source_id, 0) == int(snapshot["candidate_count"])
            if snapshot["snapshot_kind"] == "FULL" else None
        )
        if snapshot["snapshot_kind"] == "FULL" and not full_snapshot_parity[source_id]:
            raise RuntimeError(f"permit full-snapshot parity failed for {source_id}")

    conn.execute("DELETE FROM building_permit_current_serving")
    conn.execute("DELETE FROM building_permit_monthly_serving")
    conn.execute("INSERT INTO building_permit_current_serving SELECT * FROM _permit_current_next")
    conn.execute("INSERT INTO building_permit_monthly_serving SELECT * FROM _permit_monthly_next")

    seoul_snapshot = next((row for row in snapshots if row["source_id"] == SEOUL_PERMIT_SOURCE), None)
    seoul_rows = current_by_source.get(SEOUL_PERMIT_SOURCE, 0)
    seoul_monthly = monthly_by_source.get(SEOUL_PERMIT_SOURCE, 0)
    return {
        "status": "READY",
        "latestCompletedSnapshots": snapshots,
        "currentRowsBySource": current_by_source,
        "monthlyRowsBySource": monthly_by_source,
        "fullSnapshotCandidateParity": full_snapshot_parity,
        "seoulSourceAsOfDate": seoul_snapshot["source_as_of_date"] if seoul_snapshot else None,
        "seoulSnapshotId": seoul_snapshot["snapshot_id"] if seoul_snapshot else None,
        "seoulCurrentRows": seoul_rows,
        "seoulMonthlyRows": seoul_monthly,
    }


def refresh_compact_permit_metadata(conn: sqlite3.Connection, generated_at: str) -> dict[str, Any]:
    """Fingerprint the already-built compact permit mart and publish freshness."""
    if "serving_v2_building_permit_monthly" not in _tables(conn):
        return {"status": "SKIPPED", "reason": "compact permit mart is absent"}
    columns = tuple(row[1] for row in conn.execute("PRAGMA table_info(serving_v2_building_permit_monthly)"))
    required = {
        "source_id", "event_month", "event_type", "district_name", "asset_type",
        "scope_status", "construction_action", "permit_count", "total_floor_area_m2",
        "missing_area_count", "invalid_area_count",
    }
    if not required.issubset(columns):
        return {"status": "SKIPPED", "reason": "compact permit mart schema is incompatible"}
    key_columns = (
        "source_id", "event_month", "event_type", "district_name", "asset_type",
        "scope_status", "construction_action",
    )
    seoul_rows = int(conn.execute(
        "SELECT count(*) FROM serving_v2_building_permit_monthly WHERE source_id=? AND scope_status='IN_SCOPE'",
        (SEOUL_PERMIT_SOURCE,),
    ).fetchone()[0])
    source_row_count = int(conn.execute(
        "SELECT count(*) FROM building_permit_current_serving WHERE source_id=?",
        (SEOUL_PERMIT_SOURCE,),
    ).fetchone()[0]) if "building_permit_current_serving" in _tables(conn) else 0
    if seoul_rows == 0 and source_row_count > 0:
        return {
            "status": "SKIPPED",
            "reason": "compact permit mart must be rebuilt after normalized serving refresh",
        }
    snapshot = conn.execute(
        """SELECT source_as_of_date,snapshot_id FROM building_permit_snapshots
           WHERE source_id=? AND status_code='COMPLETED'
           ORDER BY completed_at DESC,snapshot_id DESC LIMIT 1""",
        (SEOUL_PERMIT_SOURCE,),
    ).fetchone() if "building_permit_snapshots" in _tables(conn) else None
    if snapshot is None:
        return {"status": "SKIPPED", "reason": "Seoul completed snapshot metadata is absent"}
    digest = _table_digest(
        conn, "serving_v2_building_permit_monthly", columns,
        key_columns,
    )
    fingerprints = _refresh_row_fingerprints(
        conn, dataset_code=PERMIT_DATASET, table="serving_v2_building_permit_monthly",
        key_columns=key_columns, content_columns=columns, generated_at=generated_at,
    )
    available = conn.execute(
        """SELECT min(event_month),max(event_month),sum(permit_count)
           FROM serving_v2_building_permit_monthly
           WHERE source_id=? AND scope_status='IN_SCOPE'""",
        (SEOUL_PERMIT_SOURCE,),
    ).fetchone()
    _upsert_freshness(
        conn,
        dataset_code=PERMIT_DATASET,
        source_code=SEOUL_PERMIT_SOURCE,
        source_as_of_date=str(snapshot[0]),
        generated_at=generated_at,
        source_row_count=source_row_count,
        serving_row_count=seoul_rows,
        content_sha256=digest,
        metadata={
            "snapshotId": snapshot[1],
            "scopeStatus": "IN_SCOPE",
            "completedSnapshotsOnly": True,
            "dateRule": "ACTUAL_EVENT_DATE_1900_THROUGH_CURRENT",
            "availableFrom": available[0],
            "availableThrough": available[1],
            "permitCount": int(available[2] or 0),
        },
    )
    return {
        "status": "READY",
        "sourceAsOfDate": snapshot[0],
        "snapshotId": snapshot[1],
        "servingRows": seoul_rows,
        "permitCount": int(available[2] or 0),
        "availableFrom": available[0],
        "availableThrough": available[1],
        "contentSha256": digest,
        "activeFingerprints": fingerprints,
    }


def refresh_dashboard_serving(
    conn: sqlite3.Connection,
    *,
    generated_at: str | None = None,
    refresh_compact_metadata: bool = True,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    apply_dashboard_serving_schema(conn)
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        conn.execute("BEGIN IMMEDIATE")
        report = {
            "generatedAt": generated_at,
            "dailyArticles": refresh_daily_article_serving(conn, generated_at),
            "buildingPermits": refresh_building_permit_serving(conn, generated_at),
        }
        if refresh_compact_metadata:
            report["compactPermits"] = refresh_compact_permit_metadata(conn, generated_at)
        violations = conn.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"dashboard serving refresh has {len(violations)} foreign-key violations")
        conn.commit()
        report["foreignKeyViolations"] = 0
        return report
    except Exception:
        conn.rollback()
        raise


def _backup(source: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.chmod(0o666)
        output.unlink()
    with closing(sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)) as src:
        with closing(sqlite3.connect(output)) as dst:
            src.backup(dst)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=root / "data" / "market.db")
    parser.add_argument("--output", type=Path, help="Keep the dry-run candidate at this path")
    parser.add_argument("--report", type=Path, help="Optional JSON report path")
    parser.add_argument("--apply", action="store_true", help="Refresh --source in place")
    args = parser.parse_args()
    source = args.source.resolve()
    if args.apply and args.output:
        parser.error("--output cannot be combined with --apply")

    temporary: tempfile.TemporaryDirectory[str] | None = None
    if args.apply:
        target = source
        mode = "APPLY"
    else:
        mode = "DRY_RUN"
        if args.output:
            target = args.output.resolve()
        else:
            temporary = tempfile.TemporaryDirectory(prefix="cre-dashboard-serving-")
            target = Path(temporary.name) / "candidate.db"
        _backup(source, target)

    try:
        with closing(sqlite3.connect(target)) as conn:
            report = refresh_dashboard_serving(conn)
            integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
            if integrity != "ok":
                raise RuntimeError("dashboard serving candidate failed integrity check")
        report.update(mode=mode, source=str(source), target=str(target), integrity=integrity)
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(_canonical_json(report) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    main()
