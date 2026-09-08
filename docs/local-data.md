# Local data directory

Runtime SQLite archives and collection staging databases are generated locally and are intentionally excluded from Git.

- `market.db`: read-only local full archive; preserves complete history, inactive detail, evidence, and lineage
- `work/*.db`: collection and migration staging databases
- `*.db-wal`, `*.db-shm`: SQLite runtime journals
- `../backups/archive-snapshots/*.db`: immutable pre-retire recovery snapshots

Merge current Supabase active-serving rows into the full archive without deleting archive-only rows:

```bash
uv run --with 'psycopg[binary]' python scripts/merge_supabase_active_into_full_archive.py --activate
```

Do not use the legacy overwrite refresh after active-serving cutover. `refresh_sqlite_sub_from_supabase.py` is guarded and will refuse when a current archive snapshot is registered.
