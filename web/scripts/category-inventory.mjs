import { createTursoClient, normalizeRows } from "./libsql-client.mjs";

const queries = [
  `
    SELECT
      ec.code,
      ec.name_ko,
      count(DISTINCT em.event_mention_id) AS mention_count,
      count(DISTINCT e.event_id) AS event_count
    FROM event_categories AS ec
    LEFT JOIN event_mentions AS em ON em.event_category_id = ec.event_category_id
    LEFT JOIN events AS e ON e.primary_category_id = ec.event_category_id
    GROUP BY ec.code, ec.name_ko
    ORDER BY ec.code
  `,
  `
    SELECT ac.code, ac.name_ko, count(a.asset_id) AS item_count
    FROM asset_classes AS ac
    LEFT JOIN assets AS a ON a.asset_class_id = ac.asset_class_id
    GROUP BY ac.code, ac.name_ko
    ORDER BY ac.code
  `,
  `
    SELECT coalesce(document_type, '미분류') AS value, count(*) AS item_count
    FROM source_documents
    GROUP BY document_type
    ORDER BY item_count DESC
  `,
  `
    SELECT coalesce(organization_type, '미분류') AS value, count(*) AS item_count
    FROM organizations
    GROUP BY organization_type
    ORDER BY item_count DESC
  `,
  `
    SELECT coalesce(mandate_status, '미분류') AS value, count(*) AS item_count
    FROM lp_mandates
    GROUP BY mandate_status
    ORDER BY item_count DESC
  `,
  `
    SELECT coalesce(process_status, '미분류') AS value, count(*) AS item_count
    FROM sale_processes
    GROUP BY process_status
    ORDER BY item_count DESC
  `,
];

const client = createTursoClient();
try {
  const [
    eventCategories,
    assetClasses,
    documentTypes,
    organizationTypes,
    lpStatuses,
    saleStatuses,
  ] = await client.batch(queries, "read");

  console.log(JSON.stringify({
    eventCategories: normalizeRows(eventCategories.rows),
    assetClasses: normalizeRows(assetClasses.rows),
    documentTypes: normalizeRows(documentTypes.rows),
    organizationTypes: normalizeRows(organizationTypes.rows),
    lpStatuses: normalizeRows(lpStatuses.rows),
    saleStatuses: normalizeRows(saleStatuses.rows),
  }, null, 2));
} finally {
  client.close();
}
