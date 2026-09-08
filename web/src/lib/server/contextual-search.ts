import type { ContextualSearchRequest, ContextualSearchResponse } from "@/lib/contextual-search-contract";
import type { SqlExecutor, SqlValue } from "@/lib/server/market-search";

const CONTEXTUAL_SQL = String.raw`
WITH filtered AS (
  SELECT record.*
  FROM contextual_search_records record
  WHERE record_mode = $1
    AND (($1 = 'APPROVED' AND review_status = 'APPROVED')
      OR ($1 = 'CANDIDATE' AND review_status = 'CANDIDATE'))
    AND ($2 = '' OR lower(search_text) LIKE lower($2))
    AND ($3 = '' OR event_domain = $3)
    AND ($4 = '' OR event_type = $4)
    AND ($5 = '' OR stage_code = $5)
    AND ($6 = '' OR process_type = $6)
    AND (($7 = '' AND $8 = '') OR EXISTS (
      SELECT 1
      FROM contextual_frame_participants participant
      WHERE participant.frame_id=record.frame_id
        AND ($7 = '' OR participant.role_code=$7)
        AND ($8 = '' OR participant.entity_id=$8)
    ))
    AND ($9 = '' OR EXISTS (SELECT 1 FROM json_each(record.asset_ids_json) WHERE value=$9))
    AND ($10 = '' OR EXISTS (SELECT 1 FROM json_each(record.region_ids_json) WHERE value=$10))
    AND ($11 = '' OR EXISTS (SELECT 1 FROM json_each(record.industry_codes_json) WHERE value=$11))
    AND ($12 = '' OR EXISTS (SELECT 1 FROM json_each(record.impact_directions_json) WHERE value=$12))
    AND ($13 = '' OR source_grade = $13)
    AND ($14 = '' OR substr(event_date,1,10) >= $14)
    AND ($15 = '' OR substr(event_date,1,10) <= $15)
), paged AS (
  SELECT * FROM filtered
  ORDER BY event_date IS NULL, event_date DESC, confidence DESC, search_record_id
  LIMIT $17 OFFSET $16
)
SELECT json_object(
  'total', (SELECT count(*) FROM filtered),
  'facets', json_object(
    'domains', json(COALESCE((SELECT json_group_array(json(item)) FROM (
      SELECT json_object('key',event_domain,'count',count(*)) item
      FROM filtered WHERE event_domain IS NOT NULL GROUP BY event_domain ORDER BY event_domain
    ) d), '[]')),
    'stages', json(COALESCE((SELECT json_group_array(json(item)) FROM (
      SELECT json_object('key',stage_code,'count',count(*)) item
      FROM filtered WHERE stage_code IS NOT NULL GROUP BY stage_code ORDER BY stage_code
    ) s), '[]')),
    'sourceGrades', json(COALESCE((SELECT json_group_array(json(item)) FROM (
      SELECT json_object('key',source_grade,'count',count(*)) item
      FROM filtered WHERE source_grade IS NOT NULL GROUP BY source_grade ORDER BY source_grade
    ) g), '[]'))
  ),
  'results', json(COALESCE((SELECT json_group_array(json_object(
    'id',search_record_id,'mode',record_mode,'sourceRecordKind',source_record_kind,
    'sourceRecordId',source_record_id,'title',title,'summary',summary,
    'eventDomain',event_domain,'eventType',event_type,'stageCode',stage_code,
    'processType',process_type,'actionCode',action_code,'eventDate',event_date,
    'temporalBasis',temporal_basis,'participantRoles',json(participant_roles_json),
    'participantEntityIds',json(participant_entity_ids_json),'assetIds',json(asset_ids_json),
    'regionIds',json(region_ids_json),'industryCodes',json(industry_codes_json),
    'impactDirections',json(impact_directions_json),'sourceGrade',source_grade,
    'confidence',confidence,'reviewStatus',review_status,'evidenceText',evidence_text,
    'ruleVersion',rule_version,'modelVersion',model_version,'metadata',json(metadata_json)
  )) FROM (
    SELECT * FROM paged result
    ORDER BY result.event_date IS NULL,result.event_date DESC,result.confidence DESC,result.search_record_id
  ) result), '[]'))
) AS payload`;

const LEGACY_SQL = String.raw`
WITH inputs AS (
  SELECT $1 AS mode, $2 AS query_text, $3 AS event_domain,
    $4 AS event_type, $5 AS stage_code, $6 AS process_type,
    $7 AS participant_role, $8 AS participant_entity_id,
    $9 AS asset_id, $10 AS region_id, $11 AS industry_code,
    $12 AS impact_direction, $13 AS source_grade,
    $14 AS date_from, $15 AS date_to,
    $16 AS row_offset, $17 AS row_limit
), filtered AS (
  SELECT legacy.*
  FROM legacy_derived_records legacy
  CROSS JOIN inputs
  WHERE inputs.mode = 'LEGACY'
    AND (inputs.query_text = '' OR lower(source_table) LIKE lower(inputs.query_text) OR lower(target_id) LIKE lower(inputs.query_text) OR lower(legacy_reason) LIKE lower(inputs.query_text))
), paged AS (
  SELECT * FROM filtered
  ORDER BY captured_at DESC, legacy_record_id
  OFFSET (SELECT row_offset FROM inputs)
  LIMIT (SELECT row_limit FROM inputs)
)
SELECT json_object(
  'total', (SELECT count(*) FROM filtered),
  'facets', json_object(
    'targetKinds', json(COALESCE((SELECT json_group_array(json(item)) FROM (
      SELECT json_object('key',target_kind,'count',count(*)) item
      FROM filtered GROUP BY target_kind ORDER BY target_kind
    ) k), '[]')),
    'sourceTables', json(COALESCE((SELECT json_group_array(json(item)) FROM (
      SELECT json_object('key',source_table,'count',count(*)) item
      FROM filtered GROUP BY source_table ORDER BY source_table
    ) t), '[]'))
  ),
  'results', json(COALESCE((SELECT json_group_array(json_object(
    'id',legacy_record_id,'mode','LEGACY','sourceRecordKind',target_kind,
    'sourceRecordId',target_id,'title',source_table || ' · ' || target_id,
    'summary',legacy_reason,'eventDomain',NULL,'eventType',NULL,'stageCode',NULL,
    'processType',NULL,'actionCode',NULL,'eventDate',substr(captured_at,1,10),
    'temporalBasis','CAPTURED_AT','participantRoles',json('[]'),
    'participantEntityIds',json('[]'),'assetIds',json('[]'),'regionIds',json('[]'),
    'industryCodes',json('[]'),'impactDirections',json('[]'),'sourceGrade',NULL,
    'confidence',NULL,'reviewStatus','SUPERSEDED','evidenceText',NULL,
    'ruleVersion',NULL,'modelVersion',NULL,'metadata',json(metadata_json)
  )) FROM (
    SELECT * FROM paged result
    ORDER BY result.captured_at DESC,result.legacy_record_id
  ) result), '[]'))
) AS payload`;

function values(request: ContextualSearchRequest): readonly SqlValue[] {
  const q = request.q ? `%${request.q}%` : "";
  return [
    request.mode, q, request.domain, request.eventType, request.stage,
    request.processType, request.role, request.participantEntityId, request.assetId,
    request.region, request.industry, request.impact, request.sourceGrade,
    request.from, request.to, (request.page - 1) * request.pageSize, request.pageSize,
  ];
}

export async function searchContextualIntelligence(
  execute: SqlExecutor,
  request: ContextualSearchRequest,
): Promise<ContextualSearchResponse> {
  const sql = request.mode === "LEGACY" ? LEGACY_SQL : CONTEXTUAL_SQL;
  const result = await execute(sql, values(request));
  const payload = result.rows[0]?.payload as Omit<ContextualSearchResponse, "request"> | undefined;
  return {
    request,
    total: payload?.total ?? 0,
    facets: payload?.facets ?? {},
    results: payload?.results ?? [],
  };
}
