const base = process.env.BASE_URL ?? "http://127.0.0.1:3001";
const smokeEmail = process.env.DASHBOARD_SMOKE_EMAIL?.trim().toLowerCase();
if (!smokeEmail) throw new Error("DASHBOARD_SMOKE_EMAIL is required and must already be approved");

const login = await fetch(`${base}/api/auth/login`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ email: smokeEmail }),
});
if (!login.ok) throw new Error(`auth login failed: ${login.status}`);
const sessionCookie = login.headers.get("set-cookie")?.split(";", 1)[0] ?? "";
if (!sessionCookie) throw new Error("auth login did not return a session cookie");

async function get(path) {
  const response = await fetch(`${base}${path}`, {
    headers: { Cookie: sessionCookie },
  });
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
const keywords=await get("/api/operations/keywords");
const insights=await get("/api/operations/insights");
const modelInterpretations=await get("/api/operations/model-interpretations");

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
  analytics:{keywords:keywords.items?.length??0,insights:insights.items?.length??0,modelInterpretations:modelInterpretations.items?.length??0},
};
if (report.indexGroups < 3 || report.julyDocuments < 1 || capital.items.length < 1 || sales.items.length < 1) throw new Error(`coverage assertion failed: ${JSON.stringify(report)}`);
console.log(JSON.stringify(report, null, 2));
