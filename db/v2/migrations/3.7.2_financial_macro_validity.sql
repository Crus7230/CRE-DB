-- PostgreSQL financial macro feature 1.0.2: normalize ECOS series validity dates to ISO-8601.
BEGIN;
DO $$ DECLARE v TEXT; BEGIN
 SELECT schema_value INTO v FROM market_intelligence.schema_meta WHERE schema_key='financial_macro_schema_version';
 IF v IS DISTINCT FROM '1.0.1' THEN RAISE EXCEPTION 'financial macro feature 1.0.1 required, found %',v; END IF;
END $$;

UPDATE market_intelligence.macro_series
SET valid_from=substr(valid_from,1,4)||'-'||substr(valid_from,5,2)||'-01'
WHERE source_id='src_bok' AND length(valid_from)=6;

UPDATE market_intelligence.schema_meta
SET schema_value='1.0.2',updated_at=to_char(clock_timestamp() AT TIME ZONE 'UTC','YYYY-MM-DD"T"HH24:MI:SS.MS"Z"')
WHERE schema_key='financial_macro_schema_version';
COMMIT;
