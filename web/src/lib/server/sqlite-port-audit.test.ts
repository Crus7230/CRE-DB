import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const forbidden = [
  /\b(?:market_intelligence|app_security)\./iu,
  /::[a-z_]/iu,
  /\bjsonb(?:_|\s*\()/iu,
  /\bdistinct\s+on\s*\(/iu,
  /\blateral\b/iu,
  /\bclock_timestamp\s*\(/iu,
  /\bilike\b/iu,
  /\bgenerate_series\s*\(/iu,
  /\barray_agg\s*\(/iu,
  /\bregexp_replace\s*\(/iu,
  /\bdate_trunc\s*\(/iu,
  /\bto_char\s*\(/iu,
  /\bat\s+time\s+zone\b/iu,
  /\binterval\s+'/iu,
  /\bany\s*\(/iu,
  /\bunnest\s*\(/iu,
  /\bstring_agg\s*\(/iu,
  /\bmake_date\s*\(/iu,
  /\bto_date\s*\(/iu,
  /\bextract\s*\(/iu,
];

describe("SQLite/Turso SQL source audit", () => {
  it("contains no PostgreSQL-only runtime SQL constructs", () => {
    const directory = path.resolve(process.cwd(), "src/lib/server");
    const failures: string[] = [];
    for (const name of readdirSync(directory)) {
      if (!name.endsWith(".ts") || name.endsWith(".test.ts")) continue;
      const text = readFileSync(path.join(directory, name), "utf8");
      for (const pattern of forbidden) {
        const match = pattern.exec(text);
        if (match) failures.push(`${name}: ${match[0]}`);
      }
    }
    expect(failures).toEqual([]);
  });

  it("uses libSQL without retaining the postgres package", () => {
    const packageJson = JSON.parse(readFileSync(path.resolve(process.cwd(), "package.json"), "utf8")) as {
      dependencies?: Record<string, string>;
    };
    expect(packageJson.dependencies?.["@libsql/client"]).toBeTruthy();
    expect(packageJson.dependencies?.postgres).toBeUndefined();
  });
});
