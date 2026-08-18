import fs from "node:fs";
import postgres from "postgres";

const envPath = process.env.SUPABASE_ENV_FILE ?? String.raw`C:\10137_WorkSpace\env\.env.supabase.local`;
const text = fs.readFileSync(envPath, "utf8");
const line = text.split(/\r?\n/).find((row) => /^(?:export\s+)?SUPABASE_DB_URL\s*=/.test(row.trim()));
if (!line) throw new Error("SUPABASE_DB_URL missing");
const url = line.slice(line.indexOf("=") + 1).trim().replace(/^(['"])(.*)\1$/, "$2");
const sql = postgres(url, { ssl: "require", max: 1 });
const result = await sql.begin("read only", async (tx) => {
  await tx`set local statement_timeout = '15s'`;
  const [eventCategories, assetClasses, documentTypes, organizationTypes, lpStatuses, saleStatuses] = await Promise.all([
    tx`select ec.code, ec.name_ko, count(distinct em.event_mention_id)::int mention_count, count(distinct e.event_id)::int event_count from market_intelligence.event_categories ec left join market_intelligence.event_mentions em on em.event_category_id=ec.event_category_id left join market_intelligence.events e on e.primary_category_id=ec.event_category_id group by ec.code,ec.name_ko order by ec.code`,
    tx`select ac.code, ac.name_ko, count(a.asset_id)::int item_count from market_intelligence.asset_classes ac left join market_intelligence.assets a on a.asset_class_id=ac.asset_class_id group by ac.code,ac.name_ko order by ac.code`,
    tx`select coalesce(document_type,'미분류') value, count(*)::int item_count from market_intelligence.source_documents group by document_type order by item_count desc`,
    tx`select coalesce(organization_type,'미분류') value, count(*)::int item_count from market_intelligence.organizations group by organization_type order by item_count desc`,
    tx`select coalesce(mandate_status,'미분류') value, count(*)::int item_count from market_intelligence.lp_mandates group by mandate_status order by item_count desc`,
    tx`select coalesce(process_status,'미분류') value, count(*)::int item_count from market_intelligence.sale_processes group by process_status order by item_count desc`,
  ]);
  return { eventCategories, assetClasses, documentTypes, organizationTypes, lpStatuses, saleStatuses };
});
await sql.end();
console.log(JSON.stringify(result, null, 2));
