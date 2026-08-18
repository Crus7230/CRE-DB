import "server-only";

import fs from "node:fs";
import postgres from "postgres";
import type { SqlExecutor } from "@/lib/server/market-search";

const DEFAULT_AUTHORITY = String.raw`C:\10137_WorkSpace\env\.env.supabase.local`;

function readConnectionUrl(): string {
  if (process.env.SUPABASE_DB_URL) return process.env.SUPABASE_DB_URL;
  const authority = process.env.SUPABASE_ENV_FILE ?? DEFAULT_AUTHORITY;
  const text = fs.readFileSync(/* turbopackIgnore: true */ authority, "utf8").replace(/^\uFEFF/, "");
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const match = line.match(/^(?:export\s+)?SUPABASE_DB_URL\s*=\s*(.*)$/);
    if (!match) continue;
    const value = match[1].trim().replace(/^(['"])(.*)\1$/, "$2");
    if (value) return value;
  }
  throw new Error("SUPABASE_DB_URL is not configured");
}

type GlobalWithSql = typeof globalThis & { __marketSql?: ReturnType<typeof postgres> };
const globalWithSql = globalThis as GlobalWithSql;

function client() {
  if (!globalWithSql.__marketSql) {
    globalWithSql.__marketSql = postgres(readConnectionUrl(), {
      max: 5,
      idle_timeout: 20,
      connect_timeout: 10,
      ssl: "require",
      transform: { undefined: null },
    });
  }
  return globalWithSql.__marketSql;
}

export const executeMarketSql: SqlExecutor = async (text, values) => {
  const rows = await client().begin("read only", async (transaction) => {
    await transaction.unsafe("SET LOCAL statement_timeout = 15000");
    return transaction.unsafe(text, [...values]);
  });
  return { rows: rows as unknown as Array<{ payload: unknown }> };
};
