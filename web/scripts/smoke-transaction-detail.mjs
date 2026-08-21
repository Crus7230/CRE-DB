import { createAuthenticatedGet } from "./authenticated-get.mjs";

const base = process.env.BASE_URL ?? "http://127.0.0.1:3001";
const get = await createAuthenticatedGet(base);
const search = await get("/api/search?kind=DOCUMENT&category=API_RECORD&page=1&pageSize=1&q=&from=&to=");
const item = search.results[0];
if (!item?.metadata?.apiRecord || item.summary?.startsWith("{")) throw new Error("transaction search template projection missing");
const detail = await get(`/api/documents/${encodeURIComponent(item.id)}`);
if (!detail.transaction?.dealAmount || !detail.transaction?.address || !detail.transaction?.screeningBand) throw new Error("transaction detail projection missing");
console.log(JSON.stringify({ id: item.id, summary: item.summary, href: item.href, transaction: detail.transaction }, null, 2));
