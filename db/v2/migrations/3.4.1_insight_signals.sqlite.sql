-- SQLite V3.4.1: reviewable insight signals with explicit evidence.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _v341_guard(value TEXT NOT NULL CHECK(value='3.4.0'));
INSERT INTO _v341_guard(value) VALUES((SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'));

CREATE TABLE insight_signals (
    insight_signal_id TEXT PRIMARY KEY,
    signal_type TEXT NOT NULL CHECK(signal_type IN ('KEYWORD_BURST','COOCCURRENCE_SHIFT','VOLUME_ANOMALY')),
    signal_date TEXT NOT NULL,
    title TEXT NOT NULL,
    summary_text TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'UNREVIEWED' CHECK(review_status IN ('UNREVIEWED','PENDING','APPROVED','REJECTED','SUPERSEDED')),
    severity_code TEXT NOT NULL CHECK(severity_code IN ('LOW','MEDIUM','HIGH')),
    keyword_id TEXT REFERENCES keyword_dictionary(keyword_id) ON DELETE RESTRICT,
    strength_score REAL NOT NULL CHECK(strength_score BETWEEN 0 AND 1),
    evidence_score REAL NOT NULL CHECK(evidence_score BETWEEN 0 AND 1),
    source_diversity_score REAL NOT NULL CHECK(source_diversity_score BETWEEN 0 AND 1),
    confidence_score REAL NOT NULL CHECK(confidence_score BETWEEN 0 AND 1),
    algorithm_version TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    window_start TEXT NOT NULL,
    window_end TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object')
) STRICT;
CREATE UNIQUE INDEX ux_insight_signal_identity ON insight_signals(signal_type,signal_date,coalesce(keyword_id,'__NONE__'),algorithm_version);
CREATE INDEX ix_insight_signals_review ON insight_signals(review_status,signal_date DESC,severity_code);
CREATE INDEX ix_insight_signals_keyword ON insight_signals(keyword_id);

CREATE TABLE insight_signal_evidence (
    insight_signal_evidence_id TEXT PRIMARY KEY,
    insight_signal_id TEXT NOT NULL REFERENCES insight_signals(insight_signal_id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('DOCUMENT','DOCUMENT_VERSION','EVENT','CLAIM')),
    target_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL CHECK(evidence_role IN ('TRIGGER','SUPPORTING','CONTRADICTING')),
    source_document_version_id TEXT REFERENCES document_versions(document_version_id) ON DELETE RESTRICT,
    evidence_rank INTEGER NOT NULL CHECK(evidence_rank>0),
    evidence_locator TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(metadata_json) AND json_type(metadata_json)='object'),
    created_at TEXT NOT NULL,
    UNIQUE(insight_signal_id,target_kind,target_id,evidence_role)
) STRICT;
CREATE INDEX ix_insight_signal_evidence_signal ON insight_signal_evidence(insight_signal_id,evidence_rank);
CREATE INDEX ix_insight_signal_evidence_version ON insight_signal_evidence(source_document_version_id);

UPDATE schema_meta SET schema_value='3.4.1' WHERE schema_key='schema_version';
DROP TABLE _v341_guard;
COMMIT;
