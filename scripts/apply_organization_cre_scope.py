#!/usr/bin/env python
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from collector.organization_cre_scope import CLASSIFIER_VERSION, classify_organization_cre_scope

ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.0.0_organization_cre_scope.sql"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env() -> dict[str, str]:
    out = {}
    for raw in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if IDENTIFIER.fullmatch(key.strip()):
                out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def stable_hash(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def classify_all(cur, schema: str) -> list[dict]:
    rows = cur.execute(f"""SELECT o.organization_id,o.canonical_name,o.status_code,o.metadata_json,
        EXISTS(SELECT 1 FROM {schema}.event_participants ep WHERE ep.organization_id=o.organization_id),
        EXISTS(SELECT 1 FROM {schema}.mention_resolutions mr WHERE mr.target_kind='ORGANIZATION' AND mr.organization_id=o.organization_id AND mr.resolution_status='RESOLVED')
        FROM {schema}.organizations o ORDER BY o.organization_id""").fetchall()
    decisions = []
    for oid, name, status, metadata, has_event, has_resolution in rows:
        values = metadata if isinstance(metadata, dict) else json.loads(metadata or "{}")
        result = classify_organization_cre_scope(
            status_code=status, metadata=values, has_event_participation=has_event,
            has_resolved_mention=has_resolution, canonical_name=name,
        )
        decisions.append({
            "organizationId": oid, "canonicalName": name, "statusCode": result.status_code,
            "reasonCodes": list(result.reason_codes),
            "evidence": {
                "hasEventParticipation": has_event,
                "hasResolvedMention": has_resolution,
                "krxSnapshotDate": values.get("krx_snapshot_date"),
                "kindIndustry": values.get("kind_industry"),
            },
        })
    return decisions


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--apply", action="store_true")
    p.add_argument("--rollback-after-apply", action="store_true")
    p.add_argument("--expected-total", type=int, required=True)
    p.add_argument("--expected-confirmed", type=int)
    p.add_argument("--expected-context-only", type=int)
    p.add_argument("--expected-review", type=int)
    p.add_argument("--expected-manifest-sha256")
    p.add_argument("--output", type=Path, default=Path(r"C:\Users\10137\AppData\Local\hermes\cache\cre-db-organization-scope-result.json"))
    args = p.parse_args()
    if args.rollback_after_apply and not args.apply:
        raise SystemExit("--rollback-after-apply requires --apply")
    if args.apply and not args.expected_manifest_sha256:
        raise SystemExit("apply requires --expected-manifest-sha256")

    import psycopg
    env = load_env(); schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    assessed_at = datetime.now(timezone.utc).isoformat()
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as conn:
        with conn.cursor() as cur:
            if args.apply:
                cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("organization-cre-scope-rule-v1",))
                cur.execute(f"LOCK TABLE {schema}.schema_meta,{schema}.organizations,{schema}.event_participants,{schema}.mention_resolutions IN SHARE MODE")
            else:
                cur.execute("BEGIN READ ONLY")
            version = cur.execute(f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
            if version not in {"2.9.0", "3.0.0"}:
                raise RuntimeError(f"expected schema 2.9.0 or 3.0.0, found {version}")
            decisions = classify_all(cur, schema)
            counts = Counter(d["statusCode"] for d in decisions)
            expected = {
                "CRE_CONFIRMED": args.expected_confirmed,
                "CRE_CONTEXT_ONLY": args.expected_context_only,
                "CRE_REVIEW": args.expected_review,
            }
            if len(decisions) != args.expected_total:
                raise RuntimeError(f"total mismatch: {len(decisions)}")
            for key, value in expected.items():
                if value is not None and counts[key] != value:
                    raise RuntimeError(f"{key} mismatch: {counts[key]}")
            manifest = {"classifierVersion": CLASSIFIER_VERSION, "decisions": decisions}
            manifest_hash = stable_hash(manifest)
            if args.expected_manifest_sha256 and manifest_hash != args.expected_manifest_sha256:
                raise RuntimeError("manifest mismatch")
            if args.apply:
                if version == "2.9.0":
                    sql = MIGRATION.read_text(encoding="utf-8")
                    if schema != "market_intelligence":
                        sql = sql.replace("market_intelligence", schema)
                    cur.execute(sql, prepare=False)
                rows = []
                for d in decisions:
                    aid = hashlib.sha256(f"organization-scope:{d['organizationId']}:CRE:{CLASSIFIER_VERSION}".encode()).hexdigest()[:32]
                    rows.append((aid,d["organizationId"],"CRE",CLASSIFIER_VERSION,d["statusCode"],
                        json.dumps(d["reasonCodes"],ensure_ascii=False),json.dumps(d["evidence"],ensure_ascii=False,default=str),assessed_at))
                cur.executemany(f"""INSERT INTO {schema}.organization_scope_assessments(
                    organization_scope_assessment_id,organization_id,scope_code,classifier_version,
                    status_code,reason_codes_json,evidence_json,assessed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(organization_id,scope_code,classifier_version) DO UPDATE SET
                    status_code=excluded.status_code,reason_codes_json=excluded.reason_codes_json,
                    evidence_json=excluded.evidence_json,assessed_at=excluded.assessed_at""", rows)
                persisted = dict(cur.execute(f"""SELECT status_code,count(*) FROM {schema}.organization_scope_assessments
                    WHERE scope_code='CRE' AND classifier_version=%s GROUP BY status_code""", (CLASSIFIER_VERSION,)).fetchall())
                if persisted != dict(counts):
                    raise RuntimeError(f"persisted assessment mismatch: {persisted}")
                schema_after = cur.execute(f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'").fetchone()[0]
                if schema_after != "3.0.0":
                    raise RuntimeError(f"schema migration mismatch: {schema_after}")
                if args.rollback_after_apply:
                    conn.rollback()
                else:
                    conn.commit()
            else:
                persisted = {}
                schema_after = version
                conn.rollback()

    report = {
        "applied": bool(args.apply and not args.rollback_after_apply),
        "rollbackRehearsal": bool(args.rollback_after_apply),
        "classifierVersion": CLASSIFIER_VERSION, "assessed": len(decisions),
        "statusCounts": dict(counts), "manifestSha256": manifest_hash,
        "schemaInTransaction": schema_after, "persistedCounts": persisted,
        "completedAt": datetime.now(timezone.utc).isoformat(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False))


if __name__ == "__main__":
    main()
