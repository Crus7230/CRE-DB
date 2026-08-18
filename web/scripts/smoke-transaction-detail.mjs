const base = "http://127.0.0.1:3001";
async function get(path) { const response = await fetch(base + path); const payload = await response.json(); if (!response.ok) throw new Error(`${response.status} ${JSON.stringify(payload)}`); return payload; }
const search = await get("/api/search?kind=DOCUMENT&category=API_RECORD&page=1&pageSize=1&q=&from=&to=");
const item = search.results[0];
if (!item?.metadata?.apiRecord || item.summary?.startsWith("{")) throw new Error("transaction search template projection missing");
const detail = await get(`/api/documents/${encodeURIComponent(item.id)}`);
if (!detail.transaction?.dealAmount || !detail.transaction?.address || !detail.transaction?.screeningBand) throw new Error("transaction detail projection missing");
console.log(JSON.stringify({ id: item.id, summary: item.summary, href: item.href, transaction: detail.transaction }, null, 2));
