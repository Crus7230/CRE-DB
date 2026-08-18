#!/usr/bin/env python
"""Render manager-by-manager LP mandate chapters from the audited base report."""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
BASE_STEM = "institutional-manager-capital-and-dry-powder-20260816"
OUT_STEM = "manager-by-manager-institutional-lp-fund-report-20260816"

ORDER = [
    "우리글로벌자산운용", "캡스톤자산운용", "코람코자산운용",
    "삼성SRA자산운용", "메테우스자산운용", "하나대체투자자산운용",
    "쿨리지코너인베스트먼트", "GCM Grosvenor",
]


def D(value):
    return Decimal(value) if value not in (None, "") else None


def eok(value):
    v = D(value)
    return "—" if v is None else f"{v / Decimal('100000000'):,.0f}억원"


def sum_values(items, key):
    values = [D(x.get(key)) for x in items if D(x.get(key)) is not None]
    return sum(values, Decimal(0)) if values else None


def comparator_prefix(code):
    return {"AT_MOST": "≤", "AT_LEAST": "≥", "ABOUT": "약 ", "EXACT": ""}.get(code, "")


def money(value, currency, comparator="EXACT"):
    if value is None:
        return "—"
    v = D(value)
    display = eok(v) if currency == "KRW" else f"{v:,.0f} {currency}"
    return comparator_prefix(comparator) + display


def amount_context_display(raw):
    if not raw:
        return "—"
    rendered = []
    labels = {
        "PROGRAM_TOTAL": "프로그램 총액",
        "TRACK_LP_COMMITMENT": "track 기관재원",
        "ALLOCATION_PER_MANAGER": "운용사당 상한",
        "TARGET_FUND_SIZE": "펀드 목표규모",
    }
    for item in raw.split(","):
        basis, value, currency, comparator = item.split(":", 3)
        rendered.append(f"{labels.get(basis, basis)} {money(value, currency, comparator)}")
    return "; ".join(rendered)


def manifest_index():
    index = {}
    for path in (ROOT / "fixtures" / "approved-lp-mandates").rglob("*.json"):
        d = json.loads(path.read_text(encoding="utf-8"))
        d["_path"] = str(path.relative_to(ROOT))
        index[d["mandate"]["mandate_code"]] = d
    return index


def official_program_sources(manifest):
    return [
        {k: src.get(k) for k in ("title", "publisher", "published_at", "url", "document_type")}
        for src in manifest.get("sources", [])
    ]


def main():
    subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "report_institutional_manager_capital.py")],
        cwd=ROOT, check=True, capture_output=True, text=True,
    )
    base_path = ROOT / "artifacts" / f"{BASE_STEM}.json"
    base = json.loads(base_path.read_text(encoding="utf-8"))
    manifests = manifest_index()
    unassigned = {x["mandate_code"]: x for x in base["mandates_without_official_manager"]}

    chapters = defaultdict(lambda: {
        "manager_name": None, "manager_class": None, "evidence_layers": set(),
        "programs": [], "capital_trace_statuses": set(),
    })

    for x in base["official_selections"]:
        c = chapters[x["manager_name"]]
        c["manager_name"] = x["manager_name"]
        c["manager_class"] = x["manager_class"]
        c["evidence_layers"].add(x["evidence_layer"])
        c["capital_trace_statuses"].add(x["capital_trace_status"])
        manifest = manifests.get(x["mandate_code"], {})
        c["programs"].append({
            "vintage_year": x["vintage_year"],
            "lp_name": x["lp_name"],
            "mandate_code": x["mandate_code"],
            "track_name": x["track_name"],
            "strategy_code": x["strategy_code"],
            "selection_status": x["selection_status"],
            "selected_at": x["selected_at"],
            "evidence_layer": x["evidence_layer"],
            "capital_trace_status": x["capital_trace_status"],
            "official_track_cap_krw": x["announced_track_commitment_krw"],
            "selection_requested_or_reported_krw": x["selection_reported_or_requested_krw"],
            "target_fund_size_krw": x["target_fund_size_krw"],
            "likely_reported_allocation_krw": None,
            "verified_commitment_krw": None,
            "verified_paid_in_krw": None,
            "verified_deployed_krw": None,
            "verified_available_krw": None,
            "dry_powder_status": x["dry_powder_status"],
            "official_sources": official_program_sources(manifest),
            "media_source": None,
            "amount_rows": x["amounts"],
        })

    for x in base["likely_reported_domestic_managers"]:
        c = chapters[x["manager_name"]]
        c["manager_name"] = x["manager_name"]
        c["manager_class"] = x["manager_class"]
        c["evidence_layers"].add(x["evidence_layer"])
        c["capital_trace_statuses"].add(x["capital_trace_status"])
        for item in x["mandates"]:
            manifest = manifests.get(item["mandate_code"], {})
            context = unassigned.get(item["mandate_code"], {})
            c["programs"].append({
                "vintage_year": item["vintage_year"],
                "lp_name": item["lp_name"],
                "mandate_code": item["mandate_code"],
                "track_name": item["track_name"],
                "strategy_code": item["strategy_code"],
                "selection_status": "REPORTED_SELECTED",
                "selected_at": item["selected_at"],
                "evidence_layer": x["evidence_layer"],
                "capital_trace_status": x["capital_trace_status"],
                "official_program_amount_context": context.get("amount_context"),
                "official_track_cap_krw": None,
                "selection_requested_or_reported_krw": None,
                "target_fund_size_krw": None,
                "likely_reported_allocation_krw": item["reported_allocation_decimal"],
                "verified_commitment_krw": None,
                "verified_paid_in_krw": None,
                "verified_deployed_krw": None,
                "verified_available_krw": None,
                "dry_powder_status": x["dry_powder_status"],
                "official_sources": official_program_sources(manifest),
                "media_source": {
                    "publisher": item.get("publisher_name"), "title": item.get("title"),
                    "published_at": item.get("published_at"), "url": item.get("canonical_url"),
                },
                "amount_rows": [],
            })

    serial = []
    for manager in ORDER:
        if manager not in chapters:
            continue
        c = chapters[manager]
        c["programs"].sort(key=lambda x: (x["vintage_year"], x["mandate_code"]))
        c["evidence_layers"] = sorted(c["evidence_layers"])
        c["capital_trace_statuses"] = sorted(c["capital_trace_statuses"])
        c["summary"] = {
            "lp_count": len({x["lp_name"] for x in c["programs"]}),
            "program_count": len(c["programs"]),
            "official_track_cap_krw": str(sum_values(c["programs"], "official_track_cap_krw")) if sum_values(c["programs"], "official_track_cap_krw") is not None else None,
            "selection_requested_or_reported_krw": str(sum_values(c["programs"], "selection_requested_or_reported_krw")) if sum_values(c["programs"], "selection_requested_or_reported_krw") is not None else None,
            "target_fund_size_krw": str(sum_values(c["programs"], "target_fund_size_krw")) if sum_values(c["programs"], "target_fund_size_krw") is not None else None,
            "likely_reported_allocation_krw": str(sum_values(c["programs"], "likely_reported_allocation_krw")) if sum_values(c["programs"], "likely_reported_allocation_krw") is not None else None,
            "verified_commitment_krw": None,
            "verified_available_krw": None,
            "dry_powder_status": "INSUFFICIENT_EVIDENCE",
        }
        serial.append(c)

    payload = {
        "generated_at": base["generated_at"],
        "database": base["as_of_database"],
        "schema_version": base["schema_version"],
        "scope": base["scope"],
        "manager_count": len(serial),
        "chapters": serial,
        "global_guard": {
            "verified_commitment_rows": 0,
            "selection_vehicle_rows": base["live_counts"]["lp_mandate_selection_vehicles"],
            "deployment_rows": base["live_counts"]["lp_mandate_deployments"],
            "source_balance_rows": base["live_counts"]["source_balance_rows"],
            "dry_powder_rule": "No number when compatible commitment/paid-in/deployment/realization is absent",
        },
    }
    out_json = ROOT / "artifacts" / f"{OUT_STEM}.json"
    out_md = ROOT / "artifacts" / f"{OUT_STEM}.md"
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 운용사별 기관 LP 위탁운용펀드·Dry Powder 통합보고서",
        "",
        f"- 기준 DB: `{payload['database']}`",
        f"- schema: `{payload['schema_version']}`",
        "- 범위: 현재 적재된 2020~2025 LP mandate 자료",
        "- 금액 원칙: 펀드 목표규모·기관 공고액·출자요청액·기사상 배정액·확정 commitment를 분리",
        "",
        "## Executive summary",
        "",
        "현재 DB로는 각 운용사가 어떤 LP 프로그램에 선정·보도됐는지와 금액 문맥은 정리할 수 있다. 다만 현재 운용 중인 순자산이나 실제 남은 dry powder는 확인할 수 없다.",
        "",
        "| 운용사 | LP·프로그램 | 관리규모로 참고 가능한 금액 문맥 | 근거 상태 | 확인 dry powder |",
        "|---|---:|---|---|---:|",
    ]
    for c in serial:
        s = c["summary"]
        contexts = []
        if s["target_fund_size_krw"]:
            contexts.append(f"펀드 목표/결성예정 {eok(s['target_fund_size_krw'])}")
        if s["official_track_cap_krw"]:
            contexts.append(f"기관 track 공고액 {eok(s['official_track_cap_krw'])}")
        if s["selection_requested_or_reported_krw"]:
            contexts.append(f"출자요청·결과표 {eok(s['selection_requested_or_reported_krw'])}")
        if s["likely_reported_allocation_krw"]:
            contexts.append(f"기사상 배정 {eok(s['likely_reported_allocation_krw'])}")
        if not contexts:
            contexts.append("금액 미공개")
        status = ", ".join(f"`{x}`" for x in c["capital_trace_statuses"])
        lines.append(f"| {c['manager_name']} | {s['lp_count']}개 LP · {s['program_count']}개 프로그램 | {'; '.join(contexts)} | {status} | 산정 불가 |")

    lines += [
        "",
        "### 표 읽는 법",
        "",
        "- **펀드 목표/결성예정액**: LP 외 제3자·GP 자금을 포함할 수 있어 기관 위탁액이 아니다.",
        "- **기관 track 공고액**: 프로그램 단계의 예산·상한이며 운용사 확정 commitment가 아니다.",
        "- **출자요청액**: 선정결과에 실렸어도 확정 약정·납입액은 아니다.",
        "- **기사상 배정액**: 공식 결과가 확보되지 않은 likely 정보다.",
        "- **확인 dry powder**: 약정·납입·집행·회수 자료가 없어 모든 회사가 산정 불가다.",
    ]

    for idx, c in enumerate(serial, 1):
        s = c["summary"]
        lines += [
            "",
            f"## {idx}. {c['manager_name']}",
            "",
            f"- 분류: `{c['manager_class']}`",
            f"- 연결 LP: {', '.join(sorted({x['lp_name'] for x in c['programs']}))}",
            f"- 프로그램 수: {s['program_count']}건",
            f"- 자금 추적 상태: {', '.join(f'`{x}`' for x in c['capital_trace_statuses'])}",
            f"- 검증된 commitment: **{eok(s['verified_commitment_krw'])}**",
            f"- 검증된 dry powder: **산정 불가** (`{s['dry_powder_status']}`)",
            "",
            "### 프로그램별 현황",
            "",
            "| 연도 | 기관 LP | 프로그램·전략 | 자금 추적 상태 | 펀드 목표규모 | 공식 공고 규모 | 출자요청/결과표 | 기사상 배정 |",
            "|---:|---|---|---|---:|---:|---:|---:|",
        ]
        for p in c["programs"]:
            official_context = (
                eok(p["official_track_cap_krw"])
                if p["official_track_cap_krw"]
                else amount_context_display(p.get("official_program_amount_context"))
            )
            lines.append(
                f"| {p['vintage_year']} | {p['lp_name']} | `{p['mandate_code']}` · {p['track_name'] or p['strategy_code'] or '미분류'} | "
                f"`{p['capital_trace_status']}` | {eok(p['target_fund_size_krw'])} | {official_context} | "
                f"{eok(p['selection_requested_or_reported_krw'])} | {eok(p['likely_reported_allocation_krw'])} |"
            )

        lines += ["", "### 해석", ""]
        if c["manager_name"] == "우리글로벌자산운용":
            lines += [
                "- 한국성장금융 정책형 뉴딜펀드 인프라투자형의 공식 선정 운용사다.",
                "- 펀드 목표규모 900억원, 정책출자자 위탁운용금액 270억원 이내다.",
                "- 270억원은 단일 manager track의 공식 상한이지만 실제 약정·납입·현재 운용잔액은 확인되지 않았다.",
            ]
        elif c["manager_name"] == "쿨리지코너인베스트먼트":
            lines += [
                "- 한국모태펀드 도시재생 분야에 2020·2021년 두 차례 공식 선정됐다.",
                "- 결성예정/목표액 합계 375억원, 결과표상 출자요청액 합계 300억원이다.",
                "- 300억원은 확정 commitment가 아니므로 현재 AUM이나 dry powder로 표시하지 않는다.",
            ]
        elif c["manager_name"] == "GCM Grosvenor":
            lines += [
                "- 대한지방행정공제회 글로벌 사모인프라 SMA 공식 선정사다.",
                "- 공개된 선정금액이 없고 해외 manager이므로 국내 운용사 합계와 분리한다.",
            ]
        else:
            lines += [
                f"- 건설근로자공제회 위탁운용사로 보도됐으며 현재 적재된 기사상 배정액 합계는 {eok(s['likely_reported_allocation_krw'])}이다.",
                "- 공식 공고는 프로그램과 상한을 확인하지만 공식 선정결과 원문은 확보되지 않았다.",
                "- 따라서 해당 금액은 likely allocation이며 실제 약정·납입·현재 운용잔액으로 확정할 수 없다.",
            ]

        lines += ["", "### 근거", ""]
        seen = set()
        for p in c["programs"]:
            for src in p["official_sources"]:
                url = src.get("url")
                if url and url not in seen:
                    seen.add(url)
                    lines.append(f"- 공식: [{src.get('title')}]({url}) · {src.get('publisher')} · {src.get('published_at')}")
            src = p.get("media_source")
            if src and src.get("url") and src["url"] not in seen:
                seen.add(src["url"])
                lines.append(f"- 기사/likely: [{src.get('title')}]({src.get('url')}) · {src.get('publisher')} · {src.get('published_at')}")

    lines += [
        "",
        "## 공통 Dry Powder 결론",
        "",
        "```text",
        "현재 DB: selection은 있으나 commitment·paid-in·vehicle·deployment·realized가 없음",
        "따라서: company dry powder = NULL / INSUFFICIENT_EVIDENCE",
        "금지: 배정액 - 0 = dry powder",
        "```",
        "",
        "향후 공식 commitment, capital call, vehicle, deal deployment가 연결되면 같은 챕터에 자동으로 추가할 수 있다.",
    ]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(out_json), "md": str(out_md), "manager_count": len(serial)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
