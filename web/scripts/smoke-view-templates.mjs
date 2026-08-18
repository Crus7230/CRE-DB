const base = "http://127.0.0.1:3001";
async function get(path) { const r = await fetch(base + path); const x = await r.json(); if (!r.ok) throw new Error(`${path} ${r.status} ${JSON.stringify(x)}`); return x; }
const high = await get("/api/search?kind=DOCUMENT&category=API_RECORD&page=1&pageSize=50&includeTransactionsUnder1000Eok=false");
const all = await get("/api/search?kind=DOCUMENT&category=API_RECORD&page=1&pageSize=50&includeTransactionsUnder1000Eok=true");
const amounts = high.results.map((item) => Number(String(item.metadata.apiRecord.dealAmount).replaceAll(",", "")));
if (amounts.some((value) => value < 10_000_000)) throw new Error(`default result contains sub-1000억원 transaction: ${Math.min(...amounts)}`);
if (!(all.total > high.total)) throw new Error(`include-small toggle did not expand results: ${high.total} -> ${all.total}`);
const events = await get("/api/search?kind=EVENT&page=1&pageSize=1&category=&includeTransactionsUnder1000Eok=false");
const assets = await get("/api/search?kind=ASSET&page=1&pageSize=1&category=&includeTransactionsUnder1000Eok=false");
const event = await get(`/api/entities/event/${events.results[0].id}`);
const asset = await get(`/api/entities/asset/${assets.results[0].id}`);
if (event.kind !== "EVENT" || !Array.isArray(event.documents) || !Array.isArray(event.organizations)) throw new Error("event template incomplete");
if (asset.kind !== "ASSET" || !Array.isArray(asset.events) || !Array.isArray(asset.documents)) throw new Error("asset template incomplete");
console.log(JSON.stringify({ transactions: { default1000EokPlus: high.total, includeUnder1000Eok: all.total, firstPageMinimumEok: Math.min(...amounts) / 10_000 }, event: { title: event.title, assets: event.assets.length, organizations: event.organizations.length, documents: event.documents.length }, asset: { title: asset.title, events: asset.events.length, organizations: asset.organizations.length, documents: asset.documents.length } }, null, 2));
