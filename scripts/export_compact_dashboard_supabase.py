#!/usr/bin/env python3
"""Build an immutable, dashboard-only Supabase load package from market.db.

The default ``plan`` command is read-only and prints row counts, content hashes,
and an upload-size estimate.  ``export`` writes gzip JSONL files plus a manifest
to a new immutable directory.  The source is always opened read-only inside one
SQLite transaction so concurrent collectors cannot produce a mixed snapshot.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import unicodedata
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "market.db"
DEFAULT_OUTPUT_ROOT = ROOT / "artifacts" / "supabase-compact"
PULSE_QUERY_SOURCE = ROOT / "web" / "src" / "lib" / "server" / "quantitative-market-pulse.ts"
SCHEMA_VERSION = "1.1.0"
PACKAGE_VERSION = "1.1.0"
DATASET_CODES = (
    "DAILY_ARTICLES",
    "FINANCIAL_MACRO",
    "MOLIT_TRANSACTIONS",
    "SEOUL_BUILDING_PERMITS",
)
EXPECTED_MACRO_CODES = (
    "BOK_BASE_RATE_MONTHLY",
    "KR_CD_91D",
    "KR_GOVT_BOND_3Y",
    "KR_GOVT_BOND_10Y",
    "KR_CORP_BOND_AA_MINUS_3Y",
    "US_FED_TARGET_LOWER",
    "US_FED_TARGET_UPPER",
    "US_EFFR",
    "US_SOFR",
    "US_TREASURY_2Y",
    "US_TREASURY_10Y",
    "US_TREASURY_30Y",
    "US_TREASURY_10Y_MINUS_2Y",
)


class CompactExportError(RuntimeError):
    """Raised when the source cannot satisfy the compact serving contract."""


@contextmanager
def consistent_source(path: Path) -> Iterator[sqlite3.Connection]:
    resolved = path.expanduser().resolve(strict=True)
    if not resolved.is_file():
        raise CompactExportError(f"Source is not a regular file: {resolved}")
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN")
        connection.execute("SELECT count(*) FROM sqlite_schema").fetchone()
        yield connection
    finally:
        if connection.in_transaction:
            connection.rollback()
        connection.close()


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def parsed_json(value: Any, *, label: str) -> Any:
    if not isinstance(value, str):
        raise CompactExportError(f"{label} is not JSON text")
    try:
        return json.loads(value)
    except json.JSONDecodeError as error:
        raise CompactExportError(f"{label} contains invalid JSON") from error


def _flatten_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        if value.strip():
            yield value
    elif isinstance(value, Mapping):
        for key in sorted(value):
            yield from _flatten_strings(value[key])
    elif isinstance(value, list):
        for item in value:
            yield from _flatten_strings(item)


def normalize_search_text(values: Iterable[str], *, maximum: int = 32_768) -> str:
    seen: set[str] = set()
    parts: list[str] = []
    for raw in values:
        normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", raw)).strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        parts.append(normalized)
    return " ".join(parts)[:maximum]


def _query_rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql)]


def article_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    details: dict[str, dict[str, Any]] = {}
    for row in connection.execute(
        "SELECT document_id,payload_json FROM serving_daily_article_details"
    ):
        payload = parsed_json(row["payload_json"], label=f"article detail {row['document_id']}")
        if not isinstance(payload, dict):
            raise CompactExportError(f"article detail {row['document_id']} is not an object")
        details[str(row["document_id"])] = payload

    topic_labels: dict[str, list[str]] = defaultdict(list)
    for row in connection.execute(
        """SELECT document_id,term_code,term_label
           FROM serving_daily_article_topics ORDER BY document_id,topic_rank,term_code"""
    ):
        topic_labels[str(row["document_id"])].extend(
            [str(row["term_code"]), str(row["term_label"])]
        )

    rows: list[dict[str, Any]] = []
    for source in connection.execute(
        "SELECT * FROM serving_daily_articles ORDER BY document_id"
    ):
        row = dict(source)
        document_id = str(row["document_id"])
        payload = details.get(document_id)
        if payload is None:
            raise CompactExportError(f"article {document_id} has no detail payload")
        evidence = next(
            (
                str(candidate).strip()
                for candidate in (
                    payload.get("safeExcerpt"),
                    row.get("summary_text"),
                    payload.get("summary"),
                    payload.get("snippet"),
                    payload.get("storedText"),
                    row.get("title"),
                )
                if isinstance(candidate, str) and candidate.strip()
            ),
            str(row["title"]),
        )[:2_000]
        searchable = [
            str(row["title"]),
            str(row.get("publisher_name") or ""),
            str(row.get("summary_text") or ""),
            evidence,
            *topic_labels.get(document_id, []),
            *_flatten_strings(payload.get("keywords", [])),
            *_flatten_strings(payload.get("eventSignals", [])),
            *_flatten_strings(payload.get("relatedEntities", [])),
        ]
        row["evidence_text"] = evidence
        row["search_text"] = normalize_search_text(searchable)
        rows.append(row)
    return rows


def article_topic_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _query_rows(
        connection,
        "SELECT * FROM serving_daily_article_topics ORDER BY document_id,term_code",
    )
    for row in rows:
        row["is_primary"] = bool(row["is_primary"])
    return rows


def article_detail_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _query_rows(
        connection,
        """SELECT document_id,document_version_id,payload_json,projection_generated_at
           FROM serving_daily_article_details ORDER BY document_id""",
    )
    for row in rows:
        row["payload"] = parsed_json(row.pop("payload_json"), label=f"article {row['document_id']}")
    return rows


def article_search_document_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for article in article_rows(connection):
        terms: set[str] = set()
        for word in re.findall(r"[0-9a-z가-힣]{2,160}", article["search_text"]):
            # Trigrams cover queries of 3+ characters.  This compact side index
            # exists only so two-character Korean/ASCII literals avoid a scan.
            terms.update(word[index : index + 2] for index in range(len(word) - 1))
        rows.append(
            {
                "document_id": article["document_id"],
                "terms": sorted(terms),
            }
        )
    rows.sort(key=lambda row: row["document_id"])
    return rows


def macro_series_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _query_rows(
        connection,
        """SELECT series.*,source.source_name
           FROM macro_series series
           LEFT JOIN collection_sources source ON source.source_id=series.source_id
           ORDER BY series.macro_series_id""",
    )
    for row in rows:
        row["is_active"] = bool(row["is_active"])
        row["metadata"] = parsed_json(
            row.pop("metadata_json"), label=f"macro series {row['series_code']}"
        )
    return rows


def macro_monthly_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _query_rows(
        connection,
        """SELECT * FROM financial_macro_monthly_serving
           ORDER BY series_code,observation_month""",
    )


def permit_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    return _query_rows(
        connection,
        """SELECT source_id,event_month,event_type,district_name,asset_type,
                  construction_action,permit_count,total_floor_area_m2,
                  missing_area_count,invalid_area_count
           FROM serving_v2_building_permit_monthly
           WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
           ORDER BY event_month,event_type,district_name,asset_type,construction_action""",
    )


def _extract_market_pulse_query() -> tuple[str, str]:
    source = PULSE_QUERY_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"const QUERY = `(.*?)`;\s*\n", source, re.DOTALL)
    if match is None or "${" in match.group(1):
        raise CompactExportError("Cannot extract the static market pulse SQL contract")
    sql = match.group(1)
    return sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()


def _previous_month(period: str) -> str:
    year, month = map(int, period.split("-"))
    return f"{year - 1}-12" if month == 1 else f"{year}-{month - 1:02d}"


def _pct(current: float, comparison: float | None) -> float | None:
    return None if comparison in (None, 0) else (current / comparison - 1) * 100


def _metric(points: Sequence[dict[str, Any]], field: str) -> dict[str, Any]:
    latest = points[-1]
    previous = next((point for point in points if point["period"] == _previous_month(latest["period"])), None)
    year, month = map(int, latest["period"].split("-"))
    year_ago = next(
        (point for point in points if point["period"] == f"{year - 1}-{month:02d}"), None
    )
    value = float(latest[field])
    previous_value = None if previous is None else float(previous[field])
    year_ago_value = None if year_ago is None else float(year_ago[field])
    current_ytd = [p for p in points if p["period"].startswith(f"{year}-") and int(p["period"][5:]) <= month]
    prior_ytd = [p for p in points if p["period"].startswith(f"{year - 1}-") and int(p["period"][5:]) <= month]
    expected = {f"{candidate:02d}" for candidate in range(1, month + 1)}
    current_complete = expected.issubset({p["period"][5:] for p in current_ytd})
    prior_complete = expected.issubset({p["period"][5:] for p in prior_ytd})
    current_sum = sum(float(p[field]) for p in current_ytd) if current_complete else None
    prior_sum = sum(float(p[field]) for p in prior_ytd) if prior_complete else None
    if field == "transactionCount":
        value = int(value)
        previous_value = None if previous_value is None else int(previous_value)
        year_ago_value = None if year_ago_value is None else int(year_ago_value)
        current_sum = None if current_sum is None else int(current_sum)
        prior_sum = None if prior_sum is None else int(prior_sum)
    return {
        "value": value,
        "previousValue": previous_value,
        "yearAgoValue": year_ago_value,
        "momPct": _pct(float(value), None if previous_value is None else float(previous_value)),
        "yoyPct": _pct(float(value), None if year_ago_value is None else float(year_ago_value)),
        "ytdValue": current_sum,
        "priorYtdValue": prior_sum,
        "ytdYoyPct": None if current_sum is None else _pct(current_sum, prior_sum),
    }


def _ratio(numerator: float, denominator: float) -> float | None:
    return None if denominator == 0 else numerator / denominator


def _point_metric(
    value: float | None,
    previous: float | None,
    year_ago: float | None,
) -> dict[str, float | None]:
    return {
        "value": value,
        "previousValue": previous,
        "yearAgoValue": year_ago,
        "momPct": None if value is None else _pct(value, previous),
        "yoyPct": None if value is None else _pct(value, year_ago),
    }


def _direction(value: float) -> str:
    if value >= 0.05:
        return "증가"
    if value <= -0.05:
        return "감소"
    return "보합"


def build_market_pulse(raw: dict[str, Any]) -> dict[str, Any]:
    trend = raw.get("trend")
    analysis = raw.get("analysisTrend")
    coverage = raw.get("coverage")
    if not isinstance(trend, list) or not trend or not isinstance(analysis, list) or not analysis:
        raise CompactExportError("Market pulse has no complete trend")
    if not isinstance(coverage, dict) or int(coverage.get("expectedDistrictCount", 0)) != 25:
        raise CompactExportError("Market pulse coverage is not the governed 25-district scope")
    if trend[-1].get("period") != raw.get("asOfPeriod"):
        raise CompactExportError("Market pulse reference month does not match its trend")
    amount = _metric(analysis, "amountKrw")
    count = _metric(analysis, "transactionCount")
    area = _metric(analysis, "areaM2")
    latest = trend[-1]
    previous = next((p for p in analysis if p["period"] == _previous_month(latest["period"])), None)
    year, month = map(int, latest["period"].split("-"))
    year_ago = next((p for p in analysis if p["period"] == f"{year - 1}-{month:02d}"), None)
    average = _ratio(float(amount["value"]), float(count["value"]))
    previous_average = None if previous is None else _ratio(float(previous["amountKrw"]), float(previous["transactionCount"]))
    year_ago_average = None if year_ago is None else _ratio(float(year_ago["amountKrw"]), float(year_ago["transactionCount"]))
    unit_amount = _ratio(float(amount["value"]), float(area["value"]))
    previous_unit = None if previous is None else _ratio(float(previous["amountKrw"]), float(previous["areaM2"]))
    year_ago_unit = None if year_ago is None else _ratio(float(year_ago["amountKrw"]), float(year_ago["areaM2"]))
    amount_mom = amount["momPct"]
    count_mom = count["momPct"]
    if amount_mom is None or count_mom is None:
        headline = "전월 비교 불가 — 검증된 기준월 또는 전월 없음"
    else:
        amount_direction, count_direction = _direction(amount_mom), _direction(count_mom)
        headline = (
            f"신고 거래금액과 고유 신고행 전월 대비 {amount_direction}"
            if amount_direction == count_direction
            else f"신고 거래금액 {amount_direction} · 고유 신고행 {count_direction}"
        )
    average_mom = None if average is None else _pct(average, previous_average)
    average_detail = "비교 불가" if average_mom is None else f"{average_mom:+.1f}%"
    coverage_complete = bool(coverage.get("coverageComplete"))
    coverage_detail = "" if coverage_complete else f" · 검증 완료 {int(coverage['returnedMonthCount'])}개월만 표시"
    coverage_caution = "" if coverage_complete else f" 과거 {int(coverage['excludedMonthCount'])}개월은 25개 자치구 기준선이 완결되지 않아 추이와 비교 계산에서 제외했습니다."
    return {
        "generatedAt": raw["generatedAt"],
        "asOfPeriod": raw["asOfPeriod"],
        "call": {
            "headline": headline,
            "detail": (
                f"신고 거래금액 {'비교 불가' if amount_mom is None else f'{amount_mom:+.1f}%'} · "
                f"고유 신고행 {'비교 불가' if count_mom is None else f'{count_mom:+.1f}%'} · "
                f"신고행당 평균 {average_detail}{coverage_detail}"
            ),
            "caution": f"면적당 금액은 자산구성 변화의 영향을 받으므로 동일자산 가격지수로 해석하지 않습니다.{coverage_caution}",
        },
        "metrics": {
            "amount": amount,
            "count": count,
            "area": area,
            "averageTicket": _point_metric(average, previous_average, year_ago_average),
            "unitAmount": _point_metric(unit_amount, previous_unit, year_ago_unit),
        },
        "trend": trend,
        "concentration": {
            "topGroups": raw.get("latestGroups", []),
            "districts": raw.get("districts", []),
        },
        "quality": {
            "sourceRowCount": int(latest["sourceRowCount"]),
            "transactionCount": int(latest["transactionCount"]),
            "uniquePayloadCount": int(latest["uniquePayloadCount"]),
            "exactDuplicateRows": int(latest["sourceRowCount"]) - int(latest["uniquePayloadCount"]),
        },
        "scope": {
            "geography": "서울특별시",
            "source": "국토교통부 실거래 공개시스템",
            "population": "용도가 확인된 비주거용 부동산 실거래",
            "areaRule": "개별 API 행 건물면적 > 3,300㎡",
            "exclusions": ["취소 신고", "주거용", "용도 미상", "동일 API payload 중복"],
            "amountBasis": "신고 거래금액 · 원 단위 환산 · 보수적 canonical payload 행 기준",
        },
    }


def market_pulse_rows(connection: sqlite3.Connection) -> tuple[list[dict[str, Any]], str]:
    sql, query_sha256 = _extract_market_pulse_query()
    row = connection.execute(sql).fetchone()
    if row is None:
        raise CompactExportError("Market pulse query returned no row")
    raw = parsed_json(row["payload"], label="market pulse")
    if not isinstance(raw, dict):
        raise CompactExportError("Market pulse payload is not an object")
    freshness = connection.execute(
        """SELECT generated_at FROM serving_dataset_freshness
           WHERE dataset_code='MOLIT_TRANSACTIONS'"""
    ).fetchone()
    if freshness is None:
        raise CompactExportError("MOLIT freshness row is missing")
    raw["generatedAt"] = freshness[0]
    payload = build_market_pulse(raw)
    return [
        {
            "as_of_period": f"{payload['asOfPeriod']}-01",
            "payload": payload,
            "source_content_sha256": sha256_json(raw),
            "generated_at": payload["generatedAt"],
        }
    ], query_sha256


def lineage_rows(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = _query_rows(
        connection,
        """SELECT dataset_code,source_code,source_as_of_date,generated_at,
                  source_status_code,source_row_count,serving_row_count,
                  content_sha256,metadata_json
           FROM serving_dataset_freshness
           WHERE dataset_code IN ('DAILY_ARTICLES','FINANCIAL_MACRO',
                                  'MOLIT_TRANSACTIONS','SEOUL_BUILDING_PERMITS')
           ORDER BY dataset_code""",
    )
    if [row["dataset_code"] for row in rows] != sorted(DATASET_CODES):
        missing = sorted(set(DATASET_CODES) - {row["dataset_code"] for row in rows})
        raise CompactExportError(f"Missing dataset freshness rows: {missing}")
    for row in rows:
        row["source_content_sha256"] = row.pop("content_sha256")
        row["metadata"] = parsed_json(
            row.pop("metadata_json"), label=f"freshness {row['dataset_code']}"
        )
    return rows


def _facets(connection: sqlite3.Connection, pulse: dict[str, Any]) -> dict[str, Any]:
    news_range = connection.execute(
        "SELECT min(article_date),max(article_date),sum(article_count) FROM serving_daily_article_dates"
    ).fetchone()
    macro_range = connection.execute(
        """SELECT min(observation_month),max(observation_month),count(*)
           FROM financial_macro_monthly_serving"""
    ).fetchone()
    permit_range = connection.execute(
        """SELECT min(event_month),max(event_month),count(*)
           FROM serving_v2_building_permit_monthly
           WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'"""
    ).fetchone()
    return {
        "news": {
            "availableFrom": news_range[0],
            "availableThrough": news_range[1],
            "articleCount": int(news_range[2] or 0),
            "topics": [
                {"key": row[0], "label": row[1], "count": int(row[2])}
                for row in connection.execute(
                    """SELECT term_code,max(term_label),count(*)
                       FROM serving_daily_article_topics GROUP BY term_code ORDER BY term_code"""
                )
            ],
            "publishers": [
                {"key": row[0], "count": int(row[1])}
                for row in connection.execute(
                    """SELECT publisher_name,count(*) FROM serving_daily_articles
                       WHERE publisher_name IS NOT NULL GROUP BY publisher_name
                       ORDER BY count(*) DESC,publisher_name"""
                )
            ],
        },
        "macro": {
            "availableFrom": macro_range[0],
            "availableThrough": macro_range[1],
            "observationCount": int(macro_range[2]),
            "seriesCodes": [row[0] for row in connection.execute(
                "SELECT series_code FROM macro_series WHERE is_active=1 ORDER BY series_code"
            )],
            "dashboardSeriesCodes": list(EXPECTED_MACRO_CODES),
        },
        "permits": {
            "availableFrom": permit_range[0],
            "availableThrough": permit_range[1],
            "aggregateRowCount": int(permit_range[2]),
            "eventTypes": [row[0] for row in connection.execute(
                """SELECT DISTINCT event_type FROM serving_v2_building_permit_monthly
                   WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
                   ORDER BY event_type"""
            )],
            "assetTypes": [row[0] for row in connection.execute(
                """SELECT DISTINCT asset_type FROM serving_v2_building_permit_monthly
                   WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
                   ORDER BY asset_type"""
            )],
            "districts": [row[0] for row in connection.execute(
                """SELECT DISTINCT district_name FROM serving_v2_building_permit_monthly
                   WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
                   ORDER BY district_name"""
            )],
            "constructionActions": [row[0] for row in connection.execute(
                """SELECT DISTINCT construction_action FROM serving_v2_building_permit_monthly
                   WHERE source_id='src_seoul_building_permit' AND scope_status='IN_SCOPE'
                   ORDER BY construction_action"""
            )],
        },
        "marketPulse": {
            "asOfPeriod": pulse["asOfPeriod"],
            "scope": pulse["scope"],
            "quality": pulse["quality"],
        },
    }


TABLE_BUILDERS: tuple[tuple[str, Callable[[sqlite3.Connection], list[dict[str, Any]]]], ...] = (
    (
        "article_dates",
        lambda connection: _query_rows(
            connection, "SELECT * FROM serving_daily_article_dates ORDER BY article_date"
        ),
    ),
    ("articles", article_rows),
    ("article_topics", article_topic_rows),
    ("article_details", article_detail_rows),
    ("article_search_documents", article_search_document_rows),
    ("macro_series", macro_series_rows),
    ("macro_monthly", macro_monthly_rows),
    ("permit_monthly", permit_rows),
)


def _table_stats(
    rows: Sequence[dict[str, Any]],
    *,
    destination: Path | None,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    uncompressed_bytes = 0
    compressed_bytes: int | None = None
    handle = gzip.open(destination, "xt", encoding="utf-8", newline="\n", compresslevel=9) if destination else None
    try:
        for row in rows:
            line = canonical_json(row) + "\n"
            encoded = line.encode("utf-8")
            digest.update(encoded)
            uncompressed_bytes += len(encoded)
            if handle is not None:
                handle.write(line)
    finally:
        if handle is not None:
            handle.close()
    if destination is not None:
        compressed_bytes = destination.stat().st_size
    return {
        "rowCount": len(rows),
        "contentSha256": digest.hexdigest(),
        "uncompressedBytes": uncompressed_bytes,
        "compressedBytes": compressed_bytes,
        "file": None if destination is None else destination.name,
    }


def _source_metadata(connection: sqlite3.Connection, source: Path) -> dict[str, Any]:
    stat = source.stat()
    return {
        "path": str(source.resolve()),
        "bytes": stat.st_size,
        "mtimeNs": stat.st_mtime_ns,
        "schemaVersion": int(connection.execute("PRAGMA schema_version").fetchone()[0]),
        "dataVersion": int(connection.execute("PRAGMA data_version").fetchone()[0]),
        "pageCount": int(connection.execute("PRAGMA page_count").fetchone()[0]),
        "pageSize": int(connection.execute("PRAGMA page_size").fetchone()[0]),
        "journalMode": str(connection.execute("PRAGMA journal_mode").fetchone()[0]),
        "openedMode": "ro",
        "consistentReadTransaction": True,
    }


def serving_identity(
    *,
    lineages: Sequence[Mapping[str, Any]],
    table_hashes: Mapping[str, str],
    row_counts: Mapping[str, int],
    facets: Mapping[str, Any],
    pulse_query_sha256: str,
) -> dict[str, Any]:
    """Build the semantic identity used for no-op and version decisions.

    File path, byte size, mtime, and SQLite page metadata remain provenance
    only, so a metadata-only source-file change cannot trigger a republish.
    """

    return {
        "schemaVersion": SCHEMA_VERSION,
        "lineage": list(lineages),
        "tableHashes": dict(table_hashes),
        "rowCounts": dict(row_counts),
        "facets": dict(facets),
        "marketPulseQuerySha256": pulse_query_sha256,
    }


def build_manifest(source: Path, staging: Path | None = None) -> dict[str, Any]:
    source = source.expanduser().resolve(strict=True)
    with consistent_source(source) as connection:
        source_metadata = _source_metadata(connection, source)
        lineages = lineage_rows(connection)
        tables: dict[str, dict[str, Any]] = {}
        for name, builder in TABLE_BUILDERS:
            rows = builder(connection)
            destination = None if staging is None else staging / f"{name}.jsonl.gz"
            tables[name] = _table_stats(rows, destination=destination)
        pulse_rows, pulse_query_sha256 = market_pulse_rows(connection)
        destination = None if staging is None else staging / "market_pulse.jsonl.gz"
        tables["market_pulse"] = _table_stats(pulse_rows, destination=destination)
        pulse = pulse_rows[0]["payload"]
        facets = _facets(connection, pulse)

    table_hashes = {name: value["contentSha256"] for name, value in sorted(tables.items())}
    row_counts = {name: value["rowCount"] for name, value in sorted(tables.items())}
    # File path, mtime, and SQLite page counts are provenance, not dataset
    # identity.  Repacking the same logical serving content must remain a no-op.
    source_manifest = serving_identity(
        lineages=lineages,
        table_hashes=table_hashes,
        row_counts=row_counts,
        facets=facets,
        pulse_query_sha256=pulse_query_sha256,
    )
    source_manifest_sha256 = sha256_json(source_manifest)
    source_as_of = max(str(row["generated_at"]) for row in lineages)
    parsed_as_of = datetime.fromisoformat(source_as_of.replace("Z", "+00:00")).astimezone(timezone.utc)
    dataset_version = f"cre-{parsed_as_of:%Y%m%dT%H%M%SZ}-{source_manifest_sha256[:12]}"
    package_bytes = sum(
        int(value["compressedBytes"] if value["compressedBytes"] is not None else value["uncompressedBytes"])
        for value in tables.values()
    )
    return {
        "packageVersion": PACKAGE_VERSION,
        "schemaVersion": SCHEMA_VERSION,
        "datasetVersion": dataset_version,
        "mode": "PLAN" if staging is None else "EXPORT",
        "willWrite": staging is not None,
        "sourceAsOfAt": source_as_of,
        "sourceManifestSha256": source_manifest_sha256,
        "source": source_metadata,
        "marketPulseQuerySha256": pulse_query_sha256,
        "tables": tables,
        "rowCounts": row_counts,
        "tableHashes": table_hashes,
        "lineage": lineages,
        "facets": facets,
        "packageBytes": package_bytes,
        "estimatedUploadBytes": sum(value["uncompressedBytes"] for value in tables.values()),
        "excluded": {
            "rawArchive": True,
            "sourceHistory": True,
            "molitTransactions": True,
            "permitHotDetail": True,
            "embeddings": True,
            "reason": "Current dashboard uses article serving rows, filterable monthly facts, and a precomputed governed market-pulse payload.",
        },
    }


def export_package(source: Path, output_root: Path) -> tuple[Path, dict[str, Any]]:
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".supabase-compact-", dir=output_root))
    try:
        manifest = build_manifest(source, staging)
        final = output_root / manifest["datasetVersion"]
        manifest_path = staging / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        if final.exists():
            existing = json.loads((final / "manifest.json").read_text(encoding="utf-8"))
            if existing.get("sourceManifestSha256") != manifest["sourceManifestSha256"]:
                raise CompactExportError(f"Existing package conflicts with {final.name}")
            shutil.rmtree(staging)
            return final, existing
        staging.rename(final)
        return final, manifest
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in ("plan", "export"):
        child = subparsers.add_parser(command)
        child.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        if command == "export":
            child.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            manifest = build_manifest(args.source)
        else:
            package_path, manifest = export_package(args.source, args.output_root)
            manifest = {**manifest, "packagePath": str(package_path)}
    except (OSError, sqlite3.Error, ValueError, CompactExportError) as error:
        raise SystemExit(f"compact export failed: {error}") from error
    print(json.dumps(manifest, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
