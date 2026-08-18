from __future__ import annotations

import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import sqlite3
from typing import Iterable
import urllib.request


class KindTableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_cell = False
        self.cell_parts: list[str] = []
        self.row: list[str] = []
        self.rows: list[list[str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"td", "th"}:
            self.in_cell = True
            self.cell_parts = []

    def handle_data(self, data: str) -> None:
        if self.in_cell:
            self.cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(" ".join("".join(self.cell_parts).split()))
            self.in_cell = False
        elif tag == "tr" and self.row:
            self.rows.append(self.row)
            self.row = []


def stable_id(prefix: str, value: str) -> str:
    return hashlib.sha256(f"{prefix}:{value}".encode()).hexdigest()[:32]


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def fetch(url: str, headers: dict[str, str] | None = None) -> bytes:
    request = urllib.request.Request(url, headers=headers or {"User-Agent": "Hermes CRE official-source collector"})
    return urllib.request.urlopen(request, timeout=60).read()


def parse_kind(raw: bytes) -> dict[str, dict[str, str]]:
    parser = KindTableParser()
    parser.feed(raw.decode("euc-kr", errors="replace"))
    if not parser.rows or parser.rows[0][:4] != ["회사명", "시장구분", "종목코드", "업종"]:
        raise RuntimeError("unexpected KIND company-list table contract")
    result: dict[str, dict[str, str]] = {}
    for row in parser.rows[1:]:
        if len(row) < 4:
            continue
        code = row[2].zfill(6)
        result[code] = {"company_name": row[0], "market": row[1], "industry": row[3] or "미분류"}
    return result


def organization_for(con: sqlite3.Connection, stock_code: str, name: str, metadata: dict) -> str:
    row = con.execute("SELECT organization_id FROM organizations WHERE stock_code=? LIMIT 1", (stock_code,)).fetchone()
    if row:
        return str(row[0])
    matches = con.execute(
        "SELECT organization_id FROM organizations WHERE canonical_name=? AND status_code<>'MERGED'", (name,)
    ).fetchall()
    if len(matches) == 1:
        organization_id = str(matches[0][0])
        con.execute(
            "UPDATE organizations SET stock_code=coalesce(stock_code,?),metadata_json=json_patch(metadata_json,?),updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE organization_id=?",
            (stock_code, json.dumps(metadata, ensure_ascii=False), organization_id),
        )
        return organization_id
    organization_id = stable_id("organization:krx", stock_code)
    con.execute(
        "INSERT INTO organizations(organization_id,organization_type,canonical_name,stock_code,country_code,status_code,metadata_json) VALUES(?,?,?,?,?,?,?)",
        (organization_id, "COMPANY", name, stock_code, "KR", "ACTIVE", json.dumps(metadata, ensure_ascii=False)),
    )
    return organization_id


def chunks(rows: Iterable[dict], size: int = 10) -> Iterable[list[dict]]:
    bucket: list[dict] = []
    for row in rows:
        bucket.append(row)
        if len(bucket) == size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect official KRX market-cap universe and KIND industries")
    parser.add_argument("--db", default="data/market.db")
    parser.add_argument("--env", default="C:/10137_WorkSpace/env/.env")
    parser.add_argument("--date", default="20260731", help="YYYYMMDD KRX trading date")
    parser.add_argument("--artifact-dir", default="artifacts/source-snapshots/krx")
    args = parser.parse_args()
    if len(args.date) != 8 or not args.date.isdigit():
        raise SystemExit("--date must be YYYYMMDD")
    api_key = load_env(Path(args.env)).get("KRX_API_KEY")
    if not api_key:
        raise SystemExit("KRX_API_KEY is not configured")

    raw_payloads: dict[str, bytes] = {}
    rows: list[dict] = []
    for endpoint in ("stk_bydd_trd", "ksq_bydd_trd", "knx_bydd_trd"):
        url = f"https://data-dbg.krx.co.kr/svc/apis/sto/{endpoint}?basDd={args.date}"
        raw = fetch(url, {"AUTH_KEY": api_key, "User-Agent": "Hermes CRE official-source collector"})
        raw_payloads[endpoint] = raw
        payload = json.loads(raw)
        block = payload.get("OutBlock_1")
        if not isinstance(block, list):
            raise RuntimeError(f"unexpected KRX payload contract: {endpoint}")
        rows.extend(block)

    kind_url = "https://kind.krx.co.kr/corpgeneral/corpList.do?method=download&searchType=13"
    kind_raw = fetch(kind_url)
    kind = parse_kind(kind_raw)
    eligible = []
    for row in rows:
        ticker = str(row.get("ISU_CD") or "").zfill(6)
        if ticker not in kind:
            continue
        market_cap = str(row.get("MKTCAP") or "").replace(",", "")
        if not market_cap.isdigit() or int(market_cap) <= 0:
            continue
        info = kind[ticker]
        eligible.append({
            "ticker": ticker,
            "name": info["company_name"],
            "industry": info["industry"],
            "market": str(row.get("MKT_NM") or info["market"]),
            "market_cap": market_cap,
            "close": str(row.get("TDD_CLSPRC") or "").replace(",", ""),
        })
    eligible.sort(key=lambda row: (-int(row["market_cap"]), row["ticker"]))
    if len(eligible) < 100:
        raise RuntimeError(f"KRX/KIND join unexpectedly small: {len(eligible)}")

    by_industry: dict[str, list[dict]] = {}
    for row in eligible:
        by_industry.setdefault(row["industry"], []).append(row)
    top50 = eligible[:50]
    industry_top10 = [row for group in by_industry.values() for row in group[:10]]

    artifact_dir = Path(args.artifact_dir) / args.date
    artifact_dir.mkdir(parents=True, exist_ok=True)
    for endpoint, raw in raw_payloads.items():
        (artifact_dir / f"{endpoint}.json").write_bytes(raw)
    (artifact_dir / "kind-company-list.html").write_bytes(kind_raw)
    combined_hash = hashlib.sha256(b"".join(raw_payloads[key] for key in sorted(raw_payloads)) + kind_raw).hexdigest()
    snapshot_date = f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:]}"
    taxonomy_code = f"KRX_KIND_{args.date}"
    methodology = {
        "krxApi": "KRX Open API daily issue trading",
        "kindIndustry": kind_url,
        "snapshotDate": snapshot_date,
        "commonStockProxy": "KIND listed-company stock-code intersection",
        "industryAsOf": "KIND list retrieved with this collection run; applied only to tickers present on the KRX snapshot date",
        "rawArtifactDir": str(artifact_dir),
    }

    con = sqlite3.connect(Path(args.db))
    con.execute("PRAGMA foreign_keys=ON")
    try:
        con.execute("BEGIN IMMEDIATE")
        con.execute(
            "INSERT INTO industry_taxonomies(taxonomy_code,taxonomy_name,publisher_name,version_label,valid_from,metadata_json) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(taxonomy_code) DO UPDATE SET taxonomy_name=excluded.taxonomy_name,publisher_name=excluded.publisher_name,version_label=excluded.version_label,valid_from=excluded.valid_from,metadata_json=excluded.metadata_json",
            (taxonomy_code, "KRX KIND 상장법인 업종", "한국거래소", args.date, snapshot_date, json.dumps(methodology, ensure_ascii=False)),
        )
        industry_ids: dict[str, str] = {}
        for industry in sorted(by_industry):
            industry_id = stable_id("industry", f"{taxonomy_code}:{industry}")
            industry_ids[industry] = industry_id
            con.execute(
                "INSERT INTO industry_nodes(industry_node_id,taxonomy_code,industry_code,industry_name,valid_from,metadata_json) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(industry_node_id) DO UPDATE SET industry_name=excluded.industry_name,valid_from=excluded.valid_from,metadata_json=excluded.metadata_json",
                (industry_id, taxonomy_code, f"KIND_{hashlib.sha1(industry.encode()).hexdigest()[:12]}", industry, snapshot_date, "{}"),
            )

        organizations: dict[str, str] = {}
        for row in eligible:
            organizations[row["ticker"]] = organization_for(con, row["ticker"], row["name"], {
                "krx_market": row["market"], "kind_industry": row["industry"], "krx_snapshot_date": snapshot_date,
            })

        overall_snapshot = stable_id("universe", f"{snapshot_date}:KRX:TOP50")
        industry_snapshot = stable_id("universe", f"{snapshot_date}:KRX:INDUSTRY_TOP10:{taxonomy_code}")
        snapshots = [
            (overall_snapshot, "KRX_MARKET_CAP_TOP_50", len(top50)),
            (industry_snapshot, "KRX_INDUSTRY_MARKET_CAP_TOP_10", len(industry_top10)),
        ]
        for snapshot_id, universe_code, count in snapshots:
            con.execute("DELETE FROM market_universe_members WHERE universe_snapshot_id=?", (snapshot_id,))
            con.execute(
                "INSERT INTO market_universe_snapshots(universe_snapshot_id,snapshot_date,market_code,universe_code,ranking_basis,taxonomy_code,snapshot_status,methodology_json,row_count,checksum_sha256) VALUES(?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(universe_snapshot_id) DO UPDATE SET snapshot_status=excluded.snapshot_status,methodology_json=excluded.methodology_json,row_count=excluded.row_count,checksum_sha256=excluded.checksum_sha256",
                (snapshot_id, snapshot_date, "KRX_ALL", universe_code, "MARKET_CAP", taxonomy_code, "COMPLETE", json.dumps(methodology, ensure_ascii=False), count, combined_hash),
            )

        for rank, row in enumerate(top50, 1):
            con.execute(
                "INSERT INTO market_universe_members(universe_member_id,universe_snapshot_id,organization_id,industry_node_id,overall_rank,market_cap_decimal,currency_code,inclusion_reason,verification_status,review_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (stable_id("member", f"{overall_snapshot}:{row['ticker']}"), overall_snapshot, organizations[row["ticker"]], industry_ids[row["industry"]], rank, row["market_cap"], "KRW", "TOP_50_OVERALL", "VERIFIED", "APPROVED", json.dumps({"close": row["close"], "market": row["market"]}, ensure_ascii=False)),
            )
        for industry, group in sorted(by_industry.items()):
            for rank, row in enumerate(group[:10], 1):
                con.execute(
                    "INSERT INTO market_universe_members(universe_member_id,universe_snapshot_id,organization_id,industry_node_id,industry_rank,market_cap_decimal,currency_code,inclusion_reason,verification_status,review_status,metadata_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (stable_id("member", f"{industry_snapshot}:{industry}:{row['ticker']}"), industry_snapshot, organizations[row["ticker"]], industry_ids[industry], rank, row["market_cap"], "KRW", "TOP_10_INDUSTRY", "VERIFIED", "APPROVED", json.dumps({"close": row["close"], "market": row["market"]}, ensure_ascii=False)),
                )
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()

    summary = {
        "snapshotDate": snapshot_date,
        "eligibleCompanies": len(eligible),
        "top50Rows": len(top50),
        "industryCount": len(by_industry),
        "industryTop10Rows": len(industry_top10),
        "checksumSha256": combined_hash,
        "artifactDir": str(artifact_dir),
    }
    (artifact_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
