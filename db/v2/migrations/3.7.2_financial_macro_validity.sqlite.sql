-- Financial macro feature 1.0.2: normalize ECOS series validity dates to ISO-8601.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _fm102_guard(value TEXT NOT NULL CHECK(value='1.0.1'));
INSERT INTO _fm102_guard(value) SELECT schema_value FROM schema_meta WHERE schema_key='financial_macro_schema_version';
DROP TABLE _fm102_guard;

UPDATE macro_series
SET valid_from=substr(valid_from,1,4)||'-'||substr(valid_from,5,2)||'-01'
WHERE source_id='src_bok' AND length(valid_from)=6;

UPDATE schema_meta SET schema_value='1.0.2',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE schema_key='financial_macro_schema_version';
COMMIT;
