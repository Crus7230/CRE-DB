from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
from pathlib import Path

from collector.post_collection_relationships import reconcile_relationships
import re
import sqlite3
import uuid
import xml.etree.ElementTree as ET

from collector.transaction_scope import classify_molit_transaction_scope
from collector.dart_cre_scope import CLASSIFIER_VERSION as DART_CRE_CLASSIFIER_VERSION
from collector.dart_cre_scope import classify_dart_cre_scope


@dataclass(frozen=True)
class DiscoveredDocument:
    canonical_url: str
    external_key: str | None
    title: str | None
    publisher_name: str | None
    published_at: str | None
    snippet_text: str | None
    document_type: str
    rights_status: str
    stored_text: str | None = None
    metadata: dict | None = None


def _iso_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _plain_text(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def month_windows(year: int) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    for month in range(1, 13):
        start = date(year, month, 1)
        end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
        windows.append((start.isoformat(), end.isoformat()))
    return windows


def render_google_query(base_query: str, start_date: str, end_date: str) -> str:
    start = date.fromisoformat(start_date)
    return f"{base_query} after:{(start - timedelta(days=1)).isoformat()} before:{end_date}"


def parse_google_news_rss(xml_bytes: bytes, *, start: datetime, end: datetime) -> list[DiscoveredDocument]:
    root = ET.fromstring(xml_bytes)
    results: list[DiscoveredDocument] = []
    for item in root.findall("./channel/item"):
        published_raw = item.findtext("pubDate")
        if not published_raw:
            continue
        published = parsedate_to_datetime(published_raw)
        if published.tzinfo is None:
            published = published.replace(tzinfo=timezone.utc)
        published = published.astimezone(timezone.utc)
        if not (start <= published < end):
            continue
        source = item.find("source")
        results.append(
            DiscoveredDocument(
                canonical_url=(item.findtext("link") or "").strip(),
                external_key=(item.findtext("guid") or "").strip() or None,
                title=_plain_text(item.findtext("title")),
                publisher_name=_plain_text(source.text if source is not None else None),
                published_at=_iso_z(published),
                snippet_text=_plain_text(item.findtext("description")),
                document_type="RSS_ITEM",
                rights_status="EXCERPT_ALLOWED",
                metadata={"publisher_url": source.get("url") if source is not None else None},
            )
        )
    return results


def parse_dart_filings(
    payload: dict,
    *,
    start: datetime,
    end: datetime,
    report_keywords: tuple[str, ...],
) -> list[DiscoveredDocument]:
    if payload.get("status") != "000":
        raise ValueError(f"OpenDART error status: {payload.get('status')}")
    results: list[DiscoveredDocument] = []
    for item in payload.get("list", []):
        report_name = str(item.get("report_nm") or "").strip()
        if not any(keyword in report_name for keyword in report_keywords):
            continue
        receipt_date = str(item.get("rcept_dt") or "").strip()
        if not re.fullmatch(r"\d{8}", receipt_date):
            continue
        published = datetime.strptime(receipt_date, "%Y%m%d").replace(tzinfo=timezone.utc)
        if not (start <= published < end):
            continue
        receipt_no = str(item.get("rcept_no") or "").strip()
        if not receipt_no:
            continue
        corp_name = str(item.get("corp_name") or "").strip() or None
        filer_name = str(item.get("flr_nm") or "").strip() or None
        results.append(
            DiscoveredDocument(
                canonical_url=f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt_no}",
                external_key=receipt_no,
                title=report_name,
                publisher_name=corp_name,
                published_at=_iso_z(published),
                snippet_text=" | ".join(value for value in (corp_name, report_name, filer_name) if value),
                document_type="DISCLOSURE",
                rights_status="METADATA_ONLY",
                metadata={
                    "corp_code": item.get("corp_code"),
                    "stock_code": item.get("stock_code"),
                    "corp_cls": item.get("corp_cls"),
                    "filer_name": filer_name,
                    "remark": item.get("rm"),
                    "provider": "OpenDART",
                },
            )
        )
    return results


def parse_molit_nrg_trade_xml(
    xml_bytes: bytes,
    *,
    lawd_cd: str,
    deal_ym: str,
) -> list[DiscoveredDocument]:
    root = ET.fromstring(xml_bytes)
    result_code = (root.findtext(".//resultCode") or "").strip()
    if result_code not in {"000", "00"}:
        message = (root.findtext(".//resultMsg") or "unknown error").strip()
        raise ValueError(f"MOLIT RTMS resultCode={result_code}: {message}")

    documents: list[DiscoveredDocument] = []
    record_occurrences: dict[str, int] = {}
    for item in root.findall(".//item"):
        record = {child.tag: (child.text or "").strip() for child in item}
        canonical_record = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        record_hash = hashlib.sha256(canonical_record.encode("utf-8")).hexdigest()
        occurrence = record_occurrences.get(record_hash, 0) + 1
        record_occurrences[record_hash] = occurrence
        external_key = record_hash if occurrence == 1 else f"{record_hash}:{occurrence}"
        try:
            deal_date = date(
                int(record["dealYear"]),
                int(record["dealMonth"]),
                int(record["dealDay"]),
            ).isoformat()
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"invalid MOLIT deal date for record {external_key}") from exc
        sgg = record.get("sggNm", "").strip()
        umd = record.get("umdNm", "").strip()
        use = record.get("buildingUse", "비주거").strip() or "비주거"
        amount = record.get("dealAmount", "").strip()
        title = f"[국토교통부 실거래] {sgg} {umd} {use} 거래"
        if amount:
            title += f" {amount}만원"
        metadata = {
            "api_record": record,
            "query": {"LAWD_CD": lawd_cd, "DEAL_YMD": deal_ym},
            "deal_date": deal_date,
            "date_semantics": "DEAL_DATE_AS_RECORD_DATE",
            "record_identity": "SHA256_CANONICAL_API_RECORD_PLUS_DUPLICATE_OCCURRENCE",
            "duplicate_occurrence": occurrence,
            "source_endpoint": "https://apis.data.go.kr/1613000/RTMSDataSvcNrgTrade/getRTMSDataSvcNrgTrade",
        }
        documents.append(
            DiscoveredDocument(
                external_key=external_key,
                canonical_url=f"molit-rtms://nrg-trade/{external_key}",
                document_type="API_RECORD",
                title=title,
                publisher_name="국토교통부 실거래가 공개시스템",
                published_at=f"{deal_date}T00:00:00Z",
                snippet_text=canonical_record,
                rights_status="FULL_STORAGE_ALLOWED",
                metadata=metadata,
            )
        )
    return documents


@dataclass(frozen=True)
class IngestResult:
    run_id: str
    discovered_count: int
    inserted_count: int
    updated_count: int
    skipped_existing_run: bool


def _stable_id(kind: str, value: str) -> str:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"remi:{kind}:{value}").hex


def _utc_now() -> str:
    return _iso_z(datetime.now(timezone.utc))


def _content_hash(document: DiscoveredDocument) -> str:
    payload = json.dumps(
        {
            "title": document.title,
            "published_at": document.published_at,
            "snippet_text": document.snippet_text,
            "metadata": document.metadata or {},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ingest_partition(
    *,
    db_path: str | Path,
    source_code: str,
    job_code: str,
    category_code: str,
    window_start: str,
    window_end: str,
    query_rendered: str,
    documents: list[DiscoveredDocument],
    runner_version: str,
    cursor_metadata: dict | None = None,
    job_version: int = 1,
    cadence_code: str = "MANUAL",
) -> IngestResult:
    if job_version < 1:
        raise ValueError("job_version must be positive")
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    now = _utc_now()
    cursor = {"window_start": window_start, "window_end": window_end}
    if cursor_metadata:
        cursor.update(cursor_metadata)
    cursor_json = json.dumps(cursor, sort_keys=True)
    try:
        con.execute("BEGIN IMMEDIATE")
        source = con.execute(
            "SELECT source_id FROM collection_sources WHERE source_code = ? AND is_active = 1",
            (source_code,),
        ).fetchone()
        if source is None:
            raise ValueError(f"unknown active source_code: {source_code}")
        category = con.execute(
            "SELECT event_category_id FROM event_categories WHERE code = ? AND is_active = 1",
            (category_code,),
        ).fetchone()
        if category is None:
            raise ValueError(f"unknown active category_code: {category_code}")

        job = con.execute(
            "SELECT job_id FROM collection_jobs WHERE job_code = ? AND job_version = ?",
            (job_code, job_version),
        ).fetchone()
        if job is None:
            job_id = _stable_id("job", f"{job_code}:{job_version}")
            con.execute(
                """INSERT INTO collection_jobs(
                       job_id, job_code, job_version, job_kind, source_id,
                       query_template, cadence_code, config_json, valid_from, is_active
                   ) VALUES (?, ?, ?, 'CATEGORY_SEARCH', ?, ?, ?, ?, ?, 1)""",
                (
                    job_id,
                    job_code,
                    job_version,
                    source[0],
                    query_rendered,
                    cadence_code,
                    json.dumps({
                        "campaign": (
                            re.match(r"^(BACKFILL_\d{4}(?:_H[12])?)", job_code).group(1)
                            if re.match(r"^(BACKFILL_\d{4}(?:_H[12])?)", job_code)
                            else "BACKFILL_2025"
                        )
                    }, sort_keys=True),
                    window_start,
                ),
            )
            con.execute(
                "INSERT INTO collection_job_categories(job_id, event_category_id, is_primary) VALUES (?, ?, 1)",
                (job_id, category[0]),
            )
        else:
            job_id = job[0]

        existing = con.execute(
            """SELECT run_id, discovered_count, inserted_count, updated_count
               FROM collection_runs
               WHERE job_id = ? AND scheduled_for = ? AND query_rendered = ?
                 AND cursor_in = ? AND status_code = 'COMPLETED'
               ORDER BY completed_at DESC LIMIT 1""",
            (job_id, window_start, query_rendered, cursor_json),
        ).fetchone()
        if existing is not None:
            con.commit()
            reconcile_relationships(
                db_path, collection_run_id=existing[0], allow_live=True,
            )
            return IngestResult(
                run_id=existing[0],
                discovered_count=existing[1] or 0,
                inserted_count=existing[2] or 0,
                updated_count=existing[3] or 0,
                skipped_existing_run=True,
            )

        run_id = _stable_id("run", f"{job_id}:{window_start}:{window_end}:{query_rendered}")
        con.execute(
            """INSERT INTO collection_runs(
                   run_id, job_id, scheduled_for, started_at, status_code,
                   query_rendered, cursor_in, runner_version
               ) VALUES (?, ?, ?, ?, 'RUNNING', ?, ?, ?)""",
            (run_id, job_id, window_start, now, query_rendered, cursor_json, runner_version),
        )

        inserted = 0
        updated = 0
        for rank, document in enumerate(documents, 1):
            if not document.canonical_url:
                continue
            row = con.execute(
                "SELECT document_id FROM source_documents WHERE source_id = ? AND canonical_url = ?",
                (source[0], document.canonical_url),
            ).fetchone()
            if row is None:
                document_id = _stable_id("document", f"{source_code}:{document.canonical_url}")
                con.execute(
                    """INSERT INTO source_documents(
                           document_id, source_id, canonical_url, publisher_name,
                           document_type, external_document_key, first_seen_at,
                           last_seen_at, access_status
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ACCESSIBLE')""",
                    (
                        document_id,
                        source[0],
                        document.canonical_url,
                        document.publisher_name,
                        document.document_type,
                        document.external_key,
                        now,
                        now,
                    ),
                )
                inserted += 1
            else:
                document_id = row[0]
                con.execute(
                    "UPDATE source_documents SET last_seen_at = ? WHERE document_id = ?",
                    (now, document_id),
                )

            content_hash = _content_hash(document)
            version = con.execute(
                "SELECT document_version_id FROM document_versions WHERE document_id = ? AND content_sha256 = ?",
                (document_id, content_hash),
            ).fetchone()
            if version is None:
                version_no = con.execute(
                    "SELECT COALESCE(MAX(version_no), 0) + 1 FROM document_versions WHERE document_id = ?",
                    (document_id,),
                ).fetchone()[0]
                version_id = _stable_id("document-version", f"{document_id}:{content_hash}")
                con.execute(
                    """INSERT INTO document_versions(
                           document_version_id, document_id, version_no, title,
                           published_at, collected_at, content_sha256, snippet_text,
                           stored_text, rights_status, metadata_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        version_id,
                        document_id,
                        version_no,
                        document.title,
                        document.published_at,
                        now,
                        content_hash,
                        document.snippet_text,
                        document.stored_text,
                        document.rights_status,
                        json.dumps(document.metadata or {}, ensure_ascii=False, sort_keys=True),
                    ),
                )
                if row is not None:
                    updated += 1
            else:
                version_id = version[0]

            if source_code == "OPENDART":
                scope = classify_dart_cre_scope(document.title, document.stored_text)
                assessment_id = _stable_id(
                    "document-scope-assessment",
                    f"{version_id}:CRE:{DART_CRE_CLASSIFIER_VERSION}",
                )
                evidence = {
                    "reportKind": scope.report_kind,
                    "reasonCodes": list(scope.reason_codes),
                    "assetCategory": scope.asset_category,
                    "assetText": scope.asset_text,
                    "subjectText": scope.subject_text,
                    "detailText": scope.detail_text,
                }
                con.execute(
                    """INSERT INTO document_scope_assessments(
                           document_scope_assessment_id,document_version_id,scope_code,
                           classifier_version,status_code,reason_codes_json,evidence_json,assessed_at
                       ) VALUES (?,?,'CRE',?,?,?,?,?)
                       ON CONFLICT(document_version_id,scope_code,classifier_version) DO UPDATE SET
                           status_code=excluded.status_code,
                           reason_codes_json=excluded.reason_codes_json,
                           evidence_json=excluded.evidence_json,
                           assessed_at=excluded.assessed_at""",
                    (
                        assessment_id, version_id, DART_CRE_CLASSIFIER_VERSION, scope.status,
                        json.dumps(list(scope.reason_codes), ensure_ascii=False),
                        json.dumps(evidence, ensure_ascii=False, sort_keys=True), now,
                    ),
                )

            con.execute(
                """INSERT OR IGNORE INTO run_documents(
                       run_id, document_version_id, result_rank, search_snippet, discovered_at
                   ) VALUES (?, ?, ?, ?, ?)""",
                (run_id, version_id, rank, document.snippet_text, now),
            )

        con.execute(
            """UPDATE collection_runs
               SET completed_at = ?, status_code = 'COMPLETED', discovered_count = ?,
                   inserted_count = ?, updated_count = ?, rejected_count = 0,
                   cursor_out = ?
               WHERE run_id = ?""",
            (now, len(documents), inserted, updated, cursor_json, run_id),
        )
        con.commit()
        reconcile_relationships(
            db_path,
            collection_run_id=run_id,
            allow_live=True,
        )
        return IngestResult(run_id, len(documents), inserted, updated, False)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@dataclass(frozen=True)
class ExtractionResult:
    inserted_extraction_runs: int
    inserted_event_mentions: int


def extract_title_candidates(
    *,
    db_path: str | Path,
    year: int,
    pipeline_version: str,
) -> ExtractionResult:
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    start = f"{year:04d}-01-01"
    end = f"{year + 1:04d}-01-01"
    now = _utc_now()
    inserted_runs = 0
    inserted_mentions = 0
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            """UPDATE event_mentions
               SET status_code = 'REJECTED', rejection_code = 'SUPERSEDED_DOCUMENT_VERSION'
               WHERE status_code IN ('EXTRACTED','RESOLUTION_REQUIRED','REVIEW_READY')
                 AND extraction_run_id IN (
                   SELECT er.extraction_run_id
                   FROM extraction_runs er
                   JOIN document_versions old_v ON old_v.document_version_id = er.document_version_id
                   WHERE er.pipeline_version = ?
                     AND old_v.version_no < (
                       SELECT max(new_v.version_no)
                       FROM document_versions new_v
                       WHERE new_v.document_id = old_v.document_id
                     )
                 )""",
            (pipeline_version,),
        )
        rows = con.execute(
            """SELECT DISTINCT
                       v.document_version_id, v.title, v.snippet_text,
                       s.source_code, ec.event_category_id, ec.code, v.metadata_json
               FROM document_versions v
               JOIN source_documents d ON d.document_id = v.document_id
               JOIN collection_sources s ON s.source_id = d.source_id
               JOIN run_documents rd ON rd.document_version_id = v.document_version_id
               JOIN collection_runs cr ON cr.run_id = rd.run_id
               JOIN collection_jobs j ON j.job_id = cr.job_id
               JOIN collection_job_categories jc ON jc.job_id = j.job_id AND jc.is_primary = 1
               JOIN event_categories ec ON ec.event_category_id = jc.event_category_id
               WHERE cr.status_code = 'COMPLETED'
                 AND v.published_at >= ? AND v.published_at < ?
                 AND v.version_no = (
                   SELECT max(latest_v.version_no)
                   FROM document_versions latest_v
                   WHERE latest_v.document_id = v.document_id
                 )
               ORDER BY v.document_version_id, ec.code""",
            (start, end),
        ).fetchall()
        extraction_ids: dict[str, str] = {}
        rule_hash = hashlib.sha256(b"title-category-candidate-v1").hexdigest()
        for document_version_id, title, snippet, source_code, category_id, category_code, metadata_json in rows:
            extraction_id = extraction_ids.get(document_version_id)
            if extraction_id is None:
                existing = con.execute(
                    "SELECT extraction_run_id FROM extraction_runs WHERE document_version_id = ? AND pipeline_version = ?",
                    (document_version_id, pipeline_version),
                ).fetchone()
                if existing is None:
                    extraction_id = _stable_id("extraction", f"{document_version_id}:{pipeline_version}")
                    con.execute(
                        """INSERT INTO extraction_runs(
                               extraction_run_id, document_version_id, pipeline_version,
                               offset_basis, model_name, prompt_or_rule_hash,
                               started_at, completed_at, status_code
                           ) VALUES (?, ?, ?, 'UNICODE_CODEPOINT', 'TITLE_CATEGORY_RULE', ?, ?, ?, 'COMPLETED')""",
                        (extraction_id, document_version_id, pipeline_version, rule_hash, now, now),
                    )
                    inserted_runs += 1
                else:
                    extraction_id = existing[0]
                extraction_ids[document_version_id] = extraction_id

            extraction_key = f"title-category:{category_code}"
            mention_id = _stable_id("event-mention", f"{extraction_id}:{extraction_key}")
            confidence = 0.75 if source_code == "OPENDART" else 0.40
            status_code = "EXTRACTED"
            rejection_code = None
            if source_code == "MOLIT_REAL_TRANSACTION":
                record = json.loads(metadata_json or "{}").get("api_record", {})
                scope = classify_molit_transaction_scope(record)
                if scope.status == "EXCLUDED":
                    status_code = "REJECTED"
                    rejection_code = scope.reason_code
                elif scope.status == "REVIEW_REQUIRED":
                    status_code = "REVIEW_READY"
            cursor = con.execute(
                """INSERT OR IGNORE INTO event_mentions(
                       event_mention_id, extraction_run_id, extraction_key,
                       event_category_id, title_raw, summary_raw,
                       confidence, status_code, rejection_code
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    mention_id, extraction_id, extraction_key, category_id,
                    title, snippet, confidence, status_code, rejection_code,
                ),
            )
            if cursor.rowcount:
                inserted_mentions += 1
        con.commit()
        reconcile_relationships(db_path, allow_live=True)
        return ExtractionResult(inserted_runs, inserted_mentions)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


@dataclass(frozen=True)
class MacroDerivationResult:
    inserted_series: int
    inserted_releases: int
    inserted_observations: int


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def derive_molit_seoul_monthly_macro(
    *,
    db_path: str | Path,
    year: int,
) -> MacroDerivationResult:
    con = sqlite3.connect(str(db_path))
    con.execute("PRAGMA foreign_keys = ON")
    con.execute("PRAGMA busy_timeout = 5000")
    inserted_series = 0
    inserted_releases = 0
    inserted_observations = 0
    now = _utc_now()
    try:
        con.execute("BEGIN IMMEDIATE")
        source_row = con.execute(
            "SELECT source_id FROM collection_sources WHERE source_code = 'MOLIT_REAL_TRANSACTION' AND is_active = 1"
        ).fetchone()
        if source_row is None:
            raise ValueError("unknown active source_code: MOLIT_REAL_TRANSACTION")
        source_id = source_row[0]
        region_row = con.execute(
            "SELECT region_id FROM regions WHERE legal_dong_code = '11' AND region_type = 'SIDO'"
        ).fetchone()
        region_id = region_row[0] if region_row else None

        rows = con.execute(
            """SELECT d.external_document_key, v.metadata_json
               FROM source_documents d
               JOIN collection_sources s ON s.source_id = d.source_id
               JOIN document_versions v ON v.document_id = d.document_id
               WHERE s.source_code = 'MOLIT_REAL_TRANSACTION'
                 AND v.version_no = (
                   SELECT max(v2.version_no) FROM document_versions v2 WHERE v2.document_id = d.document_id
                 )"""
        ).fetchall()
        aggregates: dict[str, dict] = {}
        for external_key, metadata_json in rows:
            metadata = json.loads(metadata_json or "{}")
            record = metadata.get("api_record") or {}
            if str(record.get("dealYear", "")) != str(year):
                continue
            if not str(record.get("sggCd", "")).startswith("11"):
                continue
            if str(record.get("cdealDay", "")).strip():
                continue
            if classify_molit_transaction_scope(record).status != "IN_SCOPE":
                continue
            try:
                month = int(record["dealMonth"])
                amount_krw = Decimal(str(record["dealAmount"]).replace(",", "")) * Decimal("10000")
                area_m2 = Decimal(str(record.get("buildingAr") or "0"))
            except (KeyError, InvalidOperation, TypeError, ValueError):
                continue
            if month < 1 or month > 12:
                continue
            ym = f"{year:04d}{month:02d}"
            agg = aggregates.setdefault(
                ym,
                {"count": 0, "amount_krw": Decimal("0"), "area_m2": Decimal("0"), "record_keys": []},
            )
            agg["count"] += 1
            agg["amount_krw"] += amount_krw
            agg["area_m2"] += area_m2
            agg["record_keys"].append(external_key)

        series_specs = (
            (
                "MOLIT_SEOUL_NRG_TRADE_COUNT", "서울 비주거용 부동산 실거래 건수",
                "TRANSACTION_COUNT", "COUNT",
                "국토교통부 비주거용 부동산 실거래 공개 레코드 중 주거용을 제외하고 건물면적 3,300㎡ 초과이며 취소일이 없는 서울특별시 거래의 월별 건수 합계.",
                "count",
            ),
            (
                "MOLIT_SEOUL_NRG_TRADE_AMOUNT_KRW", "서울 비주거용 부동산 실거래 금액",
                "TRANSACTION_AMOUNT", "KRW",
                "국토교통부 비주거용 부동산 실거래 공개 레코드 중 주거용을 제외하고 건물면적 3,300㎡ 초과이며 취소일이 없는 서울특별시 거래금액의 월별 합계. 원 단위 환산.",
                "amount_krw",
            ),
            (
                "MOLIT_SEOUL_NRG_BUILDING_AREA_M2", "서울 비주거용 부동산 실거래 건물면적",
                "TRANSACTED_BUILDING_AREA", "M2",
                "국토교통부 비주거용 부동산 실거래 공개 레코드 중 주거용을 제외하고 건물면적 3,300㎡ 초과이며 취소일이 없는 서울특별시 건물면적의 월별 합계.",
                "area_m2",
            ),
        )
        series_ids: dict[str, str] = {}
        for code, name, metric, unit, definition, _field in series_specs:
            series_id = _stable_id("macro-series", code)
            cursor = con.execute(
                """INSERT OR IGNORE INTO macro_series(
                       macro_series_id, series_code, series_name_ko, metric_code,
                       source_id, external_series_key, frequency_code, unit_code,
                       region_id, adjustment_code, aggregation_code, definition_text,
                       valid_from, is_active, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, 'MONTHLY', ?, ?, 'NOMINAL', 'SUM', ?, ?, 1, ?)""",
                (
                    series_id, code, name, metric, source_id, code, unit, region_id,
                    definition, f"{year:04d}-01-01",
                    json.dumps({
                        "derivation": "MOLIT_RTMS_NRG_SEOUL_SUM_V2",
                        "cancelled_records_excluded": True,
                        "residential_use_excluded": True,
                        "building_area_rule": "buildingAr > 3300 m2",
                    }, ensure_ascii=False),
                ),
            )
            inserted_series += int(bool(cursor.rowcount))
            con.execute(
                """UPDATE macro_series
                   SET definition_text = ?, metadata_json = ?
                   WHERE series_code = ?""",
                (
                    definition,
                    json.dumps({
                        "derivation": "MOLIT_RTMS_NRG_SEOUL_SUM_V2",
                        "cancelled_records_excluded": True,
                        "residential_use_excluded": True,
                        "building_area_rule": "buildingAr > 3300 m2",
                    }, ensure_ascii=False),
                    code,
                ),
            )
            series_ids[code] = con.execute(
                "SELECT macro_series_id FROM macro_series WHERE series_code = ?", (code,)
            ).fetchone()[0]

        for ym, agg in sorted(aggregates.items()):
            month = int(ym[4:6])
            period_start = date(year, month, 1)
            next_start = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
            period_end = next_start - timedelta(days=1)
            artifact_payload = {
                "year_month": ym,
                "record_keys": sorted(agg["record_keys"]),
                "count": agg["count"],
                "amount_krw": _decimal_text(agg["amount_krw"]),
                "area_m2": _decimal_text(agg["area_m2"]),
            }
            artifact_json = json.dumps(artifact_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            artifact_sha = hashlib.sha256(artifact_json.encode("utf-8")).hexdigest()
            release_key = f"DERIVED:MOLIT_RTMS:SEOUL:{ym}"
            release_id = _stable_id("macro-release", f"{release_key}:{artifact_sha}")
            cursor = con.execute(
                """INSERT OR IGNORE INTO macro_releases(
                       macro_release_id, source_id, publisher_release_key, release_title,
                       released_at, effective_date, artifact_sha256, artifact_uri,
                       publisher_revision_no, revises_release_id, first_collected_at,
                       source_document_version_id, metadata_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    release_id, source_id, release_key, f"서울 비주거용 부동산 실거래 {ym}",
                    None, period_end.isoformat(), artifact_sha,
                    f"derived://molit-rtms/seoul/{ym}", None, None, now, None,
                    json.dumps({"derived": True, "input_record_count": agg["count"]}, ensure_ascii=False),
                ),
            )
            inserted_releases += int(bool(cursor.rowcount))
            release_id = con.execute(
                """SELECT macro_release_id FROM macro_releases
                   WHERE source_id = ? AND publisher_release_key = ? AND artifact_sha256 = ?""",
                (source_id, release_key, artifact_sha),
            ).fetchone()[0]

            for code, _name, _metric, unit, _definition, field in series_specs:
                series_id = series_ids[code]
                existing = con.execute(
                    """SELECT macro_observation_id FROM macro_observations
                       WHERE macro_series_id = ? AND period_start = ? AND period_end = ? AND macro_release_id = ?""",
                    (series_id, period_start.isoformat(), period_end.isoformat(), release_id),
                ).fetchone()
                if existing:
                    continue
                value = Decimal(agg[field]) if field == "count" else agg[field]
                value_text = _decimal_text(value)
                previous = con.execute(
                    """SELECT macro_observation_id, revision_no
                       FROM macro_observations
                       WHERE macro_series_id = ? AND period_start = ? AND period_end = ?
                       ORDER BY revision_no DESC, collected_at DESC LIMIT 1""",
                    (series_id, period_start.isoformat(), period_end.isoformat()),
                ).fetchone()
                revision_no = (previous[1] + 1) if previous else 0
                status = "REVISED" if previous else "FINAL"
                supersedes = previous[0] if previous else None
                row_payload = {
                    "series_code": code, "period_start": period_start.isoformat(),
                    "period_end": period_end.isoformat(), "value": value_text,
                    "unit": unit, "artifact_sha256": artifact_sha,
                }
                row_sha = hashlib.sha256(
                    json.dumps(row_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                observation_id = _stable_id("macro-observation", f"{series_id}:{release_id}:{row_sha}")
                cursor = con.execute(
                    """INSERT OR IGNORE INTO macro_observations(
                           macro_observation_id, macro_series_id, macro_release_id,
                           period_start, period_end, period_label, observed_on,
                           numeric_value, value_decimal_text, text_value, unit_code,
                           collected_at, vintage_at, revision_no, observation_status,
                           source_document_version_id, source_record_key, raw_value,
                           row_sha256, supersedes_observation_id, metadata_json
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        observation_id, series_id, release_id,
                        period_start.isoformat(), period_end.isoformat(), ym, period_end.isoformat(),
                        float(value), value_text, None, unit, now, now, revision_no, status,
                        None, artifact_sha, value_text, row_sha, supersedes,
                        json.dumps({"derivation": "MOLIT_RTMS_NRG_SEOUL_SUM_V1"}, ensure_ascii=False),
                    ),
                )
                inserted_observations += int(bool(cursor.rowcount))
        con.commit()
        return MacroDerivationResult(inserted_series, inserted_releases, inserted_observations)
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
