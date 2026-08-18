const base = "http://127.0.0.1:3001";
async function get(path) { const r = await fetch(base + path); const x = await r.json(); if (!r.ok) throw new Error(`${path} ${r.status} ${JSON.stringify(x)}`); return x; }
const rss = await get("/api/search?kind=DOCUMENT&category=RSS_ITEM&page=1&pageSize=1&q=&from=&to=");
const dart = await get("/api/search?kind=DOCUMENT&category=DISCLOSURE&page=1&pageSize=1&q=&from=&to=");
const rssDetail = await get(`/api/documents/${encodeURIComponent(rss.results[0].id)}`);
const dartDetail = await get(`/api/documents/${encodeURIComponent(dart.results[0].id)}`);
if (!rssDetail.summary || !rssDetail.sourceUrl || rssDetail.eventSignals.length === 0 || rssDetail.keywords.length === 0) throw new Error("RSS detail projection is incomplete");
if (!dartDetail.storedText || !dartDetail.sourceUrl || dartDetail.eventSignals.length === 0 || dartDetail.keywords.length === 0) throw new Error("Disclosure detail projection is incomplete");
console.log(JSON.stringify({
  rss: { title: rssDetail.title, mode: rssDetail.contentMode, summaryChars: rssDetail.summary?.length ?? 0, keywords: rssDetail.keywords.length, events: rssDetail.eventSignals.length, sourceUrl: Boolean(rssDetail.sourceUrl) },
  disclosure: { title: dartDetail.title, mode: dartDetail.contentMode, summaryChars: dartDetail.summary?.length ?? 0, storedChars: dartDetail.storedText?.length ?? 0, keywords: dartDetail.keywords.length, events: dartDetail.eventSignals.length, sourceUrl: Boolean(dartDetail.sourceUrl) }
}, null, 2));
