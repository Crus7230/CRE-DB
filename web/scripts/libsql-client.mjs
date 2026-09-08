import { createClient } from "@libsql/client";
import fs from "node:fs";

const DEFAULT_AUTHORITY = String.raw`C:\10137_WorkSpace\env\.env.personal.txt`;

function unquote(value) {
  const trimmed = value.trim();
  if (trimmed.length >= 2) {
    const first = trimmed[0];
    const last = trimmed.at(-1);
    if ((first === "\"" && last === "\"") || (first === "'" && last === "'")) {
      return trimmed.slice(1, -1);
    }
  }
  return trimmed;
}

function parseAuthority(text) {
  const values = new Map();
  for (const rawLine of text.replace(/^\uFEFF/u, "").split(/\r?\n/u)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const rawName = line.slice(0, separator).trim();
    const name = rawName.startsWith("export ") ? rawName.slice(7).trim() : rawName;
    if (name !== "TURSO_DATABASE_URL" && name !== "TURSO_AUTH_TOKEN") continue;
    const value = unquote(line.slice(separator + 1));
    if (value) values.set(name, value);
  }
  return values;
}

function configuration() {
  let url;
  let authToken;
  if (process.env.TURSO_DATABASE_URL || process.env.TURSO_AUTH_TOKEN) {
    url = process.env.TURSO_DATABASE_URL?.trim();
    authToken = process.env.TURSO_AUTH_TOKEN?.trim();
  } else {
    const authority = process.env.TURSO_ENV_FILE ?? DEFAULT_AUTHORITY;
    const values = parseAuthority(fs.readFileSync(authority, "utf8"));
    url = values.get("TURSO_DATABASE_URL");
    authToken = values.get("TURSO_AUTH_TOKEN");
  }

  if (!url) throw new Error("TURSO_DATABASE_URL is not configured");
  if (!authToken && !url.startsWith("file:")) {
    throw new Error("TURSO_AUTH_TOKEN is not configured");
  }
  return authToken ? { url, authToken } : { url };
}

export function createTursoClient() {
  return createClient(configuration());
}

export function normalizeRows(rows) {
  return rows.map((row) => {
    const normalized = Object.fromEntries(Object.entries(row));
    if (typeof normalized.payload === "string") {
      try {
        normalized.payload = JSON.parse(normalized.payload);
      } catch {
        // A payload column that is not JSON is kept byte-for-byte.
      }
    }
    return normalized;
  });
}

export function createSqlExecutor(client) {
  return async (text, values) => {
    const result = await client.execute({ sql: text, args: [...values] });
    return { rows: normalizeRows(result.rows) };
  };
}
