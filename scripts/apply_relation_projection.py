#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
ENV = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")
MIGRATION = ROOT / "db" / "v2" / "migrations" / "3.1.0_document_entity_relations.sql"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_env() -> dict[str, str]:
    values: dict[str, str] = {}
    for raw in ENV.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if IDENTIFIER.fullmatch(key.strip()):
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback-after-apply", action="store_true")
    args = parser.parse_args()
    if args.rollback_after_apply and not args.apply:
        raise SystemExit("--rollback-after-apply requires --apply")

    import psycopg
    env = load_env()
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    with psycopg.connect(env["SUPABASE_DB_URL"], connect_timeout=20) as conn:
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("document-entity-relations-v1",))
            before = cur.execute(
                f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'"
            ).fetchone()[0]
            if args.apply:
                if before != "3.0.0":
                    raise RuntimeError(f"expected schema 3.0.0, found {before}")
                sql = MIGRATION.read_text(encoding="utf-8")
                if schema != "market_intelligence":
                    sql = sql.replace("market_intelligence", schema)
                cur.execute(sql, prepare=False)
            elif before != "3.1.0":
                raise RuntimeError(f"dry verification requires schema 3.1.0, found {before}")

            after = cur.execute(
                f"SELECT schema_value FROM {schema}.schema_meta WHERE schema_key='schema_version'"
            ).fetchone()[0]
            expected = "3.1.0"
            if after != expected:
                raise RuntimeError(f"schema version mismatch: {after}")
            counts = dict(cur.execute(
                f"SELECT relation_basis,count(*) FROM {schema}.v_document_entity_relations GROUP BY 1 ORDER BY 1"
            ).fetchall())
            kinds = dict(cur.execute(
                f"SELECT entity_kind,count(*) FROM {schema}.v_document_entity_relations GROUP BY 1 ORDER BY 1"
            ).fetchall())
            candidate_leaks = cur.execute(f"""
                SELECT count(*) FROM {schema}.v_document_entity_relations r
                JOIN {schema}.mention_resolutions mr ON mr.mention_id=r.mention_id
                WHERE r.relation_basis='RESOLVED_MENTION'
                  AND (mr.resolution_status<>'RESOLVED' OR mr.selected<>1)
            """).fetchone()[0]
            if candidate_leaks:
                raise RuntimeError(f"candidate resolution leak: {candidate_leaks}")
            if args.rollback_after_apply:
                conn.rollback()
            elif args.apply:
                conn.commit()
            else:
                conn.rollback()
    print(json.dumps({
        "applied": bool(args.apply and not args.rollback_after_apply),
        "rollbackRehearsal": bool(args.rollback_after_apply),
        "schemaVersionInTransaction": after,
        "relationBasisCounts": counts,
        "entityKindCounts": kinds,
        "candidateLeaks": candidate_leaks,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
