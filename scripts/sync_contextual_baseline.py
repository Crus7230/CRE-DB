"""Sync contextual migration DDL/seed into the fresh-install SQLite baseline."""
from __future__ import annotations

import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "db/v2/migrations/3.8.0_contextual_intelligence.sqlite.sql"
SCHEMA = ROOT / "db/v2/schema.sql"
SEED = ROOT / "db/v2/seed.sql"


def sync(*, check: bool = False) -> dict[str, object]:
    migration = MIGRATION.read_text(encoding="utf-8")
    schema = SCHEMA.read_text(encoding="utf-8")
    seed = SEED.read_text(encoding="utf-8")
    ddl_match = re.search(
        r"(CREATE TABLE contextual_processing_campaigns .*?CREATE INDEX ix_contextual_search_grade .*?;)",
        migration,
        re.S,
    )
    seed_match = re.search(
        r"(INSERT INTO contextual_rule_sets\(.*?\);\n\nINSERT INTO contextual_rules\(.*?\);)",
        migration,
        re.S,
    )
    if not ddl_match or not seed_match:
        raise RuntimeError("contextual migration blocks not found")
    ddl, governed_seed = ddl_match.group(1), seed_match.group(1)
    schema_has = "CREATE TABLE contextual_processing_campaigns" in schema
    seed_has = "rule-set-contextual-v1" in seed
    meta_has = "'contextual_intelligence_schema_version', '1.0.0'" in schema
    if check:
        if not (schema_has and seed_has and meta_has):
            raise RuntimeError("fresh-install contextual baseline is stale")
        return {"status": "current", "schema": schema_has, "seed": seed_has, "meta": meta_has}
    if schema_has or seed_has or meta_has:
        raise RuntimeError("partial contextual baseline detected; refusing ambiguous rewrite")

    schema_marker = "INSERT INTO schema_meta(schema_key, schema_value) VALUES\n    ('schema_name'"
    if schema.count(schema_marker) != 1:
        raise RuntimeError("schema metadata marker is not unique")
    schema = schema.replace(
        schema_marker,
        "-- Contextual intelligence feature schema 1.0.0 (baseline).\n" + ddl + "\n\n" + schema_marker,
        1,
    )
    schema = schema.replace(
        "    ('created_for', 'serverless-local-accumulation');",
        "    ('created_for', 'serverless-local-accumulation'),\n"
        "    ('contextual_intelligence_schema_version', '1.0.0');",
        1,
    )

    seed_marker = "INSERT INTO schema_meta(schema_key, schema_value) VALUES\n ('seed_version'"
    if seed.count(seed_marker) != 1:
        raise RuntimeError("seed metadata marker is not unique")
    seed = seed.replace(
        seed_marker,
        "-- Contextual intelligence governed rule seed 1.0.0.\n"
        + governed_seed
        + "\n\n"
        + seed_marker,
        1,
    )
    SCHEMA.write_text(schema, encoding="utf-8")
    SEED.write_text(seed, encoding="utf-8")
    return {"status": "updated", "ddlLines": len(ddl.splitlines()), "seedLines": len(governed_seed.splitlines())}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    print(sync(check=args.check))


if __name__ == "__main__":
    main()
