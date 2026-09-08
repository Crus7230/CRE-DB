-- SQLite 3.5.0 additive hardening for archives migrated before JSON object checks.
BEGIN IMMEDIATE;
CREATE TEMP TABLE _analytics_json_guard(value TEXT NOT NULL CHECK(value='3.5.0'));
INSERT INTO _analytics_json_guard(value) VALUES((SELECT schema_value FROM schema_meta WHERE schema_key='schema_version'));

CREATE TRIGGER IF NOT EXISTS trg_analytics_refresh_runs_json_insert BEFORE INSERT ON analytics_refresh_runs
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'analytics_refresh_runs.metadata_json must be an object'); END;
CREATE TRIGGER IF NOT EXISTS trg_analytics_refresh_runs_json_update BEFORE UPDATE OF metadata_json ON analytics_refresh_runs
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'analytics_refresh_runs.metadata_json must be an object'); END;

CREATE TRIGGER IF NOT EXISTS trg_keyword_dictionary_json_insert BEFORE INSERT ON keyword_dictionary
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_dictionary.metadata_json must be an object'); END;
CREATE TRIGGER IF NOT EXISTS trg_keyword_dictionary_json_update BEFORE UPDATE OF metadata_json ON keyword_dictionary
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_dictionary.metadata_json must be an object'); END;

CREATE TRIGGER IF NOT EXISTS trg_keyword_observations_json_insert BEFORE INSERT ON keyword_observations_daily
WHEN json_valid(NEW.source_scope_json)=0 OR json_type(NEW.source_scope_json)<>'object' OR json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_observations_daily JSON fields must be objects'); END;
CREATE TRIGGER IF NOT EXISTS trg_keyword_observations_json_update BEFORE UPDATE OF source_scope_json,metadata_json ON keyword_observations_daily
WHEN json_valid(NEW.source_scope_json)=0 OR json_type(NEW.source_scope_json)<>'object' OR json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_observations_daily JSON fields must be objects'); END;

CREATE TRIGGER IF NOT EXISTS trg_keyword_cooccurrences_json_insert BEFORE INSERT ON keyword_cooccurrences_daily
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_cooccurrences_daily.metadata_json must be an object'); END;
CREATE TRIGGER IF NOT EXISTS trg_keyword_cooccurrences_json_update BEFORE UPDATE OF metadata_json ON keyword_cooccurrences_daily
WHEN json_valid(NEW.metadata_json)=0 OR json_type(NEW.metadata_json)<>'object'
BEGIN SELECT RAISE(ABORT,'keyword_cooccurrences_daily.metadata_json must be an object'); END;

DROP TABLE _analytics_json_guard;
COMMIT;
