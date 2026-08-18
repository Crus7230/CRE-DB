#!/usr/bin/env python
"""Secret-safe Supabase PostgreSQL connectivity probe."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re

import psycopg

ENV_PATH = Path(r"C:\10137_WorkSpace\env\.env.supabase.local")


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        match = re.match(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$", text)
        if match:
            values[match.group(1)] = match.group(2).strip().strip("\"'")
    return values


def main() -> None:
    env = load_env(ENV_PATH)
    url = env.get("SUPABASE_DB_URL")
    if not url:
        raise SystemExit("SUPABASE_DB_URL is missing")
    schema = env.get("SUPABASE_DB_SCHEMA", "market_intelligence")
    with psycopg.connect(url, connect_timeout=20) as conn:
        database, username, version, can_create = conn.execute(
            "select current_database(), current_user, current_setting('server_version'), "
            "has_database_privilege(current_user,current_database(),'CREATE')"
        ).fetchone()
        schema_exists = bool(
            conn.execute(
                "select 1 from information_schema.schemata where schema_name=%s", (schema,)
            ).fetchone()
        )
    print(json.dumps({
        "connected": True,
        "database_present": bool(database),
        "user_present": bool(username),
        "server_version_major": version.split(".")[0],
        "database_create_privilege": can_create,
        "target_schema": schema,
        "schema_exists": schema_exists,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
