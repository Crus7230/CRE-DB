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
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
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
EXPECTED_SEOUL_DISTRICT_CODES = (
    "11110", "11140", "11170", "11200", "11215", "11230", "11260",
    "11290", "11305", "11320", "11350", "11380", "11410", "11440",
    "11470", "11500", "11530", "11545", "11560", "11590", "11620",
    "11650", "11680", "11710", "11740",
)
COMPLETE_MOLIT_COVERAGE_STATUSES = frozenset(
    {
        "COMPLETE_FULL_SNAPSHOT",
        "COMPLETE_EMPTY",
        "COMPLETE_BASELINE_WITH_CHANGES",
    }
)
LARGE_TRANSACTION_CONTRACT_VERSION = 1
LARGE_TRANSACTION_MIN_AREA_PYEONG = 5_000
LARGE_TRANSACTION_MIN_AREA_M2 = LARGE_TRANSACTION_MIN_AREA_PYEONG * 400 / 121
LARGE_TRANSACTION_PAGE_SIZE = 20
LARGE_TRANSACTION_MAX_MONTHS = 19
LARGE_TRANSACTION_MAX_PAGES_PER_MONTH = 500
LARGE_TRANSACTION_MAX_ROWS = 10_000
LARGE_TRANSACTION_MAX_UTF8_BYTES = 1_048_576
LARGE_TRANSACTION_AREA_RULE_NUMERATOR = 2_000_000
LARGE_TRANSACTION_AREA_RULE_DENOMINATOR = 121
LARGE_TRANSACTION_SOURCE = {
    "code": "MOLIT_REAL_TRANSACTION",
    "label": "국토교통부 실거래 공개시스템",
    "geography": "서울특별시",
    "completedPartitionsOnly": True,
    "exactPayloadDeduplicated": True,
    "currentServingOnly": True,
}
LARGE_TRANSACTION_QUERY = """
SELECT api_payload_sha256,district_code,district_name,locality,building_use,
       building_area_text,deal_amount_text,deal_year,deal_month_number,deal_day,
       nullif(trim(CAST(json_extract(api_payload_json,'$.buildingType') AS TEXT)),'')
         AS building_type,
       nullif(trim(CAST(json_extract(api_payload_json,'$.jibun') AS TEXT)),'') AS jibun
FROM serving_molit_current_transactions
ORDER BY deal_year,CAST(deal_month_number AS INTEGER),CAST(deal_day AS INTEGER),
         api_payload_sha256
""".strip()
LARGE_TRANSACTION_COVERAGE_QUERY = """
SELECT deal_month,district_code,coverage_status
FROM serving_molit_completed_partitions
ORDER BY deal_month,district_code
""".strip()
LARGE_TRANSACTION_QUERY_IDENTITY = {
    "contractVersion": LARGE_TRANSACTION_CONTRACT_VERSION,
    "transactionQuery": LARGE_TRANSACTION_QUERY,
    "coverageQuery": LARGE_TRANSACTION_COVERAGE_QUERY,
    "minimumAreaRule": "building_area_decimal * 121 >= 2000000",
    "baseAreaRule": "building_area_decimal > 3300",
    "pageSize": LARGE_TRANSACTION_PAGE_SIZE,
}

# These fields record when an otherwise identical projection was rebuilt or
# observed.  They remain in the immutable package for freshness/lineage, but
# must not create a new logical dataset by themselves.
CONTENT_IGNORED_COLUMNS: Mapping[str, frozenset[str]] = {
    "article_dates": frozenset({"generated_at"}),
    "articles": frozenset({"projection_generated_at"}),
    "article_details": frozenset({"projection_generated_at"}),
    "market_pulse": frozenset({"source_content_sha256", "generated_at"}),
}
CONTENT_IGNORED_JSON_KEYS: Mapping[str, frozenset[str]] = {
    "market_pulse": frozenset({"generatedAt"}),
}
LINEAGE_IGNORED_METADATA_KEYS = frozenset(
    {
        "generatedAt",
        "projectionGeneratedAt",
    }
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


LARGE_TRANSACTION_QUERY_SHA256 = sha256_json(LARGE_TRANSACTION_QUERY_IDENTITY)


def _without_keys(value: Any, ignored: frozenset[str]) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _without_keys(child, ignored)
            for key, child in value.items()
            if key not in ignored
        }
    if isinstance(value, list):
        return [_without_keys(child, ignored) for child in value]
    return value


def content_identity_row(table: str, row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the business-content projection used only for no-op identity."""

    ignored_columns = CONTENT_IGNORED_COLUMNS.get(table, frozenset())
    ignored_json_keys = CONTENT_IGNORED_JSON_KEYS.get(table, frozenset())
    return {
        key: _without_keys(value, ignored_json_keys)
        for key, value in row.items()
        if key not in ignored_columns
    }


def content_identity_lineage(row: Mapping[str, Any]) -> dict[str, Any]:
    """Keep semantic lineage while separating operational freshness clocks."""

    return {
        "dataset_code": row["dataset_code"],
        "source_code": row["source_code"],
        "source_as_of_date": row["source_as_of_date"],
        "source_status_code": row["source_status_code"],
        "source_row_count": int(row["source_row_count"]),
        "serving_row_count": int(row["serving_row_count"]),
        "source_content_sha256": row["source_content_sha256"],
        "metadata": _without_keys(
            row.get("metadata", {}), LINEAGE_IGNORED_METADATA_KEYS
        ),
    }


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


_STRICT_DECIMAL_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)?$", re.ASCII)
_STRICT_AMOUNT_RE = re.compile(r"^(?:[0-9]+|[0-9]+(?:,[0-9]{3})+)$", re.ASCII)
_RESIDENTIAL_USE_TOKENS = (
    "아파트", "공동주택", "단독주택", "다가구", "다세대", "연립", "주택", "주거"
)


def _large_transaction_coverage(
    connection: sqlite3.Connection,
) -> dict[str, dict[str, str]]:
    coverage: dict[str, dict[str, str]] = defaultdict(dict)
    expected = set(EXPECTED_SEOUL_DISTRICT_CODES)
    for raw in connection.execute(LARGE_TRANSACTION_COVERAGE_QUERY):
        month = str(raw["deal_month"] or "")
        district = str(raw["district_code"] or "")
        status = str(raw["coverage_status"] or "")
        if district not in expected:
            continue
        previous = coverage[month].get(district)
        if previous is not None and previous != status:
            raise CompactExportError(
                f"Conflicting MOLIT coverage for {month}/{district}"
            )
        coverage[month][district] = status
    return coverage


def _parse_large_transaction(
    raw: Mapping[str, Any], selected_months: frozenset[str]
) -> tuple[str, dict[str, Any]] | None:
    year_text = str(raw.get("deal_year") or "")
    month_text = str(raw.get("deal_month_number") or "")
    day_text = str(raw.get("deal_day") or "")
    if not re.fullmatch(r"20[0-9]{2}", year_text, re.ASCII):
        return None
    if (
        len(month_text) < 1
        or len(month_text) > 2
        or not month_text.isascii()
        or not month_text.isdigit()
    ):
        return None
    month_number = int(month_text)
    if month_number < 1 or month_number > 12:
        return None
    month = f"{year_text}-{month_number:02d}"
    if month not in selected_months:
        return None
    if (
        len(day_text) < 1
        or len(day_text) > 2
        or not day_text.isascii()
        or not day_text.isdigit()
    ):
        return None
    day_number = int(day_text)
    try:
        deal_date = date(int(year_text), month_number, day_number).isoformat()
    except ValueError:
        return None

    district_code = str(raw.get("district_code") or "")
    building_use = str(raw.get("building_use") or "")
    area_text = str(raw.get("building_area_text") or "")
    amount_text = str(raw.get("deal_amount_text") or "")
    if (
        not district_code.startswith("11")
        or not building_use.strip()
        or any(token in building_use for token in _RESIDENTIAL_USE_TOKENS)
        or not _STRICT_DECIMAL_RE.fullmatch(area_text)
        or not _STRICT_AMOUNT_RE.fullmatch(amount_text)
    ):
        return None
    try:
        area = Decimal(area_text)
    except InvalidOperation:
        return None
    if not area.is_finite() or area <= Decimal(3_300):
        return None
    amount_krw = int(amount_text.replace(",", "")) * 10_000

    transaction_id = str(raw.get("api_payload_sha256") or "").strip()
    if not re.fullmatch(r"[a-f0-9]{64}", transaction_id):
        raise CompactExportError("Eligible MOLIT transaction has an invalid payload hash")
    district = str(raw.get("district_name") or "")
    locality = str(raw.get("locality") or "")
    jibun = raw.get("jibun")
    address = (
        f"{district} {locality}"
        + ("" if jibun is None else f" {str(jibun)}")
    ).strip()
    if not address:
        raise CompactExportError("Eligible MOLIT transaction has no display address")
    building_type = raw.get("building_type")
    if building_type is not None:
        building_type = str(building_type)
    return month, {
        "id": transaction_id,
        "dealDate": deal_date,
        "address": address,
        "buildingUse": building_use,
        "buildingType": building_type,
        "areaM2": float(area),
        "areaPyeong": float(
            (area * Decimal(121) / Decimal(400)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        ),
        "amountKrw": str(amount_krw),
        "_areaDecimal": area,
        "_amountKrw": amount_krw,
    }


def build_large_transactions(
    connection: sqlite3.Connection,
    trend: Sequence[Mapping[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the bounded 5,000-pyeong detail envelope for pulse trend months."""

    months = [str(point.get("period") or "") for point in trend]
    if (
        not months
        or len(months) > LARGE_TRANSACTION_MAX_MONTHS
        or months != sorted(months)
        or len(set(months)) != len(months)
        or any(not re.fullmatch(r"20[0-9]{2}-(?:0[1-9]|1[0-2])", month) for month in months)
    ):
        raise CompactExportError("Market pulse months cannot satisfy the detail contract")
    observed_now = now or datetime.now(timezone.utc)
    if observed_now.tzinfo is None:
        observed_now = observed_now.replace(tzinfo=timezone.utc)
    current_kst_month = observed_now.astimezone(
        timezone(timedelta(hours=9))
    ).strftime("%Y-%m")
    if any(month >= current_kst_month for month in months):
        raise CompactExportError("Current or future month cannot be exported as completed detail")

    coverage = _large_transaction_coverage(connection)
    expected_districts = set(EXPECTED_SEOUL_DISTRICT_CODES)
    for month in months:
        month_coverage = coverage.get(month, {})
        if set(month_coverage) != expected_districts or any(
            status not in COMPLETE_MOLIT_COVERAGE_STATUSES
            for status in month_coverage.values()
        ):
            raise CompactExportError(
                f"MOLIT detail month {month} is not a complete 25-district snapshot"
            )

    by_month: dict[str, dict[str, dict[str, Any]]] = {
        month: {} for month in months
    }
    selected_months = frozenset(months)
    for source in connection.execute(LARGE_TRANSACTION_QUERY):
        parsed = _parse_large_transaction(dict(source), selected_months)
        if parsed is None:
            continue
        month, transaction = parsed
        previous = by_month[month].get(transaction["id"])
        if previous is not None and previous != transaction:
            raise CompactExportError(
                f"Payload hash has conflicting canonical facts in {month}"
            )
        by_month[month][transaction["id"]] = transaction

    output_months: list[dict[str, Any]] = []
    total_detail_rows = 0
    for point in trend:
        month = str(point["period"])
        canonical = list(by_month[month].values())
        expected_count = int(point["transactionCount"])
        if len(canonical) != expected_count:
            raise CompactExportError(
                f"MOLIT detail base count differs from market pulse for {month}"
            )
        expected_amount = Decimal(str(point["amountKrw"]))
        expected_area = Decimal(str(point["areaM2"]))
        base_amount = sum((Decimal(row["_amountKrw"]) for row in canonical), Decimal(0))
        base_area = sum((row["_areaDecimal"] for row in canonical), Decimal(0))
        area_tolerance = max(Decimal("0.000001"), abs(expected_area) * Decimal("1e-12"))
        if base_amount != expected_amount or abs(base_area - expected_area) > area_tolerance:
            raise CompactExportError(
                f"MOLIT detail base totals differ from market pulse for {month}"
            )

        large = [
            row for row in canonical
            if row["_areaDecimal"] * LARGE_TRANSACTION_AREA_RULE_DENOMINATOR
            >= LARGE_TRANSACTION_AREA_RULE_NUMERATOR
        ]
        large.sort(key=lambda row: row["id"])
        large.sort(key=lambda row: row["dealDate"], reverse=True)
        large.sort(key=lambda row: row["_amountKrw"], reverse=True)
        large.sort(key=lambda row: row["_areaDecimal"], reverse=True)
        large_amount = sum((Decimal(row["_amountKrw"]) for row in large), Decimal(0))
        large_area = sum((row["_areaDecimal"] for row in large), Decimal(0))
        if large_amount > expected_amount or large_area - expected_area > area_tolerance:
            raise CompactExportError(
                f"MOLIT large-detail subset exceeds pulse totals for {month}"
            )
        public_rows = [
            {key: value for key, value in row.items() if not key.startswith("_")}
            for row in large
        ]
        pages = [
            {"page": offset // LARGE_TRANSACTION_PAGE_SIZE + 1, "rows": public_rows[offset:offset + LARGE_TRANSACTION_PAGE_SIZE]}
            for offset in range(0, len(public_rows), LARGE_TRANSACTION_PAGE_SIZE)
        ]
        if len(pages) > LARGE_TRANSACTION_MAX_PAGES_PER_MONTH:
            raise CompactExportError(f"MOLIT detail page cap exceeded for {month}")
        total_detail_rows += len(public_rows)
        output_months.append(
            {
                "month": month,
                "baseTransactionCount": expected_count,
                "totalCount": len(public_rows),
                "coverage": {
                    "status": "COMPLETE",
                    "expectedDistrictCount": 25,
                    "completedDistrictCount": 25,
                },
                "pages": pages,
            }
        )

    if total_detail_rows > LARGE_TRANSACTION_MAX_ROWS:
        raise CompactExportError("MOLIT detail envelope row cap exceeded")
    envelope = {
        "contractVersion": LARGE_TRANSACTION_CONTRACT_VERSION,
        "minAreaPyeong": LARGE_TRANSACTION_MIN_AREA_PYEONG,
        "minAreaM2": LARGE_TRANSACTION_MIN_AREA_M2,
        "areaBasis": "TRANSACTED_BUILDING_AREA",
        "pageSize": LARGE_TRANSACTION_PAGE_SIZE,
        "months": output_months,
    }
    serialized_bytes = len(canonical_json(envelope).encode("utf-8"))
    if serialized_bytes > LARGE_TRANSACTION_MAX_UTF8_BYTES:
        raise CompactExportError("MOLIT detail envelope byte cap exceeded")
    return envelope


def large_transactions_stats(envelope: Mapping[str, Any]) -> dict[str, Any]:
    months = envelope["months"]
    return {
        "contractVersion": int(envelope["contractVersion"]),
        "monthCount": len(months),
        "totalCount": sum(int(month["totalCount"]) for month in months),
        "serializedUtf8Bytes": len(canonical_json(envelope).encode("utf-8")),
        "maximumUtf8Bytes": LARGE_TRANSACTION_MAX_UTF8_BYTES,
        "minimumAreaPyeong": LARGE_TRANSACTION_MIN_AREA_PYEONG,
        "minimumAreaM2": LARGE_TRANSACTION_MIN_AREA_M2,
        "pageSize": LARGE_TRANSACTION_PAGE_SIZE,
        "querySha256": LARGE_TRANSACTION_QUERY_SHA256,
        "source": dict(LARGE_TRANSACTION_SOURCE),
    }


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


def market_pulse_rows(
    connection: sqlite3.Connection,
) -> tuple[list[dict[str, Any]], str, str]:
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
    large_transactions = build_large_transactions(connection, payload["trend"])
    payload["largeTransactions"] = large_transactions
    raw["largeTransactions"] = large_transactions
    return [
        {
            "as_of_period": f"{payload['asOfPeriod']}-01",
            "payload": payload,
            "source_content_sha256": sha256_json(raw),
            "generated_at": payload["generatedAt"],
        }
    ], query_sha256, LARGE_TRANSACTION_QUERY_SHA256


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
            "largeTransactions": large_transactions_stats(pulse["largeTransactions"]),
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
    table: str,
    rows: Sequence[dict[str, Any]],
    *,
    destination: Path | None,
) -> dict[str, Any]:
    digest = hashlib.sha256()
    content_digest = hashlib.sha256()
    uncompressed_bytes = 0
    compressed_bytes: int | None = None
    handle = gzip.open(destination, "xt", encoding="utf-8", newline="\n", compresslevel=9) if destination else None
    try:
        for row in rows:
            line = canonical_json(row) + "\n"
            encoded = line.encode("utf-8")
            digest.update(encoded)
            content_digest.update(
                (canonical_json(content_identity_row(table, row)) + "\n").encode("utf-8")
            )
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
        "stableContentSha256": content_digest.hexdigest(),
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
    large_transactions_query_sha256: str,
) -> dict[str, Any]:
    """Build the semantic identity used for no-op and version decisions.

    File path, byte size, mtime, and SQLite page metadata remain provenance
    only, so a metadata-only source-file change cannot trigger a republish.
    """

    return {
        "schemaVersion": SCHEMA_VERSION,
        "identityVersion": 3,
        "lineage": [content_identity_lineage(row) for row in lineages],
        "tableHashes": dict(table_hashes),
        "rowCounts": dict(row_counts),
        "facets": dict(facets),
        "marketPulseQuerySha256": pulse_query_sha256,
        "largeTransactionsQuerySha256": large_transactions_query_sha256,
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
            tables[name] = _table_stats(name, rows, destination=destination)
        (
            pulse_rows,
            pulse_query_sha256,
            large_transactions_query_sha256,
        ) = market_pulse_rows(connection)
        destination = None if staging is None else staging / "market_pulse.jsonl.gz"
        tables["market_pulse"] = _table_stats(
            "market_pulse", pulse_rows, destination=destination
        )
        pulse = pulse_rows[0]["payload"]
        facets = _facets(connection, pulse)

    table_hashes = {name: value["contentSha256"] for name, value in sorted(tables.items())}
    stable_table_hashes = {
        name: value["stableContentSha256"] for name, value in sorted(tables.items())
    }
    row_counts = {name: value["rowCount"] for name, value in sorted(tables.items())}
    # File path, mtime, and SQLite page counts are provenance, not dataset
    # identity.  Repacking the same logical serving content must remain a no-op.
    source_manifest = serving_identity(
        lineages=lineages,
        table_hashes=stable_table_hashes,
        row_counts=row_counts,
        facets=facets,
        pulse_query_sha256=pulse_query_sha256,
        large_transactions_query_sha256=large_transactions_query_sha256,
    )
    source_manifest_sha256 = sha256_json(source_manifest)
    source_as_of = max(str(row["generated_at"]) for row in lineages)
    content_dates = [
        str(facets["news"]["availableThrough"]),
        f'{facets["macro"]["availableThrough"]}-01',
        f'{facets["permits"]["availableThrough"]}-01',
        f'{facets["marketPulse"]["asOfPeriod"]}-01',
    ]
    content_as_of_date = max(content_dates)
    parsed_content_as_of = datetime.fromisoformat(content_as_of_date).replace(
        tzinfo=timezone.utc
    )
    dataset_version = (
        f"cre-{parsed_content_as_of:%Y%m%dT000000Z}-{source_manifest_sha256[:12]}"
    )
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
        "contentAsOfDate": content_as_of_date,
        "sourceManifestSha256": source_manifest_sha256,
        "source": source_metadata,
        "marketPulseQuerySha256": pulse_query_sha256,
        "largeTransactionsQuerySha256": large_transactions_query_sha256,
        "largeTransactions": large_transactions_stats(pulse["largeTransactions"]),
        "tables": tables,
        "rowCounts": row_counts,
        "tableHashes": table_hashes,
        "stableTableHashes": stable_table_hashes,
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


def _verified_base_package(package: Path) -> dict[str, Any]:
    package = package.expanduser().resolve(strict=True)
    manifest_path = package / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise CompactExportError(f"Cannot read base package manifest: {manifest_path}") from error
    expected_tables = {name for name, _builder in TABLE_BUILDERS} | {"market_pulse"}
    tables = manifest.get("tables")
    if (
        not isinstance(tables, dict)
        or set(tables) != expected_tables
        or manifest.get("schemaVersion") != SCHEMA_VERSION
        or not re.fullmatch(
            r"cre-[0-9]{8}T[0-9]{6}Z-[a-f0-9]{12}",
            str(manifest.get("datasetVersion") or ""),
        )
    ):
        raise CompactExportError("Base package manifest contract is invalid")

    verified_tables: dict[str, dict[str, Any]] = {}
    for table in sorted(expected_tables):
        report = tables[table]
        filename = report.get("file")
        if not isinstance(filename, str) or Path(filename).name != filename:
            raise CompactExportError(f"Unsafe base package filename for {table}")
        path = package / filename
        digest = hashlib.sha256()
        stable_digest = hashlib.sha256()
        row_count = 0
        uncompressed_bytes = 0
        try:
            with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
                for line_number, line in enumerate(handle, start=1):
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as error:
                        raise CompactExportError(
                            f"Invalid base package JSON in {filename}:{line_number}"
                        ) from error
                    if not isinstance(row, dict):
                        raise CompactExportError(
                            f"Non-object base package row in {filename}:{line_number}"
                        )
                    encoded = (canonical_json(row) + "\n").encode("utf-8")
                    digest.update(encoded)
                    stable_digest.update(
                        (canonical_json(content_identity_row(table, row)) + "\n").encode("utf-8")
                    )
                    uncompressed_bytes += len(encoded)
                    row_count += 1
        except OSError as error:
            raise CompactExportError(f"Cannot read base package table {filename}") from error
        actual = {
            "rowCount": row_count,
            "contentSha256": digest.hexdigest(),
            "stableContentSha256": stable_digest.hexdigest(),
            "uncompressedBytes": uncompressed_bytes,
            "compressedBytes": path.stat().st_size,
            "file": filename,
        }
        for key in (
            "rowCount", "contentSha256", "stableContentSha256",
            "uncompressedBytes", "compressedBytes", "file",
        ):
            if report.get(key) != actual[key]:
                raise CompactExportError(f"Base package {table} {key} mismatch")
        verified_tables[table] = actual

    row_counts = {name: value["rowCount"] for name, value in sorted(verified_tables.items())}
    table_hashes = {name: value["contentSha256"] for name, value in sorted(verified_tables.items())}
    stable_hashes = {
        name: value["stableContentSha256"] for name, value in sorted(verified_tables.items())
    }
    if (
        manifest.get("rowCounts") != row_counts
        or manifest.get("tableHashes") != table_hashes
        or manifest.get("stableTableHashes") != stable_hashes
    ):
        raise CompactExportError("Base package aggregate table identity mismatch")
    legacy_identity = {
        "schemaVersion": SCHEMA_VERSION,
        "identityVersion": 2,
        "lineage": [content_identity_lineage(row) for row in manifest["lineage"]],
        "tableHashes": stable_hashes,
        "rowCounts": row_counts,
        "facets": manifest["facets"],
        "marketPulseQuerySha256": manifest["marketPulseQuerySha256"],
    }
    if sha256_json(legacy_identity) != manifest.get("sourceManifestSha256"):
        raise CompactExportError("Base package source identity is invalid")
    if not str(manifest["datasetVersion"]).endswith(
        f"-{manifest['sourceManifestSha256'][:12]}"
    ):
        raise CompactExportError("Base package dataset version does not match its identity")
    return manifest


def _base_market_pulse_row(base_package: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    filename = manifest["tables"]["market_pulse"]["file"]
    with gzip.open(base_package / filename, "rt", encoding="utf-8", newline="") as handle:
        rows = [json.loads(line) for line in handle]
    if len(rows) != 1 or not isinstance(rows[0].get("payload"), dict):
        raise CompactExportError("Base package must contain exactly one market pulse row")
    if "largeTransactions" in rows[0]["payload"]:
        raise CompactExportError("Base market pulse already contains large-transaction detail")
    return rows[0]


def build_large_transactions_delta_manifest(
    source: Path,
    base_package: Path,
    staging: Path | None = None,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Augment one verified immutable package without rebuilding its other tables."""

    source = source.expanduser().resolve(strict=True)
    base_package = base_package.expanduser().resolve(strict=True)
    base = _verified_base_package(base_package)
    market_row = _base_market_pulse_row(base_package, base)
    pulse = deepcopy(market_row["payload"])
    trend = pulse.get("trend")
    if not isinstance(trend, list):
        raise CompactExportError("Base market pulse has no trend")
    with consistent_source(source) as connection:
        large_transactions = build_large_transactions(connection, trend, now=now)
        detail_source = _source_metadata(connection, source)
    pulse["largeTransactions"] = large_transactions
    market_row["payload"] = pulse
    market_row["source_content_sha256"] = sha256_json(
        {
            "baseSourceContentSha256": market_row["source_content_sha256"],
            "largeTransactions": large_transactions,
        }
    )

    if staging is not None:
        for table in sorted(set(base["tables"]) - {"market_pulse"}):
            filename = base["tables"][table]["file"]
            shutil.copy2(base_package / filename, staging / filename)
    market_destination = None if staging is None else staging / "market_pulse.jsonl.gz"
    market_stats = _table_stats(
        "market_pulse", [market_row], destination=market_destination
    )
    if staging is None:
        encoded = (canonical_json(market_row) + "\n").encode("utf-8")
        market_stats["compressedBytes"] = len(gzip.compress(encoded, compresslevel=9, mtime=0))

    tables = deepcopy(base["tables"])
    tables["market_pulse"] = market_stats
    row_counts = {name: int(value["rowCount"]) for name, value in sorted(tables.items())}
    table_hashes = {
        name: str(value["contentSha256"]) for name, value in sorted(tables.items())
    }
    stable_table_hashes = {
        name: str(value["stableContentSha256"]) for name, value in sorted(tables.items())
    }
    if any(
        table_hashes[table] != base["tableHashes"][table]
        or stable_table_hashes[table] != base["stableTableHashes"][table]
        or row_counts[table] != int(base["rowCounts"][table])
        for table in tables
        if table != "market_pulse"
    ):
        raise CompactExportError("A non-market table changed during delta packaging")
    if table_hashes["market_pulse"] == base["tableHashes"]["market_pulse"]:
        raise CompactExportError("Market pulse augmentation produced no content change")

    detail_stats = large_transactions_stats(large_transactions)
    facets = deepcopy(base["facets"])
    facets["marketPulse"] = deepcopy(facets["marketPulse"])
    facets["marketPulse"]["largeTransactions"] = detail_stats
    source_manifest = serving_identity(
        lineages=base["lineage"],
        table_hashes=stable_table_hashes,
        row_counts=row_counts,
        facets=facets,
        pulse_query_sha256=base["marketPulseQuerySha256"],
        large_transactions_query_sha256=LARGE_TRANSACTION_QUERY_SHA256,
    )
    source_manifest_sha256 = sha256_json(source_manifest)
    content_as_of_date = str(base["contentAsOfDate"])
    parsed_content_as_of = datetime.fromisoformat(content_as_of_date).replace(
        tzinfo=timezone.utc
    )
    dataset_version = (
        f"cre-{parsed_content_as_of:%Y%m%dT000000Z}-{source_manifest_sha256[:12]}"
    )
    required_clones = [
        table for table, _builder in TABLE_BUILDERS
    ]
    package_bytes = sum(int(value["compressedBytes"]) for value in tables.values())
    estimated_upload_bytes = sum(int(value["uncompressedBytes"]) for value in tables.values())
    return {
        **deepcopy(base),
        "datasetVersion": dataset_version,
        "mode": "PLAN" if staging is None else "EXPORT",
        "willWrite": staging is not None,
        "sourceManifestSha256": source_manifest_sha256,
        "largeTransactionsQuerySha256": LARGE_TRANSACTION_QUERY_SHA256,
        "tables": tables,
        "rowCounts": row_counts,
        "tableHashes": table_hashes,
        "stableTableHashes": stable_table_hashes,
        "facets": facets,
        "packageBytes": package_bytes,
        "estimatedUploadBytes": estimated_upload_bytes,
        "estimatedClientUploadBytes": int(market_stats["uncompressedBytes"]),
        "largeTransactions": detail_stats,
        "detailSource": detail_source,
        "delta": {
            "baseDatasetVersion": base["datasetVersion"],
            "baseSourceManifestSha256": base["sourceManifestSha256"],
            "changedTables": ["market_pulse"],
            "requiredServerCloneTables": required_clones,
        },
    }


def export_large_transactions_delta(
    source: Path,
    base_package: Path,
    output_root: Path,
) -> tuple[Path, dict[str, Any]]:
    output_root = output_root.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".supabase-detail-", dir=output_root))
    try:
        manifest = build_large_transactions_delta_manifest(
            source, base_package, staging
        )
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
    for command in ("plan-large-transactions", "export-large-transactions"):
        child = subparsers.add_parser(command)
        child.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
        child.add_argument("--base-package", type=Path, required=True)
        if command == "export-large-transactions":
            child.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "plan":
            manifest = build_manifest(args.source)
        elif args.command == "export":
            package_path, manifest = export_package(args.source, args.output_root)
            manifest = {**manifest, "packagePath": str(package_path)}
        elif args.command == "plan-large-transactions":
            manifest = build_large_transactions_delta_manifest(
                args.source, args.base_package
            )
        else:
            package_path, manifest = export_large_transactions_delta(
                args.source, args.base_package, args.output_root
            )
            manifest = {**manifest, "packagePath": str(package_path)}
    except (OSError, sqlite3.Error, ValueError, CompactExportError) as error:
        raise SystemExit(f"compact export failed: {error}") from error
    print(json.dumps(manifest, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
