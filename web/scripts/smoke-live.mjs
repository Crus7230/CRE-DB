const base = process.env.BASE_URL ?? "http://127.0.0.1:3001";

async function get(path) {
  const response = await fetch(`${base}${path}`);
  const body = await response.json();
  if (!response.ok) throw new Error(`${path}: ${response.status} ${JSON.stringify(body)}`);
  return body;
}

const index = await get("/api/index");
const documents = await get("/api/search?kind=DOCUMENT&category=&from=2026-07-01&to=2026-07-31&page=1&pageSize=5&q=");
const companies = await get("/api/companies?view=OVERALL&industry=&q=&limit=5");
if (companies.snapshotDate !== "2026-07-31" || companies.items.length !== 5) throw new Error("company universe snapshot mismatch");
const company = await get(`/api/companies/${encodeURIComponent(companies.items[0].organizationId)}`);
const tenantSignals = await get("/api/companies?view=TENANT_SIGNALS&industry=&q=&limit=5");
const capital = await get("/api/institutional-capital");
const sales = await get("/api/sale-processes");

const report = {
  database: companies.database,
  indexGroups: index.groups.length,
  julyDocuments: documents.total,
  julySampleLatest: documents.results[0]?.date ?? null,
  marketSnapshot: companies.snapshotDate,
  companyRows: companies.items.length,
  companyDetail: {
    name: company.organization.name,
    events: company.counts.events,
    assets: company.counts.assets,
    documents: company.counts.documents,
    occupancies: company.counts.occupancies,
  },
  tenantSignals: {
    rows: tenantSignals.items.length,
    verifiedOccupancies: tenantSignals.coverage.verifiedOccupancies,
    companiesWithDocumentSignals: tenantSignals.coverage.companiesWithLeaseDocumentSignals,
  },
  institutionalCapital: capital.coverage,
  saleProcesses: sales.coverage,
};
if (report.indexGroups < 3 || report.julyDocuments < 1 || capital.items.length < 1 || sales.items.length < 1) throw new Error(`coverage assertion failed: ${JSON.stringify(report)}`);
console.log(JSON.stringify(report, null, 2));
