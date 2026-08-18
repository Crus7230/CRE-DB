BEGIN IMMEDIATE;

CREATE TABLE sale_process_relations (
    sale_process_relation_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
    from_sale_process_id TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    to_sale_process_id   TEXT NOT NULL REFERENCES sale_processes(sale_process_id) ON DELETE CASCADE,
    relation_type       TEXT NOT NULL CHECK (relation_type IN (
                          'RELAUNCHED_AS','PREVIOUS_ATTEMPT','SUCCESSOR_ATTEMPT',
                          'PREFERRED_SWITCH_CONTINUATION','PACKAGE_COMPONENT_OF',
                          'STRUCTURE_CHANGED_TO','DUPLICATE_OF','OTHER'
                        )),
    evidence_status     TEXT NOT NULL DEFAULT 'UNSOURCED' CHECK (evidence_status IN (
                          'UNSOURCED','SOURCE_CLAIM','MANUAL_VERIFIED'
                        )),
    source_claim_id     TEXT REFERENCES claims(claim_id),
    review_status       TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK (review_status IN (
                          'UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED'
                        )),
    metadata_json       TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(metadata_json)),
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(from_sale_process_id,to_sale_process_id,relation_type),
    CHECK (from_sale_process_id <> to_sale_process_id),
    CHECK (evidence_status <> 'SOURCE_CLAIM' OR source_claim_id IS NOT NULL)
) STRICT;

CREATE VIEW v_sale_process_relations AS
SELECT r.sale_process_relation_id,
       r.from_sale_process_id,
       source.process_code AS from_process_code,
       r.to_sale_process_id,
       target.process_code AS to_process_code,
       r.relation_type,
       r.evidence_status,
       r.review_status,
       r.source_claim_id,
       r.metadata_json
FROM sale_process_relations r
JOIN sale_processes source ON source.sale_process_id=r.from_sale_process_id
JOIN sale_processes target ON target.sale_process_id=r.to_sale_process_id;

UPDATE schema_meta
SET schema_value='2.4.0'
WHERE schema_key='schema_version' AND schema_value='2.3.0';

COMMIT;
