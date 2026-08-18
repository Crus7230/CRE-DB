#!/usr/bin/env python
"""Generate integrated QA and coverage reports for 2020-2025 LP mandates."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
ARTIFACTS = {
    "pensions_mutual_aid": ROOT / "artifacts" / "lp-manager-selections-2020-2025-pensions-mutual-aid.json",
    "policy_funds": ROOT / "artifacts" / "lp-manager-selections-2020-2025-policy-funds.json",
    "financial_other_lps": ROOT / "artifacts" / "lp-manager-selections-2020-2025-financial-other-lps.json",
}
OUT_JSON = ROOT / "artifacts" / "lp-mandates-2020-2025-integrated-qa.json"
OUT_MD = ROOT / "artifacts" / "lp-mandates-2020-2025-integrated-qa.md"


def rows(conn: sqlite3.Connection, sql: str) -> list[dict]:
    return [dict(row) for row in conn.execute(sql)]


def research_count(payload: dict) -> int:
    for key in ("records", "mandates", "items", "results"):
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def main() -> None:
    research = {}
    for name, path in ARTIFACTS.items():
        payload = json.loads(path.read_text(encoding="utf-8"))
        research[name] = {"path": str(path.relative_to(ROOT)), "record_count": research_count(payload)}

    approved_files = sorted((ROOT / "fixtures" / "approved-lp-mandates").rglob("*.json"))
    candidate_files = sorted((ROOT / "fixtures" / "lp-mandate-candidates").rglob("*.json"))
    speculative_files = sorted((ROOT / "artifacts" / "lp-mandate-speculative").rglob("*.json"))
    for path in approved_files + candidate_files + speculative_files:
        json.loads(path.read_text(encoding="utf-8"))

    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    tables = [
        "lp_mandates", "lp_mandate_tracks", "lp_mandate_guidelines",
        "lp_mandate_selections", "lp_mandate_selection_members",
        "lp_mandate_selection_vehicles", "lp_mandate_amounts",
        "lp_mandate_deployments",
    ]
    counts = {table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables}
    mandates = rows(conn, """
        SELECT m.mandate_code, m.vintage_year, o.canonical_name AS lp,
               m.mandate_name, m.mandate_status
        FROM lp_mandates m
        JOIN organizations o ON o.organization_id = m.lp_organization_id
        ORDER BY m.vintage_year, m.mandate_code
    """)
    selections = rows(conn, """
        SELECT m.mandate_code, o.canonical_name AS manager,
               s.selection_status, s.selected_at
        FROM lp_mandate_selections s
        JOIN lp_mandate_tracks t ON t.mandate_track_id = s.mandate_track_id
        JOIN lp_mandates m ON m.mandate_id = t.mandate_id
        JOIN organizations o ON o.organization_id = s.manager_organization_id
        ORDER BY m.mandate_code
    """)
    likely_selections = rows(conn, """
        SELECT mandate_code, track_code, manager_name, selected_at,
               value_status, canonical_eligible, confidence,
               independent_family_count, occurrence_count,
               reported_allocation_decimal, allocation_currency_code
        FROM v_lp_manager_best_available
        WHERE canonical_eligible=0
        ORDER BY mandate_code, manager_name
    """)
    amounts = rows(conn, """
        SELECT amount_basis, currency_code, COUNT(*) AS row_count,
               SUM(CAST(COALESCE(amount_decimal, upper_amount_decimal) AS NUMERIC)) AS numeric_sum
        FROM lp_mandate_amounts
        GROUP BY amount_basis, currency_code
        ORDER BY amount_basis, currency_code
    """)
    reviewed_tables = [
        "lp_mandates", "lp_mandate_tracks", "lp_mandate_guidelines",
        "lp_mandate_selections", "lp_mandate_amounts", "lp_mandate_deployments",
    ]
    checks = {
        "period_violations": conn.execute(
            "SELECT COUNT(*) FROM lp_mandates WHERE vintage_year NOT BETWEEN 2020 AND 2025"
        ).fetchone()[0],
        "unapproved_live_rows": sum(
            conn.execute(f"SELECT COUNT(*) FROM {table} WHERE review_status <> 'APPROVED'").fetchone()[0]
            for table in reviewed_tables
        ),
        "guidelines_without_source_claim": conn.execute(
            "SELECT COUNT(*) FROM lp_mandate_guidelines WHERE source_claim_id IS NULL"
        ).fetchone()[0],
        "amounts_without_source_claim": conn.execute(
            "SELECT COUNT(*) FROM lp_mandate_amounts WHERE source_claim_id IS NULL"
        ).fetchone()[0],
        "deployment_rows": counts["lp_mandate_deployments"],
        "source_balance_rows": conn.execute("SELECT COUNT(*) FROM v_lp_mandate_source_balance").fetchone()[0],
        "likely_manager_claims": conn.execute("SELECT COUNT(*) FROM claims WHERE predicate_code='LP_MANDATE_REPORTED_SELECTED_MANAGER' AND verification_status='PENDING' AND review_status='ACCEPTED'").fetchone()[0],
        "likely_allocation_claims": conn.execute("SELECT COUNT(*) FROM claims WHERE predicate_code='LP_MANDATE_REPORTED_MANAGER_ALLOCATION' AND verification_status='PENDING' AND review_status='ACCEPTED'").fetchone()[0],
        "foreign_key_violations": len(conn.execute("PRAGMA foreign_key_check").fetchall()),
        "integrity_check": conn.execute("PRAGMA integrity_check").fetchone()[0],
    }
    schema_version = conn.execute(
        "SELECT schema_value FROM schema_meta WHERE schema_key = 'schema_version'"
    ).fetchone()[0]
    conn.close()

    checks["pass"] = all([
        checks["period_violations"] == 0,
        checks["unapproved_live_rows"] == 0,
        checks["guidelines_without_source_claim"] == 0,
        checks["amounts_without_source_claim"] == 0,
        checks["foreign_key_violations"] == 0,
        checks["integrity_check"] == "ok",
    ])

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database": str(DB),
        "schema_version": schema_version,
        "research_artifacts": research,
        "fixture_counts": {
            "approved_manifests": len(approved_files),
            "retained_review_candidates": len(candidate_files),
            "speculative_verification_candidates": len(speculative_files),
        },
        "live_counts": counts,
        "canonical_mandates": mandates,
        "officially_supported_selections": selections,
        "likely_reported_selections_pending_primary": likely_selections,
        "amounts_by_basis_and_currency": amounts,
        "qa_checks": checks,
        "interpretation": {
            "unknown_manager_policy": "Canonical manager remains absent without a primary result, while concrete reports are shown in best-available projections with a non-canonical likely status.",
            "requested_amount_policy": "Selection request amounts remain OTHER and are not promoted to confirmed LP commitments.",
            "balance_policy": "Target fund size and announced/requested amounts do not create deployable source balance.",
            "deployment_policy": "No vehicle-to-deal deployment is created without official vehicle and deal evidence.",
            "news_only_policy": "Detailed reports may enter the relational verification layer as likely claims, but remain excluded from lp_mandate_selections, commitment balances and deployments.",
        },
        "coverage_gaps": [
            "국민연금·우정사업본부·군인공제회·경찰공제회·과학기술인공제회는 공식 게시판 전수 역탐색이 추가로 필요함.",
            "공무원연금·교직원공제회·건설근로자공제회·우정사업본부의 일부 선정사명은 언론 근거만 있어 REVIEW_READY 또는 research-only로 유지함.",
            "KIC·HUG·캠코·IBK 및 도시재생 후속 연도는 공식 계획–결과 쌍을 충분히 확보하지 못함.",
            "공식 fund·REIT·SPC와 특정 deal의 연결 증거가 아직 없어 deployment와 residual source를 의도적으로 생성하지 않음.",
        ],
    }
    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 2020-2025 국내 LP 위탁운용 통합 QA·Coverage",
        "",
        f"- 생성시각(UTC): `{report['generated_at']}`",
        f"- DB: `{DB}`",
        f"- schema: `{schema_version}`",
        f"- QA: **{'PASS' if checks['pass'] else 'FAIL'}**",
        "",
        "## Live canonical coverage",
        "",
        f"- 승인 mandate: **{counts['lp_mandates']}건**",
        f"- 전략 track: **{counts['lp_mandate_tracks']}건**",
        f"- 공식 선정 manager row: **{counts['lp_mandate_selections']}건**",
        f"- 관계형 유력 manager claim: **{checks['likely_manager_claims']}건**",
        f"- 관계형 유력 배정금액 claim: **{checks['likely_allocation_claims']}건**",
        f"- 추측성·검증대기 manifest: **{len(speculative_files)}건**",
        f"- 구조화 guideline: **{counts['lp_mandate_guidelines']}건**",
        f"- 금액 row: **{counts['lp_mandate_amounts']}건**",
        f"- vehicle link: **{counts['lp_mandate_selection_vehicles']}건**",
        f"- deal deployment: **{counts['lp_mandate_deployments']}건**",
        f"- residual source projection: **{checks['source_balance_rows']}건**",
        "",
        "## Officially supported selections",
        "",
    ]
    lines += [f"- `{x['mandate_code']}` — **{x['manager']}** ({x['selected_at']})" for x in selections]
    lines += ["", "## Likely reported selections pending primary verification", ""]
    lines += [f"- `{x['mandate_code']}` — **{x['manager_name']}** · `{x['value_status']}` · `{x['reported_allocation_decimal']} {x['allocation_currency_code']}` · confidence `{x['confidence']}`" for x in likely_selections]
    lines += [
        "",
        "## QA checks",
        "",
        f"- 2020~2025 범위 위반: `{checks['period_violations']}`",
        f"- 미승인 live row: `{checks['unapproved_live_rows']}`",
        f"- source claim 없는 guideline: `{checks['guidelines_without_source_claim']}`",
        f"- source claim 없는 amount: `{checks['amounts_without_source_claim']}`",
        f"- FK 위반: `{checks['foreign_key_violations']}`",
        f"- integrity: `{checks['integrity_check']}`",
        "",
        "## Interpretation guards",
        "",
        "- 공식 결과가 없는 mandate의 canonical manager는 비우되 best-available 조회에는 유력정보 상태로 표시함.",
        "- 기사 기반 선정사·귀속금액은 relational verification layer에 보관하고 canonical selection·잔액·deployment에서 제외함.",
        "- `출자요청액`은 확정 약정·납입액으로 승격하지 않음.",
        "- `TARGET_FUND_SIZE`는 LP source balance에 포함하지 않음.",
        "- 공식 vehicle·deal 증거가 없으므로 deployment와 residual source는 0건이 정상.",
        "",
        "## Coverage gaps",
        "",
    ]
    lines += [f"- {gap}" for gap in report["coverage_gaps"]]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(OUT_JSON), "md": str(OUT_MD), "qa_pass": checks["pass"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
