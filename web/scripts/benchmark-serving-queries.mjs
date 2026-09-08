import { getDailyArticles } from "../src/lib/server/daily-articles.ts";
import { searchMarket } from "../src/lib/server/market-search.ts";
import { createSqlExecutor, createTursoClient } from "./libsql-client.mjs";

function todayInSeoul() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date());
}

const client = createTursoClient();
const execute = createSqlExecutor(client);

async function measure(label, operation, summarize) {
  const started = performance.now();
  const result = await operation();
  const elapsedMs = Math.round(performance.now() - started);
  console.log(JSON.stringify({ label, elapsedMs, ...summarize(result) }));
}

const selectedDate = process.argv.find((value) => /^\d{4}-\d{2}-\d{2}$/.test(value)) || todayInSeoul();
const query = process.argv.find((value) => value.startsWith("--query="))?.slice("--query=".length) || "강남 오피스";

try {
  await measure(
    "daily-articles",
    () => getDailyArticles(execute, selectedDate),
    (result) => ({ selectedDate, resultCount: result.articles.length }),
  );
  await measure(
    "event-search",
    () => searchMarket(execute, {
      q: query,
      kind: "EVENT",
      category: "",
      classificationScheme: "",
      from: null,
      to: null,
      page: 1,
      pageSize: 20,
      includeTransactionsUnder1000Eok: false,
    }),
    (result) => ({ query, total: result.total, resultCount: result.results.length }),
  );
  await measure(
    "daily-articles-warm",
    () => getDailyArticles(execute, selectedDate),
    (result) => ({ selectedDate, resultCount: result.articles.length }),
  );
} finally {
  client.close();
}
