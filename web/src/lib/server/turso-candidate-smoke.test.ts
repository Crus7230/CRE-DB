import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { describe, expect, it } from "vitest";
import type { ContextualSearchRequest } from "@/lib/contextual-search-contract";
import type { SearchRequest } from "@/lib/search-contract";
import { getCategoryIndex } from "@/lib/server/category-index";
import { getCompanies, getCompanyDetail } from "@/lib/server/company-intelligence";
import { searchContextualIntelligence } from "@/lib/server/contextual-search";
import { getDailyArticles } from "@/lib/server/daily-articles";
import { getDocumentDetail } from "@/lib/server/document-intelligence";
import { getInstitutionalCapital, getSaleProcesses } from "@/lib/server/domain-workspaces";
import { getEntityDetail } from "@/lib/server/entity-intelligence";
import { getInsightSignals } from "@/lib/server/insight-signals";
import { getKeywordAnalytics } from "@/lib/server/keyword-analytics";
import { getMacroTimeseries } from "@/lib/server/macro-timeseries";
import { searchMarket, type SqlExecutor, type SqlValue } from "@/lib/server/market-search";
import { getModelInterpretations } from "@/lib/server/model-interpretations";
import { getOperationsOverview } from "@/lib/server/operations-insights";
import { getOperationsTimeline } from "@/lib/server/operations-timeline";
import { getQuantitativeMarketPulse } from "@/lib/server/quantitative-market-pulse";

const candidatePath = process.env.CRE_TURSO_CANDIDATE_DB;
const canSmoke = Boolean(candidatePath && existsSync(candidatePath));

const python = String.raw`
import json, sqlite3, sys
path = sys.argv[1]
request = json.load(sys.stdin)
uri = "file:" + path.replace(chr(92), "/") + "?mode=ro&immutable=1"
connection = sqlite3.connect(uri, uri=True)
connection.execute("PRAGMA query_only=ON")
try:
    cursor = connection.execute(request["sql"], request["args"])
    names = [column[0] for column in cursor.description or []]
    rows = [dict(zip(names, row)) for row in cursor.fetchall()]
    print(json.dumps({"rows": rows}, ensure_ascii=False))
finally:
    connection.close()
`;

function queryCandidate(text: string, values: readonly SqlValue[] = []): Array<Record<string, unknown>> {
  if (!candidatePath) throw new Error("Missing CRE_TURSO_CANDIDATE_DB");
  const result = spawnSync("python", ["-c", python, candidatePath], {
    encoding: "utf8",
    input: JSON.stringify({ sql: text, args: values }),
    maxBuffer: 16 * 1024 * 1024,
    timeout: 120_000,
  });
  if (result.status !== 0) throw new Error(result.stderr || `Python exited ${result.status}`);
  return (JSON.parse(result.stdout) as { rows: Array<Record<string, unknown>> }).rows;
}

const execute: SqlExecutor = async (text, values) => ({
  rows: queryCandidate(text, values).map((row) => ({
    ...row,
    payload: typeof row.payload === "string" ? JSON.parse(row.payload) : row.payload,
  })) as Array<{ payload: unknown }>,
});

const contextualRequest: ContextualSearchRequest = {
  q: "", mode: "APPROVED", domain: "", eventType: "", stage: "", processType: "",
  role: "", participantEntityId: "", assetId: "", region: "", industry: "", impact: "",
  sourceGrade: "", from: "", to: "", page: 1, pageSize: 5,
};

const searchRequest: SearchRequest = {
  q: "", kind: "ALL", category: "", classificationScheme: "", from: null, to: null,
  page: 1, pageSize: 5, includeTransactionsUnder1000Eok: false,
};

describe.skipIf(!canSmoke)("read-only candidate SQLite smoke", () => {
  it("executes the ported search and intelligence SQL without mutating the candidate", async () => {
    const [{ document_id: documentId }] = queryCandidate("SELECT document_id FROM source_documents ORDER BY document_id LIMIT 1");
    const [{ event_id: eventId }] = queryCandidate("SELECT event_id FROM events ORDER BY event_id LIMIT 1");
    const [{ asset_id: assetId }] = queryCandidate("SELECT asset_id FROM assets ORDER BY asset_id LIMIT 1");
    const [{ organization_id: organizationId }] = queryCandidate(
      "SELECT organization_id FROM v_company_universe_current ORDER BY organization_id LIMIT 1",
    );
    const [{ selected_date: selectedDate }] = queryCandidate(
      "SELECT max(date(published_at,'+9 hours')) AS selected_date FROM document_versions WHERE published_at IS NOT NULL",
    );

    const contextual = await searchContextualIntelligence(execute, contextualRequest);
    const search = await searchMarket(execute, searchRequest);
    const articles = await getDailyArticles(execute, String(selectedDate));
    const document = await getDocumentDetail(execute, String(documentId));
    const event = await getEntityDetail(execute, "EVENT", String(eventId));
    const asset = await getEntityDetail(execute, "ASSET", String(assetId));
    const signals = await getInsightSignals(execute, 5);
    const keywords = await getKeywordAnalytics(execute, 5);
    const macro = await getMacroTimeseries(execute);
    const interpretations = await getModelInterpretations(execute, 5);
    const categoryIndex = await getCategoryIndex(execute);
    const operations = await getOperationsOverview(execute);
    const timeline = await getOperationsTimeline(execute, 90);
    const pulse = await getQuantitativeMarketPulse(execute);
    const companies = await getCompanies(execute, { view: "OVERALL", industry: "", q: "", limit: 3 });
    const company = await getCompanyDetail(execute, String(organizationId));
    const capital = await getInstitutionalCapital(execute);
    const saleProcesses = await getSaleProcesses(execute);

    expect(contextual.results).toBeInstanceOf(Array);
    expect(search.results).toBeInstanceOf(Array);
    expect(articles.articles).toBeInstanceOf(Array);
    expect(document?.id).toBe(String(documentId));
    expect(event?.kind).toBe("EVENT");
    expect(asset?.kind).toBe("ASSET");
    expect(signals.signals).toBeInstanceOf(Array);
    expect(keywords.keywords.every((item) => typeof item.isCollectionBias === "boolean")).toBe(true);
    expect(macro.series).toHaveLength(13);
    expect(macro.series.flatMap((series) => series.points).every((point) => typeof point.partial === "boolean")).toBe(true);
    expect(interpretations.interpretations).toBeInstanceOf(Array);
    expect(categoryIndex.groups).toBeInstanceOf(Array);
    expect(operations.sources).toBeInstanceOf(Array);
    expect(timeline.series).toHaveLength(90);
    expect(pulse.trend).toBeInstanceOf(Array);
    expect(companies.items.length).toBeLessThanOrEqual(3);
    expect(company.organization.organizationId).toBe(String(organizationId));
    expect(capital.items).toBeInstanceOf(Array);
    expect(saleProcesses.items).toBeInstanceOf(Array);
  }, 180_000);
});
