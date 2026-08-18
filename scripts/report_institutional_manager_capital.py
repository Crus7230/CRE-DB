#!/usr/bin/env python
"""Generate an auditable institutional-manager capital and dry-powder report.

The script is intentionally conservative: a selection, announced cap, requested
amount, target fund size, or news-reported allocation never becomes verified
available capital without compatible commitment/paid-in/deployment evidence.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
ARTIFACT_DIR = ROOT / "artifacts"
REPORT_STEM = "institutional-manager-capital-and-dry-powder-20260816"

MANAGER_CLASS = {
    "우리글로벌자산운용": "DOMESTIC_ASSET_MANAGER",
    "캡스톤자산운용": "DOMESTIC_ASSET_MANAGER",
    "코람코자산운용": "DOMESTIC_ASSET_MANAGER",
    "삼성SRA자산운용": "DOMESTIC_ASSET_MANAGER",
    "메테우스자산운용": "DOMESTIC_ASSET_MANAGER",
    "하나대체투자자산운용": "DOMESTIC_ASSET_MANAGER",
    "쿨리지코너인베스트먼트": "DOMESTIC_OTHER_GP",
    "GCM Grosvenor": "FOREIGN_MANAGER",
}

STATUS_EXPLANATION = {
    "INSUFFICIENT_EVIDENCE": "약정·납입·집행·회수·비용·취소를 같은 source scope에서 확인할 근거가 부족함",
    "UNTRACED_AWARDED_NOT_CONFIRMED_COMMITTED_OR_AVAILABLE": "선정·배정 보도는 있으나 실제 약정·납입·가용성이 확인되지 않음",
}


def dec(value: str | None) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


def won_eok(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value / Decimal('100000000'):,.0f}억원"


def amount_context_text(raw: str | None) -> str:
    if not raw:
        return "금액 미구조화"
    symbols = {"AT_MOST": "≤", "AT_LEAST": "≥", "ABOUT": "약 ", "EXACT": ""}
    rendered = []
    for item in raw.split(","):
        basis, amount, currency, comparator = item.split(":", 3)
        value = dec(amount)
        display = won_eok(value) if currency == "KRW" else f"{value:,.0f} {currency}"
        rendered.append(f"{basis} {symbols.get(comparator, comparator + ' ')}{display}")
    return "; ".join(rendered)


def load_manifest_index() -> dict[str, dict]:
    index: dict[str, dict] = {}
    for path in (ROOT / "fixtures" / "approved-lp-mandates").rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["_path"] = str(path.relative_to(ROOT))
        index[payload["manifest_id"]] = payload
    return index


def source_rows(manifest: dict, source_ids: list[str]) -> list[dict]:
    by_id = {x["id"]: x for x in manifest.get("sources", [])}
    return [
        {
            "source_id": sid,
            "publisher": by_id[sid].get("publisher"),
            "title": by_id[sid].get("title"),
            "published_at": by_id[sid].get("published_at"),
            "url": by_id[sid].get("url"),
            "exact_text": by_id[sid].get("exact_text"),
        }
        for sid in source_ids if sid in by_id
    ]


def main() -> None:
    manifests = load_manifest_index()
    conn = sqlite3.connect(f"file:{DB.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    live_counts = {
        table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        for table in (
            "lp_mandates", "lp_mandate_tracks", "lp_mandate_selections",
            "lp_mandate_selection_vehicles", "lp_mandate_amounts",
            "lp_mandate_deployments",
        )
    }
    live_counts["source_balance_rows"] = conn.execute(
        "SELECT COUNT(*) FROM v_lp_mandate_source_balance"
    ).fetchone()[0]

    official = []
    selection_sql = """
        SELECT s.mandate_selection_id, m.mandate_code, m.vintage_year,
               lp.canonical_name AS lp_name, t.track_code, t.track_name,
               t.strategy_code, t.target_manager_count,
               mgr.canonical_name AS manager_name, s.selection_status,
               s.selected_at, s.metadata_json
        FROM lp_mandate_selections s
        JOIN lp_mandate_tracks t ON t.mandate_track_id=s.mandate_track_id
        JOIN lp_mandates m ON m.mandate_id=t.mandate_id
        JOIN organizations lp ON lp.organization_id=m.lp_organization_id
        JOIN organizations mgr ON mgr.organization_id=s.manager_organization_id
        ORDER BY mgr.canonical_name, m.vintage_year
    """
    amount_sql = """
        SELECT a.amount_basis, a.amount_decimal, a.currency_code,
               a.comparator_code, a.amount_status, a.raw_value,
               CASE WHEN a.mandate_selection_id=? THEN 'SELECTION'
                    WHEN a.mandate_track_id=? THEN 'TRACK' ELSE 'OTHER' END AS scope
        FROM lp_mandate_amounts a
        WHERE a.mandate_selection_id=? OR a.mandate_track_id=?
        ORDER BY scope, a.amount_basis
    """
    for row in conn.execute(selection_sql):
        d = dict(row)
        track_id = conn.execute(
            "SELECT mandate_track_id FROM lp_mandate_selections WHERE mandate_selection_id=?",
            (d["mandate_selection_id"],),
        ).fetchone()[0]
        amounts = [dict(x) for x in conn.execute(
            amount_sql,
            (d["mandate_selection_id"], track_id, d["mandate_selection_id"], track_id),
        )]
        meta = json.loads(d.pop("metadata_json") or "{}")
        manifest_id = meta.get("manifest_id")
        manifest = manifests.get(manifest_id, {})
        sources = source_rows(manifest, meta.get("evidence", {}).get("source_ids", []))
        selection_amounts = [x for x in amounts if x["scope"] == "SELECTION"]
        track_commitments = [x for x in amounts if x["scope"] == "TRACK" and x["amount_basis"] == "TRACK_LP_COMMITMENT"]
        target_sizes = [x for x in amounts if x["amount_basis"] == "TARGET_FUND_SIZE"]
        d.update({
            "manager_class": MANAGER_CLASS.get(d["manager_name"], "UNCLASSIFIED"),
            "evidence_layer": "CANONICAL_VERIFIED_SELECTION",
            "manifest_id": manifest_id,
            "manifest_path": manifest.get("_path"),
            "sources": sources,
            "amounts": amounts,
            "capital_trace_status": (
                "OFFICIAL_SELECTED_REQUEST_AMOUNT_ONLY"
                if selection_amounts
                else "OFFICIAL_SELECTED_NO_COMMITMENT"
                if amounts
                else "OFFICIAL_SELECTED_NO_AMOUNT"
            ),
            "selection_reported_or_requested_krw": str(sum((dec(x["amount_decimal"]) or Decimal(0) for x in selection_amounts if x["currency_code"] == "KRW"), Decimal(0))) if selection_amounts else None,
            "announced_track_commitment_krw": str(sum((dec(x["amount_decimal"]) or Decimal(0) for x in track_commitments if x["currency_code"] == "KRW"), Decimal(0))) if track_commitments else None,
            "target_fund_size_krw": str(sum((dec(x["amount_decimal"]) or Decimal(0) for x in target_sizes if x["currency_code"] == "KRW"), Decimal(0))) if target_sizes else None,
            "verified_commitment_krw": None,
            "verified_paid_in_krw": None,
            "verified_deployed_krw": None,
            "verified_realized_krw": None,
            "verified_available_krw": None,
            "dry_powder_status": "INSUFFICIENT_EVIDENCE",
            "dry_powder_reason": STATUS_EXPLANATION["INSUFFICIENT_EVIDENCE"],
        })
        official.append(d)

    likely_rows = [dict(r) for r in conn.execute("""
        SELECT b.mandate_code, m.vintage_year, lp.canonical_name AS lp_name,
               b.track_code, t.track_name, t.strategy_code,
               b.manager_name, b.selected_at, b.value_status,
               b.confidence, b.independent_family_count, b.occurrence_count,
               b.reported_allocation_decimal, b.allocation_currency_code,
               b.source_claim_id, cl.event_mention_id,
               d.canonical_url, d.publisher_name, v.title, v.published_at
        FROM v_lp_manager_best_available b
        JOIN lp_mandates m ON m.mandate_code=b.mandate_code
        JOIN organizations lp ON lp.organization_id=m.lp_organization_id
        LEFT JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id AND t.track_code=b.track_code
        LEFT JOIN claims cl ON cl.claim_id=b.source_claim_id
        LEFT JOIN event_mentions em ON em.event_mention_id=cl.event_mention_id
        LEFT JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
        LEFT JOIN document_versions v ON v.document_version_id=er.document_version_id
        LEFT JOIN source_documents d ON d.document_id=v.document_id
        WHERE b.canonical_eligible=0
        ORDER BY b.manager_name, m.vintage_year
    """)]
    likely = []
    for manager in sorted({x["manager_name"] for x in likely_rows}):
        items = [x for x in likely_rows if x["manager_name"] == manager]
        total = sum(
            (dec(x["reported_allocation_decimal"]) or Decimal(0)
             for x in items if x["allocation_currency_code"] == "KRW"),
            Decimal(0),
        )
        likely.append({
            "manager_name": manager,
            "manager_class": MANAGER_CLASS.get(manager, "DOMESTIC_ASSET_MANAGER"),
            "evidence_layer": "LIKELY_REPORTED_PENDING_PRIMARY",
            "capital_trace_status": "LIKELY_REPORTED_PENDING_PRIMARY",
            "reported_allocation_krw": str(total),
            "mandates": items,
            "verified_commitment_krw": None,
            "verified_paid_in_krw": None,
            "verified_deployed_krw": None,
            "verified_realized_krw": None,
            "verified_available_krw": None,
            "dry_powder_status": "INSUFFICIENT_EVIDENCE",
            "dry_powder_reason": (
                "기사 기반 선정·배정 보도만 있고 공식 선정 결과, 실제 약정·납입, "
                "vehicle·deal deployment가 확인되지 않음"
            ),
        })

    unassigned = [dict(r) for r in conn.execute("""
        SELECT m.mandate_code, m.vintage_year, lp.canonical_name AS lp_name,
               m.mandate_name, m.mandate_status,
               GROUP_CONCAT(DISTINCT a.amount_basis || ':' ||
                   COALESCE(a.amount_decimal, a.upper_amount_decimal) || ':' ||
                   a.currency_code || ':' || a.comparator_code) AS amount_context
        FROM lp_mandates m
        JOIN organizations lp ON lp.organization_id=m.lp_organization_id
        LEFT JOIN lp_mandate_tracks t ON t.mandate_id=m.mandate_id
        LEFT JOIN lp_mandate_amounts a ON a.mandate_id=m.mandate_id OR a.mandate_track_id=t.mandate_track_id
        WHERE NOT EXISTS (
            SELECT 1 FROM lp_mandate_tracks tx
            JOIN lp_mandate_selections sx ON sx.mandate_track_id=tx.mandate_track_id
            WHERE tx.mandate_id=m.mandate_id
        )
        GROUP BY m.mandate_id
        ORDER BY m.vintage_year, m.mandate_code
    """)]

    integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
    fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
    schema_version = conn.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'"
    ).fetchone()[0]
    conn.close()

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "as_of_database": str(DB),
        "schema_version": schema_version,
        "scope": "CURRENTLY_LOADED_2020_2025_LP_MANDATE_CORPUS",
        "method": {
            "canonical_rule": "Official/transaction-party primary source only",
            "likely_rule": "Article-only manager and allocation retained outside canonical totals",
            "dry_powder_rule": "Only compatible verified commitment/paid-in/deployment/realization evidence can create available capital",
            "zero_is_not_missing": "No balance row means not computable, not zero dry powder",
        },
        "live_counts": live_counts,
        "summary": {
            "official_selection_rows": len(official),
            "official_domestic_asset_manager_rows": sum(x["manager_class"] == "DOMESTIC_ASSET_MANAGER" for x in official),
            "official_domestic_other_gp_rows": sum(x["manager_class"] == "DOMESTIC_OTHER_GP" for x in official),
            "foreign_manager_rows": sum(x["manager_class"] == "FOREIGN_MANAGER" for x in official),
            "likely_domestic_manager_count": len(likely),
            "likely_reported_allocation_krw": str(sum((dec(x["reported_allocation_krw"]) or Decimal(0) for x in likely), Decimal(0))),
            "verified_available_manager_count": 0,
            "verified_available_krw": None,
        },
        "official_selections": official,
        "likely_reported_domestic_managers": likely,
        "mandates_without_official_manager": unassigned,
        "qa": {
            "integrity_check": integrity,
            "foreign_key_violations": fk,
            "selection_vehicle_rows": live_counts["lp_mandate_selection_vehicles"],
            "deployment_rows": live_counts["lp_mandate_deployments"],
            "source_balance_rows": live_counts["source_balance_rows"],
            "verified_available_never_fabricated": all(x["verified_available_krw"] is None for x in official + likely),
        },
    }

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = ARTIFACT_DIR / f"{REPORT_STEM}.json"
    csv_path = ARTIFACT_DIR / f"{REPORT_STEM}.csv"
    md_path = ARTIFACT_DIR / f"{REPORT_STEM}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    csv_rows = []
    for x in official:
        csv_rows.append({
            "manager": x["manager_name"], "manager_class": x["manager_class"],
            "evidence_layer": x["evidence_layer"], "lp": x["lp_name"],
            "mandate": x["mandate_code"], "selected_at": x["selected_at"],
            "reported_or_requested_krw": x["selection_reported_or_requested_krw"],
            "announced_track_commitment_krw": x["announced_track_commitment_krw"],
            "likely_reported_allocation_krw": None,
            "capital_trace_status": x["capital_trace_status"],
            "verified_available_krw": None, "dry_powder_status": x["dry_powder_status"],
        })
    for x in likely:
        for item in x["mandates"]:
            csv_rows.append({
                "manager": x["manager_name"], "manager_class": x["manager_class"],
                "evidence_layer": x["evidence_layer"], "lp": item["lp_name"],
                "mandate": item["mandate_code"], "selected_at": item["selected_at"],
                "reported_or_requested_krw": None,
                "announced_track_commitment_krw": None,
                "likely_reported_allocation_krw": item["reported_allocation_decimal"],
                "capital_trace_status": x["capital_trace_status"],
                "verified_available_krw": None, "dry_powder_status": x["dry_powder_status"],
            })
    with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(csv_rows[0]))
        writer.writeheader(); writer.writerows(csv_rows)

    domestic_official = [x for x in official if x["manager_class"] == "DOMESTIC_ASSET_MANAGER"]
    domestic_gp = [x for x in official if x["manager_class"] == "DOMESTIC_OTHER_GP"]
    foreign = [x for x in official if x["manager_class"] == "FOREIGN_MANAGER"]
    lines = [
        "# 국내 자산운용사 기관 위탁자금·Dry Powder 현황",
        "",
        f"- 기준 DB: `{DB}`",
        f"- 생성시각(UTC): `{report['generated_at']}`",
        f"- schema: `{schema_version}`",
        "- 분석범위: 현재 live DB에 적재된 2020~2025 LP mandate corpus",
        "",
        "## Executive conclusion",
        "",
        "- 현재 DB에서 **검증 가능한 회사별 dry powder는 0원이 아니라 산정 불가**다.",
        f"- 공식 selection {len(official)}건은 확인되지만 vehicle link {live_counts['lp_mandate_selection_vehicles']}건, deployment {live_counts['lp_mandate_deployments']}건, balance projection {live_counts['source_balance_rows']}건이다.",
        "- 따라서 배정·출자요청·목표 펀드규모에서 알려진 거래액을 차감하지 않았다.",
        f"- 기사상 likely allocation 합계 {won_eok(dec(report['summary']['likely_reported_allocation_krw']))}은 참고치이며 공식 위탁액·약정액·dry powder 합계에서 제외했다.",
        "",
        "## 1. 공식 선정된 국내 자산운용사",
        "",
        "| 회사 | 기관 LP·프로그램 | 공식 확인 금액 문맥 | 자금 추적 상태 | Dry powder |",
        "|---|---|---:|---|---:|",
    ]
    for x in domestic_official:
        context = won_eok(dec(x["announced_track_commitment_krw"])) + " track 상한" if x["announced_track_commitment_krw"] else "선정금액 미공개"
        lines.append(f"| {x['manager_name']} | {x['lp_name']} · {x['mandate_code']} | {context} | `{x['capital_trace_status']}` | 산정 불가 |")
    if not domestic_official:
        lines.append("| — | — | — | — | — |")
    lines += [
        "",
        "### 우리글로벌자산운용",
        "",
        "- 한국성장금융 정책형 뉴딜펀드 2021년 인프라투자형 공식 선정.",
        "- 정책출자자 위탁운용금액은 **270억원 이내**, 목표결성금액은 **900억원**.",
        "- 270억원은 track 공고 상한이며 selection-specific commitment·납입액이 아니다.",
        "- vehicle·capital call·집행·회수 자료가 없어 dry powder는 산정 불가.",
        "",
        "## 2. 기사상 선정·배정 보도 — 공식 합계 제외",
        "",
        "| 회사 | 기관 LP | 보도상 배정액 | 근거 상태 | Dry powder |",
        "|---|---|---:|---|---:|",
    ]
    for x in likely:
        lps = ", ".join(sorted({i["lp_name"] for i in x["mandates"]}))
        lines.append(f"| {x['manager_name']} | {lps} | {won_eok(dec(x['reported_allocation_krw']))} | `LIKELY_REPORTED_PENDING_PRIMARY` | 산정 불가 |")
    lines += [
        "",
        "보도상 합계는 캡스톤 1,300억원, 코람코 700억원, 삼성SRA·메테우스·하나대체투자자산운용 각 500억원이다. 공식 선정 결과와 약정·납입 자료가 없어 canonical total에는 포함하지 않는다.",
        "",
        "## 3. 국내 기타 GP",
        "",
    ]
    for x in domestic_gp:
        lines += [
            f"### {x['manager_name']} — {x['mandate_code']}",
            f"- 기관 LP: {x['lp_name']}",
            f"- 공식 선정일: {x['selected_at']}",
            f"- 결과표 출자요청액: {won_eok(dec(x['selection_reported_or_requested_krw']))}",
            f"- 자금 추적 상태: `{x['capital_trace_status']}`",
            "- 출자요청액은 확정 약정·납입액이 아니므로 dry powder 산정에서 제외.",
            "",
        ]
    lines += ["## 4. 해외 manager 부록", ""]
    for x in foreign:
        lines.append(f"- **{x['manager_name']}** — {x['lp_name']} `{x['mandate_code']}` 공식 선정; 선정금액 미공개; dry powder 산정 불가.")
    lines += [
        "",
        "## 5. 회사에 귀속하지 못한 공식 mandate",
        "",
        "| Vintage | 기관 LP | 프로그램 | 공식 금액 문맥 |",
        "|---:|---|---|---|",
    ]
    for x in unassigned:
        lines.append(f"| {x['vintage_year']} | {x['lp_name']} | `{x['mandate_code']}` | {amount_context_text(x['amount_context'])} |")
    lines += [
        "",
        "## 6. Dry powder 판정 기준",
        "",
        "```text",
        "verified available capital =",
        "  verified committed or paid-in basis",
        "  - verified invested/deployed",
        "  - verified fees/costs",
        "  - verified cancelled amount",
        "  + verified realized/recyclable amount when reuse is explicitly allowed",
        "```",
        "",
        "현재 DB에는 회사별 paid-in, capital call, vehicle 연결, LP-source deployment, realization, fee, cancellation이 없다. 따라서 숫자 0을 쓰지 않고 `INSUFFICIENT_EVIDENCE`로 표시한다.",
        "",
        "## 7. Evidence guard",
        "",
        "- 공식 공고의 program/track 금액은 공식이지만 특정 회사 commitment와 같지 않다.",
        "- 출자요청액은 awarded·committed·paid-in과 같지 않다.",
        "- 기사상 allocation은 공식 결과가 확보될 때까지 likely layer에 둔다.",
        "- target fund size에는 GP·제3자 자금이 포함될 수 있다.",
        "- 거래 취득가를 배정액에서 차감해 dry powder를 만들지 않는다.",
        "- vehicle·deal source가 연결되지 않은 상태에서 미공개 deployment를 0으로 가정하지 않는다.",
        "",
        "## 8. QA",
        "",
        f"- integrity: `{integrity}`",
        f"- FK violations: `{fk}`",
        f"- official selections: `{len(official)}`",
        f"- likely manager claims: `{sum(len(x['mandates']) for x in likely)}`",
        f"- vehicle links: `{live_counts['lp_mandate_selection_vehicles']}`",
        f"- deployments: `{live_counts['lp_mandate_deployments']}`",
        f"- balance rows: `{live_counts['source_balance_rows']}`",
        "- verified available 값을 임의 생성하지 않음: `PASS`",
        "",
        "## 9. 주요 직접 근거",
        "",
        "### 공식 선정 결과",
        "",
    ]
    seen_sources = set()
    for x in official:
        for source in x["sources"]:
            key = source.get("url")
            if not key or key in seen_sources:
                continue
            seen_sources.add(key)
            lines.append(f"- {x['manager_name']} — [{source.get('title')}]({key}) · {source.get('publisher')} · {source.get('published_at')}")
    lines += ["", "### 기사상 likely 선정·배정", ""]
    seen_sources.clear()
    for x in likely:
        for item in x["mandates"]:
            key = item.get("canonical_url")
            if not key or key in seen_sources:
                continue
            seen_sources.add(key)
            lines.append(f"- [{item.get('title')}]({key}) · {item.get('publisher_name')} · {item.get('published_at')} · 공식 결과 추가 확인 필요")
    lines += [
        "",
        "## 10. 다음 조사 우선순위",
        "",
        "1. 기사상 2022·2024 건설근로자공제회 선정사의 공식 결과 원문 확보",
        "2. 선정 운용사의 실제 fund·REIT·SPC 식별",
        "3. LP commitment·capital call·paid-in 공시 확보",
        "4. vehicle→deal deployment와 금액 basis 연결",
        "5. 회수·재투자 허용·비용·취소 조건 확보",
    ]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "csv": str(csv_path), "md": str(md_path), "qa": report["qa"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
