"""Official financial-market macro collection and revision-safe SQLite storage."""
from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import time
from typing import Any, Callable
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ECOS_BASE = "https://ecos.bok.or.kr/api"
NYFED_BASE = "https://markets.newyorkfed.org/api/rates"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"
    "?data=daily_treasury_yield_curve&field_tdr_date_value={year}"
)
USER_AGENT = "CRE-DB/1.0 (+official macro collector)"


@dataclass(frozen=True)
class SeriesSpec:
    series_code: str
    name_ko: str
    source_id: str
    external_key: str
    frequency: str
    region_id: str
    definition: str
    start: str
    stat_code: str | None = None
    item_code: str | None = None
    field: str | None = None
    aggregation: str | None = None


SERIES: tuple[SeriesSpec, ...] = (
    SeriesSpec("BOK_BASE_RATE_MONTHLY", "한국은행 기준금리(월)", "src_bok", "722Y001/0101000/M", "MONTHLY", "reg_kr", "한국은행 ECOS가 공표하는 월별 한국은행 기준금리", "200001", "722Y001", "0101000", aggregation="PROVIDER_MONTHLY"),
    SeriesSpec("KR_CD_91D", "CD 91일 금리", "src_bok", "721Y001/2010000/M", "MONTHLY", "reg_kr", "한국은행 ECOS 월별 CD(91일) 금리", "199103", "721Y001", "2010000", aggregation="PROVIDER_MONTHLY"),
    SeriesSpec("KR_GOVT_BOND_3Y", "국고채 3년 금리", "src_bok", "721Y001/5020000/M", "MONTHLY", "reg_kr", "한국은행 ECOS 월별 국고채 3년 수익률", "199505", "721Y001", "5020000", aggregation="PROVIDER_MONTHLY"),
    SeriesSpec("KR_GOVT_BOND_10Y", "국고채 10년 금리", "src_bok", "721Y001/5050000/M", "MONTHLY", "reg_kr", "한국은행 ECOS 월별 국고채 10년 수익률", "200010", "721Y001", "5050000", aggregation="PROVIDER_MONTHLY"),
    SeriesSpec("KR_CORP_BOND_AA_MINUS_3Y", "회사채 AA- 3년 금리", "src_bok", "721Y001/7020000/M", "MONTHLY", "reg_kr", "한국은행 ECOS 월별 회사채 3년 AA- 수익률", "198701", "721Y001", "7020000", aggregation="PROVIDER_MONTHLY"),
    SeriesSpec("US_EFFR", "미국 유효 연방기금금리", "src_ny_fed", "NYFED/EFFR/percentRate", "DAILY", "reg_us", "뉴욕연은이 공표하는 Effective Federal Funds Rate", "2000-07-03", field="percentRate", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_FED_TARGET_LOWER", "미국 연방기금 목표금리 하단", "src_ny_fed", "NYFED/EFFR/targetRateFrom", "DAILY", "reg_us", "뉴욕연은 EFFR 응답의 연방기금 목표범위 하단", "2008-12-16", field="targetRateFrom", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_FED_TARGET_UPPER", "미국 연방기금 목표금리 상단", "src_ny_fed", "NYFED/EFFR/targetRateTo", "DAILY", "reg_us", "뉴욕연은 EFFR 응답의 연방기금 목표범위 상단", "2008-12-16", field="targetRateTo", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_SOFR", "미국 SOFR", "src_ny_fed", "NYFED/SOFR/percentRate", "DAILY", "reg_us", "뉴욕연은이 공표하는 Secured Overnight Financing Rate", "2018-04-02", field="percentRate", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_TREASURY_2Y", "미국 국채 2년 금리", "src_us_treasury", "USTREASURY/BC_2YEAR", "DAILY", "reg_us", "미국 재무부 Daily Treasury Par Yield Curve Rate 2년", "1990-01-02", field="BC_2YEAR", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_TREASURY_10Y", "미국 국채 10년 금리", "src_us_treasury", "USTREASURY/BC_10YEAR", "DAILY", "reg_us", "미국 재무부 Daily Treasury Par Yield Curve Rate 10년", "1990-01-02", field="BC_10YEAR", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_TREASURY_30Y", "미국 국채 30년 금리", "src_us_treasury", "USTREASURY/BC_30YEAR", "DAILY", "reg_us", "미국 재무부 Daily Treasury Par Yield Curve Rate 30년", "1990-01-02", field="BC_30YEAR", aggregation="CALENDAR_MONTH_AVERAGE"),
    SeriesSpec("US_TREASURY_10Y_MINUS_2Y", "미국 국채 10년-2년 금리차", "src_us_treasury", "DERIVED/BC_10YEAR-BC_2YEAR", "DAILY", "reg_us", "동일 미국 재무부 yield-curve 관측일의 10년 금리에서 2년 금리를 차감한 값", "1990-01-02", field="DERIVED_10Y_MINUS_2Y", aggregation="CALENDAR_MONTH_AVERAGE"),
)
SERIES_BY_CODE = {s.series_code: s for s in SERIES}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def fetch_bytes(url: str, *, timeout: int = 120, attempts: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json, application/xml, text/xml"}), timeout=timeout) as response:
                return response.read()
        except Exception as exc:  # pragma: no cover - network retry
            last = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"official source request failed: {url}: {last}")


def month_bounds(value: str) -> tuple[str, str]:
    year, month = int(value[:4]), int(value[4:6])
    return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{monthrange(year, month)[1]:02d}"


def observation(series_code: str, period_start: str, period_end: str, raw_value: Any, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    decimal_text = str(raw_value).strip()
    Decimal(decimal_text)
    return {
        "series_code": series_code,
        "period_start": period_start,
        "period_end": period_end,
        "numeric_value": float(decimal_text),
        "value_decimal_text": decimal_text,
        "raw_value": decimal_text,
        "source_record_key": f"{series_code}:{period_start}",
        "observation_status": "FINAL",
        "metadata": metadata or {},
    }


def parse_ecos_rows(spec: SeriesSpec, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        if row.get("DATA_VALUE") in (None, ""):
            continue
        start, end = month_bounds(str(row["TIME"]))
        result.append(observation(spec.series_code, start, end, row["DATA_VALUE"], {
            "statCode": row.get("STAT_CODE"), "itemCode": row.get("ITEM_CODE1"),
            "itemName": row.get("ITEM_NAME1"), "unitName": row.get("UNIT_NAME"),
        }))
    return result


def parse_nyfed_rows(kind: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    specs = [s for s in SERIES if s.source_id == "src_ny_fed" and ((kind == "SOFR" and s.series_code == "US_SOFR") or (kind == "EFFR" and s.series_code != "US_SOFR"))]
    result = []
    for row in rows:
        day = row.get("effectiveDate")
        if not day:
            continue
        for spec in specs:
            if day < spec.start:
                continue
            value = row.get(spec.field or "")
            if value in (None, ""):
                continue
            item = observation(spec.series_code, day, day, value, {"revisionIndicator": row.get("revisionIndicator", ""), "apiType": row.get("type")})
            if row.get("revisionIndicator"):
                item["observation_status"] = "REVISED"
            result.append(item)
    return result


def parse_treasury_xml(raw: bytes) -> list[dict[str, Any]]:
    root = ET.fromstring(raw)
    atom = "{http://www.w3.org/2005/Atom}"
    metadata_ns = "{http://schemas.microsoft.com/ado/2007/08/dataservices/metadata}"
    result = []
    specs = [s for s in SERIES if s.source_id == "src_us_treasury" and s.field != "DERIVED_10Y_MINUS_2Y"]
    for entry in root.findall(f"{atom}entry"):
        props = entry.find(f".//{metadata_ns}properties")
        if props is None:
            continue
        values = {node.tag.split("}")[-1]: node.text for node in props}
        raw_date = values.get("NEW_DATE")
        if not raw_date:
            continue
        day = raw_date[:10]
        day_values: dict[str, Decimal] = {}
        for spec in specs:
            value = values.get(spec.field or "")
            if value in (None, ""):
                continue
            day_values[spec.series_code] = Decimal(value)
            result.append(observation(spec.series_code, day, day, value, {"treasuryRowId": values.get("Id")}))
        if "US_TREASURY_10Y" in day_values and "US_TREASURY_2Y" in day_values:
            spread = day_values["US_TREASURY_10Y"] - day_values["US_TREASURY_2Y"]
            result.append(observation("US_TREASURY_10Y_MINUS_2Y", day, day, format(spread, "f"), {"derivedFrom": ["BC_10YEAR", "BC_2YEAR"]}))
    return result


def fetch_ecos(api_key: str, end_month: str, *, start_month: str | None = None, sleep_seconds: float = 0.05) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_obs, manifest = [], {"provider": "BOK_ECOS", "requests": [], "series": {}}
    for spec in [s for s in SERIES if s.source_id == "src_bok"]:
        effective_start = max(spec.start, start_month) if start_month else spec.start
        rows: list[dict[str, Any]] = []
        start_index, total = 1, None
        while total is None or start_index <= total:
            end_index = start_index + 9
            url = f"{ECOS_BASE}/StatisticSearch/{api_key}/json/kr/{start_index}/{end_index}/{spec.stat_code}/M/{effective_start}/{end_month}/{spec.item_code}"
            payload = json.loads(fetch_bytes(url, timeout=60).decode("utf-8"))
            block = payload.get("StatisticSearch")
            if not block:
                result = payload.get("RESULT", {})
                if result.get("CODE") == "INFO-200":
                    break
                raise RuntimeError(f"ECOS error for {spec.series_code}: {result}")
            total = int(block.get("list_total_count") or 0)
            page_rows = block.get("row") or []
            rows.extend(page_rows)
            manifest["requests"].append({"seriesCode": spec.series_code, "start": start_index, "end": end_index, "rows": len(page_rows)})
            start_index += 10
            if sleep_seconds:
                time.sleep(sleep_seconds)
        parsed = parse_ecos_rows(spec, rows)
        all_obs.extend(parsed)
        manifest["series"][spec.series_code] = {"rows": rows, "observationCount": len(parsed)}
    return all_obs, manifest


def fetch_nyfed(end_date: str, *, start_date: str | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_obs, manifest = [], {"provider": "NY_FED_MARKETS", "responses": {}}
    for kind, path, start in (("EFFR", "unsecured/effr", "2000-01-01"), ("SOFR", "secured/sofr", "2018-04-01")):
        start = max(start, start_date) if start_date else start
        url = f"{NYFED_BASE}/{path}/search.json?startDate={start}&endDate={end_date}&type=rate"
        raw = fetch_bytes(url)
        payload = json.loads(raw.decode("utf-8"))
        rows = payload.get("refRates") or []
        all_obs.extend(parse_nyfed_rows(kind, rows))
        manifest["responses"][kind] = {"url": url, "rows": rows}
    return all_obs, manifest


def fetch_treasury(start_year: int, end_year: int, *, sleep_seconds: float = 0.05) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_obs, manifest = [], {"provider": "US_TREASURY", "years": {}}
    for year in range(start_year, end_year + 1):
        url = TREASURY_URL.format(year=year)
        raw = fetch_bytes(url)
        parsed = parse_treasury_xml(raw)
        all_obs.extend(parsed)
        manifest["years"][str(year)] = {"url": url, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "observationCount": len(parsed), "rawXml": raw.decode("utf-8")}
        if sleep_seconds:
            time.sleep(sleep_seconds)
    return all_obs, manifest


def write_artifact(root: Path, source_code: str, retrieved_at: str, manifest: dict[str, Any]) -> tuple[Path, str]:
    stamp = retrieved_at.replace(":", "").replace("-", "").replace(".", "")
    path = root / f"{source_code.lower()}-{stamp}.json"
    text = canonical_json(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path, sha256_text(text)


def series_valid_from(spec: SeriesSpec) -> str:
    return f"{spec.start[:4]}-{spec.start[4:6]}-01" if len(spec.start) == 6 else spec.start


def ensure_series(conn: sqlite3.Connection) -> None:
    for spec in SERIES:
        metadata_value = {"domain": "FINANCIAL_MARKETS", "nativeId": spec.external_key, "aggregation": spec.aggregation}
        if spec.series_code == "US_FED_TARGET_LOWER":
            metadata_value["semanticBoundary"] = "2008-12-16 target-range regime"
        metadata = canonical_json(metadata_value)
        conn.execute(
            """INSERT INTO macro_series(macro_series_id,series_code,series_name_ko,metric_code,source_id,external_series_key,frequency_code,unit_code,region_id,adjustment_code,aggregation_code,definition_text,valid_from,is_active,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,'NONE',?,?,?,1,?)
               ON CONFLICT(series_code) DO NOTHING""",
            (f"ms_fin_{spec.series_code.lower()}", spec.series_code, spec.name_ko, "INTEREST_RATE", spec.source_id, spec.external_key, spec.frequency, "PERCENT", spec.region_id, spec.aggregation, spec.definition, series_valid_from(spec), metadata),
        )
        actual = conn.execute(
            """SELECT source_id,external_series_key,frequency_code,unit_code,region_id,aggregation_code,valid_from,is_active,metadata_json
                 FROM macro_series WHERE series_code=?""",
            (spec.series_code,),
        ).fetchone()
        expected = (spec.source_id, spec.external_key, spec.frequency, "PERCENT", spec.region_id, spec.aggregation, series_valid_from(spec), 1, metadata)
        if actual != expected:
            raise RuntimeError(f"macro series master contract mismatch for {spec.series_code}: migration required")


def store_source_snapshot(conn: sqlite3.Connection, source_id: str, source_code: str, observations: list[dict[str, Any]], artifact_path: Path, artifact_sha: str, retrieved_at: str) -> dict[str, int]:
    latest_period = max((o["period_end"] for o in observations), default=None)
    release_key = f"{source_code}:SNAPSHOT:{retrieved_at[:10]}"
    release_id = "mr_" + sha256_text(f"{source_id}|{release_key}|{artifact_sha}")[:32]
    conn.execute(
        """INSERT OR IGNORE INTO macro_releases(macro_release_id,source_id,publisher_release_key,release_title,released_at,effective_date,artifact_sha256,artifact_uri,first_collected_at,metadata_json)
           VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (release_id, source_id, release_key, f"{source_code} official API snapshot", retrieved_at, latest_period, artifact_sha, str(artifact_path), retrieved_at, canonical_json({"observationCount": len(observations)})),
    )
    inserted = unchanged = revised = 0
    for item in observations:
        series_id = conn.execute("SELECT macro_series_id FROM macro_series WHERE series_code=?", (item["series_code"],)).fetchone()[0]
        hash_body = canonical_json({k: item[k] for k in ("series_code", "period_start", "period_end", "value_decimal_text", "observation_status")})
        row_sha = sha256_text(hash_body)
        same = conn.execute("SELECT 1 FROM macro_observations WHERE macro_series_id=? AND period_start=? AND period_end=? AND row_sha256=?", (series_id, item["period_start"], item["period_end"], row_sha)).fetchone()
        if same:
            unchanged += 1
            continue
        previous = conn.execute("""SELECT macro_observation_id,revision_no FROM macro_observations WHERE macro_series_id=? AND period_start=? AND period_end=? ORDER BY revision_no DESC,vintage_at DESC LIMIT 1""", (series_id, item["period_start"], item["period_end"])).fetchone()
        revision_no = (previous[1] + 1) if previous else 0
        status = "REVISED" if previous else item["observation_status"]
        observation_id = "mo_" + sha256_text(f"{series_id}|{item['period_start']}|{row_sha}")[:32]
        conn.execute(
            """INSERT INTO macro_observations(macro_observation_id,macro_series_id,macro_release_id,period_start,period_end,period_label,observed_on,numeric_value,value_decimal_text,unit_code,collected_at,vintage_at,revision_no,observation_status,source_record_key,raw_value,row_sha256,supersedes_observation_id,metadata_json)
               VALUES(?,?,?,?,?,?,?,?,?,'PERCENT',?,?,?,?,?,?,?,?,?)""",
            (observation_id, series_id, release_id, item["period_start"], item["period_end"], item["period_start"][:7], item["period_start"], item["numeric_value"], item["value_decimal_text"], retrieved_at, retrieved_at, revision_no, status, item["source_record_key"], item["raw_value"], row_sha, previous[0] if previous else None, canonical_json(item["metadata"])),
        )
        inserted += 1
        revised += int(previous is not None)
    return {"observations": len(observations), "inserted": inserted, "unchanged": unchanged, "revised": revised}
