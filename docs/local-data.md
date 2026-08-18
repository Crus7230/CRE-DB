# Local data directory

Runtime SQLite snapshots and collection staging databases are generated locally and are intentionally excluded from Git.

- `market.db`: read-only snapshot refreshed from Supabase PostgreSQL
- `work/*.db`: collection and migration staging databases
- `*.db-wal`, `*.db-shm`: SQLite runtime journals

Use `scripts/refresh_sqlite_sub_from_supabase.py` to rebuild the local snapshot from the authoritative Supabase `market_intelligence` schema.
