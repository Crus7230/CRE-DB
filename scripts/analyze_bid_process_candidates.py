from __future__ import annotations

from collections import Counter
import csv
import io
import json
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "data" / "market.db"


def main() -> None:
    con = sqlite3.connect(DB)
    rows = con.execute(
        """SELECT rt.review_task_id,rt.priority,rt.payload_json,em.title_raw,em.summary_raw
           FROM review_tasks rt
           JOIN event_mentions em ON em.event_mention_id=rt.target_id
           WHERE rt.review_type='SALE_PROCESS_EVIDENCE_REVIEW'
             AND rt.reason_code='TITLE_SNIPPET_CANDIDATE'
             AND rt.status_code IN ('PENDING','IN_PROGRESS')
           ORDER BY rt.priority,em.created_at"""
    ).fetchall()
    con.close()
    asset_counts: Counter[str] = Counter()
    region_counts: Counter[str] = Counter()
    stage_counts: Counter[str] = Counter()
    participation_counts: Counter[str] = Counter()
    advisor_counts: Counter[str] = Counter()
    funding_counts: Counter[str] = Counter()
    documents: list[dict] = []
    for task_id, priority, payload_json, title, snippet in rows:
        payload = json.loads(payload_json)
        c = payload["candidate"]
        asset_counts.update(c["asset_types"])
        region_counts.update(c["region_groups"])
        stage_counts.update(c["stage_signals"])
        participation_counts.update(c["participation_signals"])
        advisor_counts.update(c["advisor_signals"])
        funding_counts.update(c["funding_signals"])
        score = (
            3 * len(c["reported_ranks"]) + 2 * len(c["money_mentions"])
            + 2 * len(c["funding_signals"]) + len(c["organization_mentions"])
            + len(c["stage_signals"]) + len(c["advisor_signals"])
        )
        documents.append({
            "reviewTaskId": task_id,
            "priority": priority,
            "evidenceScore": score,
            "publishedAt": payload.get("publishedAt"),
            "sourceCode": payload.get("sourceCode"),
            "canonicalUrl": payload.get("canonicalUrl"),
            "title": title,
            "snippet": snippet,
            "assetTypes": c["asset_types"],
            "regionGroups": c["region_groups"],
            "stageSignals": c["stage_signals"],
            "participationSignals": c["participation_signals"],
            "advisorSignals": c["advisor_signals"],
            "fundingSignals": c["funding_signals"],
            "moneyMentions": c["money_mentions"],
            "reportedRanks": c["reported_ranks"],
            "organizationMentions": c["organization_mentions"],
            "status": "REVIEW_CANDIDATE_NOT_CANONICAL",
        })
    documents.sort(key=lambda x: (-x["evidenceScore"], x["publishedAt"] or "", x["title"] or ""))
    output = {
        "contract": "TITLE_SNIPPET_CANDIDATES_ONLY",
        "candidateDocumentCount": len(documents),
        "counts": {
            "assetType": dict(asset_counts), "regionGroup": dict(region_counts),
            "stage": dict(stage_counts), "participation": dict(participation_counts),
            "advisor": dict(advisor_counts), "funding": dict(funding_counts),
        },
        "documents": documents,
    }
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    (artifacts / "bid-process-2025-candidates.json").write_text(
        json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    buffer = io.StringIO()
    fields = ["reviewTaskId","priority","evidenceScore","publishedAt","sourceCode","canonicalUrl","title","assetTypes","regionGroups","stageSignals","participationSignals","advisorSignals","fundingSignals","moneyMentions","reportedRanks","organizationMentions","status"]
    writer = csv.DictWriter(buffer, fieldnames=fields)
    writer.writeheader()
    for row in documents:
        out = {key: row.get(key) for key in fields}
        for key in ("assetTypes","regionGroups","stageSignals","participationSignals","advisorSignals","fundingSignals","moneyMentions","reportedRanks","organizationMentions"):
            out[key] = json.dumps(out[key], ensure_ascii=False)
        writer.writerow(out)
    (artifacts / "bid-process-2025-candidates.csv").write_text("\ufeff" + buffer.getvalue(), encoding="utf-8")

    lines = [
        "# 2025년 자산매각 입찰 프로세스 후보 조사", "",
        "> 제목·snippet 규칙 추출 결과이며 canonical sale process 또는 확정 사실이 아니다.", "",
        f"- 후보 문서: {len(documents):,}건", "",
        "## 자산유형", "",
    ]
    lines += [f"- {k}: {v:,}건" for k,v in asset_counts.most_common()]
    lines += ["", "## 권역", ""] + [f"- {k}: {v:,}건" for k,v in region_counts.most_common()]
    lines += ["", "## 입찰단계 신호", ""] + [f"- {k}: {v:,}건" for k,v in stage_counts.most_common()]
    lines += ["", "## 자금조달 신호", ""] + [f"- {k}: {v:,}건" for k,v in funding_counts.most_common()]
    lines += ["", "## 고정보 후보 상위 50건", ""]
    for i,row in enumerate(documents[:50],1):
        lines += [
            f"### {i}. {row['title']}",
            f"- 게시: {row['publishedAt']} · 점수: {row['evidenceScore']} · 우선순위: {row['priority']}",
            f"- 자산/권역: {', '.join(row['assetTypes']) or '미상'} / {', '.join(row['regionGroups']) or '미상'}",
            f"- 단계: {', '.join(row['stageSignals'] + row['participationSignals']) or '미상'}",
            f"- 자문/자금: {', '.join(row['advisorSignals'] + row['fundingSignals']) or '미상'}",
            f"- URL: {row['canonicalUrl']}", "",
        ]
    (artifacts / "bid-process-2025-candidate-report.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"candidateDocuments":len(documents),"counts":output["counts"],"topEvidenceScore":documents[0]["evidenceScore"] if documents else 0}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
