import { searchMarket, type SqlExecutor } from "../src/lib/server/market-search";
import { createSqlExecutor, createTursoClient } from "./libsql-client.mjs";

const client = createTursoClient();
const execute = createSqlExecutor(client) as SqlExecutor;
try {
  const response = await searchMarket(execute, {
    q: "",
    kind: "ALL",
    category: "",
    classificationScheme: "",
    from: null,
    to: null,
    page: 1,
    pageSize: 5,
    includeTransactionsUnder1000Eok: false,
  });
  console.log(JSON.stringify({
    total: response.total,
    facets: response.facets,
    first: response.results[0]?.kind,
    archivedOnFirstPage: response.results.filter((result) => result.status === "ARCHIVED_LOCAL").length,
  }));
} finally {
  client.close();
}
