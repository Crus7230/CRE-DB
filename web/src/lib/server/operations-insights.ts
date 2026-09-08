import { normalizeOperationsOverview, type OperationsOverviewResponse } from "@/lib/operations-insights-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

export type OperationsSqlExecutor = SqlExecutor;

const OPERATIONS_OVERVIEW_SQL = `
WITH clock AS (
  SELECT strftime('%Y-%m-%dT%H:%M:%fZ','now') AS now_utc
), active_jobs AS (
  SELECT
    source_id,
    count(*) AS active_job_count,
    sum(CASE WHEN upper(coalesce(cadence_code,'')) NOT IN ('','MANUAL','ON_DEMAND') THEN 1 ELSE 0 END) AS scheduled_job_count
  FROM collection_jobs
  WHERE is_active=1
  GROUP BY source_id
), source_runs AS (
  SELECT j.source_id, r.*
  FROM collection_runs r
  JOIN collection_jobs j ON j.job_id=r.job_id
), run_rollup AS (
  SELECT
    source_id,
    count(*) AS run_count,
    sum(CASE WHEN status_code='COMPLETED' THEN 1 ELSE 0 END) AS completed_run_count,
    max(CASE WHEN status_code IN ('COMPLETED','PARTIAL') THEN completed_at END) AS latest_successful_at
  FROM source_runs
  GROUP BY source_id
), latest_runs AS (
  SELECT * FROM (
    SELECT
      source_id,
      status_code,
      discovered_count,
      inserted_count,
      updated_count,
      rejected_count,
      coalesce(completed_at,started_at,created_at) AS latest_run_at,
      row_number() OVER (
        PARTITION BY source_id
        ORDER BY coalesce(completed_at,started_at,created_at) DESC, run_id DESC
      ) AS rn
    FROM source_runs
  ) ranked
  WHERE rn=1
), document_rollup AS (
  SELECT
    sd.source_id,
    count(DISTINCT sd.document_id) AS distinct_document_count,
    count(DISTINCT dv.document_version_id) AS document_version_count
  FROM source_documents sd
  LEFT JOIN document_versions dv ON dv.document_id=sd.document_id
  GROUP BY sd.source_id
), run_status_counts AS (
  SELECT status_code AS status, count(*) AS count
  FROM collection_runs
  GROUP BY status_code
), archive_rows AS (
  SELECT asi.*
  FROM archived_serving_index asi
  JOIN archive_snapshots ars
    ON ars.archive_snapshot_id=asi.archive_snapshot_id
   AND ars.is_current=1 AND ars.integrity_status='VALIDATED'
), latest_document_versions_ranked AS (
  SELECT document_id,document_version_id,
         row_number() OVER (
           PARTITION BY document_id
           ORDER BY version_no DESC,document_version_id DESC
         ) AS version_rank
  FROM document_versions
), latest_document_versions AS (
  SELECT document_id,document_version_id
  FROM latest_document_versions_ranked
  WHERE version_rank=1
), current_cre_scope_ranked AS (
  SELECT document_version_id,classifier_version,status_code,
         row_number() OVER (
           PARTITION BY document_version_id
           ORDER BY CASE classifier_version
                      WHEN 'NEWS_CRE_SCOPE_RULE_V3' THEN 0
                      WHEN 'NEWS_CRE_SCOPE_RULE_V2' THEN 1
                      ELSE 2
                    END,
                    assessed_at DESC,document_scope_assessment_id DESC
         ) AS scope_rank
  FROM document_scope_assessments
  WHERE scope_code='CRE' AND classifier_version IN (
    'DART_CRE_SCOPE_RULE_V1','NEWS_CRE_SCOPE_RULE_V3','NEWS_CRE_SCOPE_RULE_V2','NEWS_CRE_SCOPE_RULE_V1','MOLIT_SCOPE_TIERED_V2'
  )
), current_cre_scope AS (
  SELECT document_version_id,classifier_version,status_code
  FROM current_cre_scope_ranked
  WHERE scope_rank=1
), serving_targets AS (
  SELECT 'EVENT' AS target_kind,e.event_id AS target_id FROM events e
  UNION SELECT 'ASSET',a.asset_id FROM assets a
  UNION SELECT 'ORGANIZATION',o.organization_id
    FROM organizations o
    JOIN organization_scope_assessments osa
      ON osa.organization_id=o.organization_id
     AND osa.scope_code='CRE' AND osa.classifier_version='ORG_CRE_SCOPE_RULE_V1'
     AND osa.status_code='CRE_CONFIRMED'
  UNION SELECT 'DOCUMENT',sd.document_id
    FROM source_documents sd
    LEFT JOIN collection_sources cs ON cs.source_id=sd.source_id
    LEFT JOIN latest_document_versions ldv ON ldv.document_id=sd.document_id
    LEFT JOIN current_cre_scope dsa ON dsa.document_version_id=ldv.document_version_id
    WHERE cs.source_code IS NULL
       OR cs.source_code NOT IN ('OPENDART','GOOGLE_NEWS_RSS','MOLIT_REAL_TRANSACTION')
       OR dsa.status_code='CRE_CONFIRMED'
  UNION SELECT 'LP_MANDATE',m.mandate_id FROM lp_mandates m
  UNION SELECT 'SALE_PROCESS',s.sale_process_id FROM sale_processes s
  UNION SELECT ar.record_kind,ar.record_id FROM archive_rows ar
    WHERE (ar.record_kind='EVENT' AND NOT EXISTS (SELECT 1 FROM events e WHERE e.event_id=ar.record_id))
       OR (ar.record_kind='DOCUMENT' AND NOT EXISTS (SELECT 1 FROM source_documents sd WHERE sd.document_id=ar.record_id))
       OR (ar.record_kind='LP_MANDATE' AND NOT EXISTS (SELECT 1 FROM lp_mandates m WHERE m.mandate_id=ar.record_id))
       OR (ar.record_kind='SALE_PROCESS' AND NOT EXISTS (SELECT 1 FROM sale_processes s WHERE s.sale_process_id=ar.record_id))
), governed_schemes AS (
  SELECT classification_scheme_id,scheme_code,scheme_name_ko,cardinality_code,
         target_kinds_json,vocabulary_version
  FROM classification_schemes
  WHERE governance_status='ACTIVE'
), current_assignments AS (
  SELECT rc.*,ct.governance_status AS term_governance_status
  FROM record_classifications rc
  JOIN classification_terms ct
    ON ct.classification_scheme_id=rc.classification_scheme_id
   AND ct.classification_term_id=rc.classification_term_id
  JOIN serving_targets st ON st.target_kind=rc.target_kind AND st.target_id=rc.target_id
  WHERE rc.review_status NOT IN ('REJECTED','SUPERSEDED')
    AND (rc.valid_from IS NULL OR rc.valid_from<=(SELECT now_utc FROM clock))
    AND (rc.valid_to IS NULL OR rc.valid_to>(SELECT now_utc FROM clock))
), eligible_by_kind AS (
  SELECT gs.classification_scheme_id,st.target_kind,count(DISTINCT st.target_id) AS eligible_count
  FROM governed_schemes gs
  JOIN serving_targets st ON EXISTS (
    SELECT 1
    FROM json_each(gs.target_kinds_json) target_kind
    WHERE target_kind.value=st.target_kind
  )
  GROUP BY gs.classification_scheme_id,st.target_kind
), eligible_counts AS (
  SELECT classification_scheme_id,sum(eligible_count) AS eligible_count
  FROM eligible_by_kind GROUP BY classification_scheme_id
), assignment_by_kind AS (
  SELECT classification_scheme_id,target_kind,
         count(DISTINCT target_id) AS assigned_count,
         count(DISTINCT CASE WHEN review_status='APPROVED' THEN target_id END) AS approved_count,
         count(DISTINCT CASE WHEN review_status IN ('UNREVIEWED','PENDING') THEN target_id END) AS pending_count,
         count(DISTINCT CASE WHEN is_primary=1 THEN target_id END) AS primary_count,
         sum(CASE WHEN term_governance_status='DEPRECATED' THEN 1 ELSE 0 END) AS deprecated_count
  FROM current_assignments
  GROUP BY classification_scheme_id,target_kind
), assignment_counts AS (
   SELECT classification_scheme_id,sum(assigned_count) AS assigned_count,
          sum(approved_count) AS approved_count,sum(pending_count) AS pending_count,
          sum(primary_count) AS primary_count,sum(deprecated_count) AS deprecated_count
  FROM assignment_by_kind GROUP BY classification_scheme_id
), primary_conflicts AS (
  SELECT classification_scheme_id,count(*) AS conflict_count
  FROM (
    SELECT classification_scheme_id,target_kind,target_id
    FROM current_assignments
    GROUP BY classification_scheme_id,target_kind,target_id
    HAVING sum(CASE WHEN is_primary=1 THEN 1 ELSE 0 END)>1
  ) conflicts GROUP BY classification_scheme_id
), scheme_quality AS (
  SELECT gs.scheme_code,gs.scheme_name_ko,gs.cardinality_code,gs.vocabulary_version,
         coalesce(ec.eligible_count,0) AS eligible_count,
         coalesce(ac.assigned_count,0) AS assigned_count,
         coalesce(ac.approved_count,0) AS approved_count,
         coalesce(ac.pending_count,0) AS pending_count,
         coalesce(ac.primary_count,0) AS primary_count,
         max(coalesce(ec.eligible_count,0)-coalesce(ac.primary_count,0),0) AS primary_missing_count,
         coalesce(pc.conflict_count,0) AS primary_conflict_count,
         coalesce(ac.deprecated_count,0) AS deprecated_count
  FROM governed_schemes gs
  LEFT JOIN eligible_counts ec ON ec.classification_scheme_id=gs.classification_scheme_id
  LEFT JOIN assignment_counts ac ON ac.classification_scheme_id=gs.classification_scheme_id
  LEFT JOIN primary_conflicts pc ON pc.classification_scheme_id=gs.classification_scheme_id
), review_status_counts AS (
  SELECT review_status AS status,count(*) AS count FROM current_assignments GROUP BY review_status
), evidence_status_counts AS (
  SELECT evidence_status AS status,count(*) AS count FROM current_assignments GROUP BY evidence_status
), source_health AS (
  SELECT
    s.source_code,
    s.source_name,
    s.source_kind,
    CASE
      WHEN s.is_active=0 THEN 'DISABLED'
      WHEN coalesce(aj.active_job_count,0)>0 THEN 'ONBOARDED'
      ELSE 'NOT_ONBOARDED'
    END AS onboarding,
    CASE
      WHEN s.is_active=0 OR coalesce(aj.active_job_count,0)=0 THEN 'NOT_ONBOARDED'
      WHEN coalesce(aj.scheduled_job_count,0)>0 THEN 'SCHEDULED'
      ELSE 'MANUAL'
    END AS sla_mode,
    'NO_SLA' AS freshness,
    coalesce(lr.status_code,'NONE') AS latest_execution,
    CASE
      WHEN lr.status_code IS NULL OR lr.status_code NOT IN ('COMPLETED','PARTIAL') THEN 'UNKNOWN'
      WHEN coalesce(lr.inserted_count,0)+coalesce(lr.updated_count,0)>0 THEN 'NEW_DATA'
      WHEN coalesce(lr.discovered_count,0)=0 THEN 'ZERO_RESULT'
      WHEN coalesce(lr.discovered_count,0)>0 THEN 'REUSED_ONLY'
      ELSE 'UNKNOWN'
    END AS data_outcome,
    coalesce(aj.active_job_count,0) AS active_job_count,
    coalesce(aj.scheduled_job_count,0) AS scheduled_job_count,
    coalesce(rr.run_count,0) AS run_count,
    coalesce(rr.completed_run_count,0) AS completed_run_count,
    coalesce(dr.distinct_document_count,0) AS distinct_document_count,
    coalesce(dr.document_version_count,0) AS document_version_count,
    rr.latest_successful_at,
    lr.latest_run_at,
    lr.discovered_count,
    lr.inserted_count,
    lr.updated_count,
    lr.rejected_count
  FROM collection_sources s
  LEFT JOIN active_jobs aj ON aj.source_id=s.source_id
  LEFT JOIN run_rollup rr ON rr.source_id=s.source_id
  LEFT JOIN latest_runs lr ON lr.source_id=s.source_id
  LEFT JOIN document_rollup dr ON dr.source_id=s.source_id
)
SELECT json_object(
  'generatedAt',(SELECT now_utc FROM clock),
  'asOfAt',(SELECT now_utc FROM clock),
  'policyVersion','SOURCE_HEALTH_V1',
  'summary',json_object(
    'sourceCount',(SELECT count(*) FROM source_health),
    'onboardedSourceCount',(SELECT count(*) FROM source_health WHERE onboarding='ONBOARDED'),
    'notOnboardedSourceCount',(SELECT count(*) FROM source_health WHERE onboarding='NOT_ONBOARDED'),
    'distinctDocumentCount',(SELECT coalesce(sum(distinct_document_count),0) FROM source_health),
    'documentVersionCount',(SELECT coalesce(sum(document_version_count),0) FROM source_health),
    'runCount',(SELECT count(*) FROM collection_runs)
  ),
  'runStatusCounts',json(coalesce((
    SELECT json_group_array(json_object('status',status,'count',count))
    FROM (SELECT status,count FROM run_status_counts ORDER BY status)
  ),'[]')),
  'classificationQuality',json_object(
    'schemes',json(coalesce((
      SELECT json_group_array(json_object(
        'schemeCode',scheme_code,'schemeName',scheme_name_ko,'cardinality',cardinality_code,
        'vocabularyVersion',vocabulary_version,'eligibleTargetCount',eligible_count,
        'assignedTargetCount',assigned_count,'approvedTargetCount',approved_count,
        'pendingTargetCount',pending_count,'primaryTargetCount',primary_count,
        'primaryMissingCount',primary_missing_count,'primaryConflictCount',primary_conflict_count,
        'deprecatedAssignmentCount',deprecated_count
      ))
      FROM (SELECT * FROM scheme_quality ORDER BY scheme_name_ko)
    ),'[]')),
    'reviewStatusCounts',json(coalesce((
      SELECT json_group_array(json_object('status',status,'count',count))
      FROM (SELECT status,count FROM review_status_counts ORDER BY status)
    ),'[]')),
    'evidenceStatusCounts',json(coalesce((
      SELECT json_group_array(json_object('status',status,'count',count))
      FROM (SELECT status,count FROM evidence_status_counts ORDER BY status)
    ),'[]')),
    'currentAssignmentCount',(SELECT count(*) FROM current_assignments),
    'supersededAssignmentCount',(SELECT count(*) FROM record_classifications WHERE review_status='SUPERSEDED')
  ),
  'sources',json(coalesce((
    SELECT json_group_array(json_object(
      'sourceCode',source_code,
      'sourceName',source_name,
      'sourceKind',source_kind,
      'onboarding',onboarding,
      'slaMode',sla_mode,
      'freshness',freshness,
      'latestExecution',latest_execution,
      'dataOutcome',data_outcome,
      'activeJobCount',active_job_count,
      'scheduledJobCount',scheduled_job_count,
      'runCount',run_count,
      'completedRunCount',completed_run_count,
      'distinctDocumentCount',distinct_document_count,
      'documentVersionCount',document_version_count,
      'latestSuccessfulAt',latest_successful_at,
      'latestRunAt',latest_run_at,
      'expectedIntervalSeconds',NULL,
      'graceSeconds',NULL,
      'latestDiscoveredCount',discovered_count,
      'latestInsertedCount',inserted_count,
      'latestUpdatedCount',updated_count,
      'latestRejectedCount',rejected_count
    ))
    FROM (
      SELECT * FROM source_health
      ORDER BY distinct_document_count DESC,source_name
    )
  ),'[]'))
) AS payload;
`;

export async function getOperationsOverview(execute: OperationsSqlExecutor): Promise<OperationsOverviewResponse> {
  const result = await execute(OPERATIONS_OVERVIEW_SQL, []);
  if (result.rows.length !== 1) throw new Error("Operations overview query returned an unexpected row count");
  return normalizeOperationsOverview(result.rows[0].payload);
}
