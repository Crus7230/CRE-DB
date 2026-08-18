-- V2.6.0 -> V2.7.0: auditable post-collection relationship reconciliation
PRAGMA foreign_keys=ON;
BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS predicate_relationship_rules (
    relationship_rule_id TEXT PRIMARY KEY,
    predicate_code      TEXT NOT NULL REFERENCES predicate_definitions(predicate_code),
    claim_role_code     TEXT REFERENCES claim_role_definitions(role_code),
    target_relation     TEXT NOT NULL CHECK (target_relation IN (
                          'EVENT_PARTICIPANT','PROPERTY_OCCUPANCY','BUSINESS_ACTIVITY'
                        )),
    participant_role_code TEXT,
    occupancy_type      TEXT,
    tenure_type         TEXT,
    minimum_verification_status TEXT NOT NULL DEFAULT 'VERIFIED' CHECK (
                          minimum_verification_status IN ('VERIFIED','PENDING','UNVERIFIED')
                        ),
    auto_apply          INTEGER NOT NULL DEFAULT 1 CHECK (auto_apply IN (0,1)),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    UNIQUE(predicate_code,claim_role_code,target_relation)
) STRICT;

INSERT OR IGNORE INTO claim_role_definitions(role_code,name_ko,allowed_kind,description) VALUES
 ('SUBJECT_ORGANIZATION','대상 조직','ENTITY','조직 단위 claim의 명시적 subject');

INSERT OR IGNORE INTO predicate_relationship_rules(
 relationship_rule_id,predicate_code,claim_role_code,target_relation,
 participant_role_code,minimum_verification_status
) VALUES
 ('participant-role-tenant','PARTICIPANT_ROLE','TENANT','EVENT_PARTICIPANT','TENANT','VERIFIED'),
 ('participant-role-landlord','PARTICIPANT_ROLE','LANDLORD','EVENT_PARTICIPANT','LANDLORD','VERIFIED'),
 ('participant-role-owner','PARTICIPANT_ROLE','OWNER','EVENT_PARTICIPANT','OWNER','VERIFIED'),
 ('participant-role-operator','PARTICIPANT_ROLE','OPERATOR','EVENT_PARTICIPANT','OPERATOR','VERIFIED'),
 ('participant-role-investor','PARTICIPANT_ROLE','INVESTOR','EVENT_PARTICIPANT','INVESTOR','VERIFIED'),
 ('participant-role-buyer','PARTICIPANT_ROLE','BUYER','EVENT_PARTICIPANT','BUYER','VERIFIED'),
 ('participant-role-seller','PARTICIPANT_ROLE','SELLER','EVENT_PARTICIPANT','SELLER','VERIFIED'),
 ('business-domain-subject','BUSINESS_DOMAIN','SUBJECT_ORGANIZATION','BUSINESS_ACTIVITY',NULL,'VERIFIED');

CREATE TABLE IF NOT EXISTS relationship_resolution_runs (
    relationship_run_id TEXT PRIMARY KEY,
    collection_run_id   TEXT REFERENCES collection_runs(run_id),
    scope_code          TEXT NOT NULL CHECK (scope_code IN ('COLLECTION_RUN','ALL_EXISTING')),
    pipeline_version    TEXT NOT NULL,
    started_at          TEXT NOT NULL,
    completed_at        TEXT,
    status_code         TEXT NOT NULL CHECK (status_code IN ('RUNNING','COMPLETED','FAILED')),
    resolved_mentions   INTEGER NOT NULL DEFAULT 0 CHECK (resolved_mentions >= 0),
    ambiguous_mentions  INTEGER NOT NULL DEFAULT 0 CHECK (ambiguous_mentions >= 0),
    event_participants_created INTEGER NOT NULL DEFAULT 0 CHECK (event_participants_created >= 0),
    occupancies_created INTEGER NOT NULL DEFAULT 0 CHECK (occupancies_created >= 0),
    business_activities_created INTEGER NOT NULL DEFAULT 0 CHECK (business_activities_created >= 0),
    unresolved_mentions INTEGER NOT NULL DEFAULT 0 CHECK (unresolved_mentions >= 0),
    error_message       TEXT,
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json))
) STRICT;

CREATE INDEX IF NOT EXISTS ix_relationship_runs_collection
    ON relationship_resolution_runs(collection_run_id,started_at DESC);

DROP VIEW IF EXISTS v_relationship_gaps;
CREATE VIEW v_relationship_gaps AS
SELECT 'UNRESOLVED_ORGANIZATION_MENTION' AS gap_code,
       'MENTION' AS record_kind,
       m.mention_id AS record_id,
       m.surface_text AS detail,
       (SELECT min(rd.run_id)
          FROM extraction_runs er
          JOIN run_documents rd ON rd.document_version_id=er.document_version_id
         WHERE er.extraction_run_id=m.extraction_run_id) AS collection_run_id
  FROM mentions m
 WHERE m.mention_type='ORGANIZATION'
   AND m.review_status<>'REJECTED'
   AND NOT EXISTS (
       SELECT 1 FROM mention_resolutions mr
        WHERE mr.mention_id=m.mention_id AND mr.selected=1
   )
UNION ALL
SELECT 'ORGANIZATION_MISSING_IDENTIFIERS','ORGANIZATION',o.organization_id,o.canonical_name,NULL
  FROM organizations o
 WHERE o.status_code<>'MERGED'
   AND o.corporate_no IS NULL AND o.business_no IS NULL
   AND o.dart_corp_code IS NULL AND o.stock_code IS NULL
UNION ALL
SELECT 'COMPANY_EVENT_WITHOUT_PARTICIPANT','EVENT',e.event_id,e.canonical_title,NULL
  FROM events e
  JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
 WHERE ec.code IN ('LEASE','CORPORATE_RELOCATION','INVESTMENT')
   AND e.lifecycle_status<>'MERGED'
   AND NOT EXISTS (SELECT 1 FROM event_participants ep WHERE ep.event_id=e.event_id)
UNION ALL
SELECT 'PROPERTY_EVENT_WITHOUT_PLACE','EVENT',e.event_id,e.canonical_title,NULL
  FROM events e
  JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
 WHERE ec.code IN ('LEASE','CORPORATE_RELOCATION')
   AND e.lifecycle_status<>'MERGED'
   AND NOT EXISTS (SELECT 1 FROM event_assets ea WHERE ea.event_id=e.event_id)
   AND NOT EXISTS (SELECT 1 FROM event_projects ep WHERE ep.event_id=e.event_id);

UPDATE schema_meta SET schema_value='2.7.0' WHERE schema_key='schema_version';
INSERT OR REPLACE INTO schema_meta(schema_key,schema_value) VALUES('relationship_pipeline_version','post-collection-relationships-v1');
