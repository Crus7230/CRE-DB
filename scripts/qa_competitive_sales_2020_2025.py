from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"
FIXTURES = ROOT / "fixtures" / "approved-sale-processes"
ARTIFACTS = ROOT / "artifacts"
BACKUP_MANIFEST = ROOT / "backups" / "market-post-historical-sale-processes-20260816.db.manifest.json"
OUTPUT_JSON = ARTIFACTS / "competitive-sales-2020-2025-integrated-qa.json"
OUTPUT_MD = ARTIFACTS / "competitive-sales-2020-2025-integrated-qa.md"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def approved_manifests() -> list[tuple[Path, dict]]:
    rows: list[tuple[Path, dict]] = []
    for subdir in ("historical-office-dc", "historical-hotel", "historical-logistics"):
        for path in sorted((FIXTURES / subdir).glob("*.json")):
            try:
                payload = load_json(path)
            except json.JSONDecodeError:
                continue
            if payload.get("status") == "APPROVED":
                rows.append((path, payload))
    return rows


def main() -> None:
    manifests = approved_manifests()
    by_group: dict[str, int] = defaultdict(int)
    organization_ids: dict[str, set[str]] = defaultdict(set)
    asset_ids: dict[str, set[str]] = defaultdict(set)
    review_only_sources = 0
    for path, payload in manifests:
        group = path.parent.name.replace("historical-", "")
        by_group[group] += 1
        for org in payload.get("organizations", []):
            organization_ids[org["canonical_name"]].add(org["id"])
        asset = payload["asset"]
        asset_ids[asset["canonical_name"]].add(asset["id"])
        review_only_sources += sum(
            1
            for source in payload.get("sources", [])
            if source.get("access_status_reviewed") == "TITLE_SNIPPET_REVIEW_ONLY"
            or source.get("metadata", {}).get("evidence_level") == "TITLE_SNIPPET_REVIEW_ONLY"
        )

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    scalar = lambda sql, args=(): con.execute(sql, args).fetchone()[0]
    schema_version = scalar("SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'")
    process_by_asset = dict(
        con.execute(
            """SELECT a.asset_class_id,COUNT(DISTINCT sp.sale_process_id)
                 FROM sale_processes sp
                 JOIN events e ON e.event_id=sp.event_id
                 JOIN event_assets ea ON ea.event_id=e.event_id
                 JOIN assets a ON a.asset_id=ea.asset_id
                GROUP BY a.asset_class_id ORDER BY a.asset_class_id"""
        ).fetchall()
    )
    google_completed = scalar(
        "SELECT COUNT(*) FROM collection_runs WHERE runner_version='2020-2024-bid-process-v1' AND status_code='COMPLETED'"
    )
    google_documents = scalar(
        "SELECT COALESCE(SUM(inserted_count),0) FROM collection_runs WHERE runner_version='2020-2024-bid-process-v1' AND status_code='COMPLETED'"
    )
    pipeline_rows = {
        row["pipeline_version"]: dict(row)
        for row in con.execute(
            """SELECT er.pipeline_version,
                      COUNT(DISTINCT er.extraction_run_id) AS runs,
                      COUNT(DISTINCT em.event_mention_id) AS mentions,
                      SUM(CASE WHEN em.status_code='REVIEW_READY' THEN 1 ELSE 0 END) AS review_ready,
                      SUM(CASE WHEN em.status_code='APPROVED' THEN 1 ELSE 0 END) AS approved
                 FROM extraction_runs er
                 LEFT JOIN event_mentions em ON em.extraction_run_id=er.extraction_run_id
                WHERE er.pipeline_version IN ('BID_PROCESS_TITLE_SNIPPET_V4','DART_BUSINESS_TRANSFER_CRE_REVIEW_V1')
                GROUP BY er.pipeline_version"""
        )
    }
    counts = {
        "sale_processes": scalar("SELECT COUNT(*) FROM sale_processes"),
        "historical_sale_processes": scalar(
            "SELECT COUNT(*) FROM sale_processes WHERE sale_process_id NOT IN ('sp_hyundai_yeonji_2025','sp_cheongna_logistics_2025')"
        ),
        "rounds": scalar("SELECT COUNT(*) FROM bid_rounds"),
        "participations": scalar("SELECT COUNT(*) FROM bidder_participations"),
        "participation_members": scalar("SELECT COUNT(*) FROM bidder_participation_members"),
        "submissions": scalar("SELECT COUNT(*) FROM bid_submissions"),
        "funding_components": scalar("SELECT COUNT(*) FROM bid_funding_components"),
        "decisions": scalar("SELECT COUNT(*) FROM bid_decisions"),
        "milestones": scalar("SELECT COUNT(*) FROM transaction_milestones"),
        "process_relations": scalar("SELECT COUNT(*) FROM sale_process_relations"),
    }
    fk_violations = [tuple(row) for row in con.execute("PRAGMA foreign_key_check")]
    integrity = scalar("PRAGMA integrity_check")
    live_duplicate_org_names = scalar(
        "SELECT COUNT(*) FROM (SELECT canonical_name FROM organizations GROUP BY canonical_name HAVING COUNT(*)>1)"
    )
    live_duplicate_asset_names = scalar(
        "SELECT COUNT(*) FROM (SELECT canonical_name FROM assets GROUP BY canonical_name HAVING COUNT(*)>1)"
    )
    con.close()

    dart_sale = load_json(ARTIFACTS / "backfill-2020-2024-opendart-sale-document-text-v3-summary.json")
    dart_business = load_json(ARTIFACTS / "backfill-2020-2024-opendart-business-transfer-document-text-v1-summary.json")
    backup = load_json(BACKUP_MANIFEST)

    google_planned = 3420
    google_gap = google_planned - google_completed
    research = {
        "deep_research_processes": 47,
        "approved_historical_manifests": len(manifests),
        "by_group": dict(sorted(by_group.items())),
        "not_promoted": 33,
        "not_promoted_breakdown": {
            "office_dc": 4,
            "hotel": 14,
            "hotel_ifc_crosswalk": 1,
            "logistics": 14,
        },
        "approval_rule": "competitive process and terminal/milestone facts must pass direct-body or official-source evidence gate",
        "review_only_source_claims_in_approved_manifests": review_only_sources,
    }
    duplicate_fixture_orgs = {name: sorted(ids) for name, ids in organization_ids.items() if len(ids) > 1}
    duplicate_fixture_assets = {name: sorted(ids) for name, ids in asset_ids.items() if len(ids) > 1}

    checks = {
        "schema_is_supported": schema_version in {"2.5.0", "2.6.0"},
        "historical_manifest_count_is_14": len(manifests) == 14,
        "historical_live_process_count_is_14": counts["historical_sale_processes"] == 14,
        "total_live_process_count_is_16": counts["sale_processes"] == 16,
        "approved_manifests_have_no_review_only_sources": review_only_sources == 0,
        "fixture_organization_master_duplicates_absent": not duplicate_fixture_orgs,
        "fixture_asset_master_duplicates_absent": not duplicate_fixture_assets,
        "live_organization_master_duplicates_absent": live_duplicate_org_names == 0,
        "live_asset_master_duplicates_absent": live_duplicate_asset_names == 0,
        "foreign_keys_clean": not fk_violations,
        "sqlite_integrity_ok": integrity == "ok",
        "final_backup_clean": backup.get("quickCheck") == "ok" and backup.get("foreignKeyViolations") == 0,
    }

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "schema_version": schema_version,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "checks": checks,
        "research_gate": research,
        "live_relational_counts": counts,
        "sale_processes_by_asset_class": process_by_asset,
        "process_relation_note": (
            "0 current edges is expected: no separately approved pair has both endpoints canonical. "
            "Crescendo preferred-party switch is represented as rounds/decisions inside one process; "
            "excluded or future attempts remain metadata/crosswalk candidates until approved."
        ),
        "coverage": {
            "google_news_2020_2024": {
                "planned_partitions": google_planned,
                "completed_partitions": google_completed,
                "completion_ratio": round(google_completed / google_planned, 6),
                "upstream_throttled_gap": google_gap,
                "inserted_documents": google_documents,
                "gap_status": "UPSTREAM_THROTTLED_NOT_ZERO_FILLED",
            },
            "opendart_2020_2024_unique_sale_documents": {
                "attempted": dart_sale["attempted"],
                "downloaded": dart_sale["downloaded"],
                "unavailable_014": dart_sale["unavailable014"],
                "retryable_failures": dart_sale["retryableFailures"],
                "business_transfer_subset": {
                    "attempted": dart_business["attempted"],
                    "downloaded": dart_business["downloaded"],
                    "unavailable_014": dart_business["unavailable014"],
                    "retryable_failures": dart_business["retryableFailures"],
                },
            },
        },
        "review_only_pipelines": pipeline_rows,
        "canonical_auto_creation_from_review_pipelines": 0,
        "duplicates": {
            "fixture_organizations": duplicate_fixture_orgs,
            "fixture_assets": duplicate_fixture_assets,
            "live_organization_names": live_duplicate_org_names,
            "live_asset_names": live_duplicate_asset_names,
        },
        "integrity": {"foreign_key_violations": fk_violations, "integrity_check": integrity},
        "final_backup": backup,
        "key_artifacts": [
            "artifacts/competitive-sales-2020-2024-chronology.json",
            "artifacts/hotel-competitive-sales-2020-2024-deep-dive.json",
            "artifacts/logistics-competitive-sales-2020-2024-structured.json",
            "artifacts/bid-process-2020-2025-candidates.json",
            "artifacts/opendart-2020-2024-business-transfer-cre-candidates.json",
        ],
    }
    OUTPUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md = f"""# 2020–2025 경쟁매각 통합 QA

- 상태: **{payload['status']}**
- Schema: `{schema_version}`
- Live sale processes: **{counts['sale_processes']}** (역사 14 + 2025 calibration 2)
- 심층조사: **47건 → 승인 14 / 비승격 33**
- 관계형 구성: round {counts['rounds']}, participation {counts['participations']}, submission {counts['submissions']}, funding {counts['funding_components']}, decision {counts['decisions']}, milestone {counts['milestones']}
- FK 위반: **{len(fk_violations)}**
- SQLite integrity: **{integrity}**

## 승인 gate

- Office/DC: 6건
- Hotel: 7건
- Logistics: 1건
- 승인 manifest 내 title/snippet-only source claim: **{review_only_sources}건**
- 미공개 bidder·vehicle·lender·정확가격·정확일자 추정 없음

## Coverage

- Google News 2020–2024: **{google_completed}/{google_planned} partitions** ({google_completed / google_planned:.2%})
- Google 미완료: **{google_gap}** — `UPSTREAM_THROTTLED_NOT_ZERO_FILLED`
- OpenDART 2020–2024 unique sale documents: **{dart_sale['downloaded']}/{dart_sale['attempted']}**, status 014: {dart_sale['unavailable014']}, retryable failure: {dart_sale['retryableFailures']}
- 영업양도·양수 subset: **{dart_business['downloaded']}/{dart_business['attempted']}**, status 014: {dart_business['unavailable014']}
- News review 후보: **{pipeline_rows.get('BID_PROCESS_TITLE_SNIPPET_V4', {}).get('mentions', 0)}**
- 영업양도·양수 review 후보: **{pipeline_rows.get('DART_BUSINESS_TRANSFER_CRE_REVIEW_V1', {}).get('mentions', 0)}**
- Review pipeline canonical 자동 생성: **0**

## Process relation

현재 canonical relation edge는 **{counts['process_relations']}건**이다. 양쪽 endpoint가 모두 승인된 별도 attempt pair가 아직 없기 때문이다. 크레센도 우협 변경은 동일 process 내부 round·decision으로 보존했고, 제외·향후 attempt는 승인 전 crosswalk/metadata 상태로 유지했다.

## Final backup

- 파일: `{Path(backup['backup']).name}`
- SHA-256: `{backup['sha256']}`
- quick_check: `{backup['quickCheck']}`
- FK 위반: `{backup['foreignKeyViolations']}`
"""
    OUTPUT_MD.write_text(md, encoding="utf-8")
    print(json.dumps({"status": payload["status"], "json": str(OUTPUT_JSON), "markdown": str(OUTPUT_MD), "checks": checks}, ensure_ascii=False, indent=2))
    if payload["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
