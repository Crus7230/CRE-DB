-- Correction-safe current-state projection for MOLIT transaction snapshots.
-- Raw collection history remains append-only and is intentionally untouched.

CREATE TABLE IF NOT EXISTS serving_molit_completed_partitions (
  partition_key TEXT PRIMARY KEY,
  district_code TEXT NOT NULL CHECK (
    length(district_code) = 5 AND district_code GLOB '11[0-9][0-9][0-9]'
  ),
  deal_month TEXT NOT NULL CHECK (
    deal_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'
  ),
  latest_run_id TEXT NOT NULL,
  latest_completed_at TEXT NOT NULL,
  discovered_count INTEGER CHECK (discovered_count IS NULL OR discovered_count >= 0),
  linked_document_count INTEGER NOT NULL CHECK (linked_document_count >= 0),
  active_record_count INTEGER CHECK (active_record_count IS NULL OR active_record_count >= 0),
  coverage_status TEXT NOT NULL CHECK (
    coverage_status IN (
      'COMPLETE_FULL_SNAPSHOT',
      'COMPLETE_EMPTY',
      'COMPLETE_BASELINE_WITH_CHANGES',
      'UNAVAILABLE_NO_BASELINE'
    )
  ),
  projection_generated_at TEXT NOT NULL,
  UNIQUE (district_code, deal_month),
  UNIQUE (latest_run_id)
);

CREATE INDEX IF NOT EXISTS ix_serving_molit_partitions_month
  ON serving_molit_completed_partitions(deal_month, district_code);

CREATE TABLE IF NOT EXISTS serving_molit_current_transactions (
  transaction_key TEXT PRIMARY KEY CHECK (length(transaction_key) = 64),
  transaction_key_json TEXT NOT NULL CHECK (json_valid(transaction_key_json)),
  partition_key TEXT NOT NULL,
  source_run_id TEXT NOT NULL,
  source_document_id TEXT NOT NULL,
  document_version_id TEXT NOT NULL,
  api_payload_json TEXT NOT NULL CHECK (json_valid(api_payload_json)),
  api_payload_sha256 TEXT NOT NULL CHECK (length(api_payload_sha256) = 64),
  duplicate_occurrence INTEGER NOT NULL CHECK (duplicate_occurrence >= 1),
  district_code TEXT NOT NULL,
  district_name TEXT NOT NULL,
  locality TEXT NOT NULL,
  building_use TEXT NOT NULL,
  building_area_text TEXT NOT NULL,
  deal_amount_text TEXT NOT NULL,
  deal_year TEXT NOT NULL,
  deal_month_number TEXT NOT NULL,
  deal_day TEXT NOT NULL,
  projection_generated_at TEXT NOT NULL,
  FOREIGN KEY (partition_key)
    REFERENCES serving_molit_completed_partitions(partition_key) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ix_serving_molit_current_month
  ON serving_molit_current_transactions(deal_year, deal_month_number);

CREATE INDEX IF NOT EXISTS ix_serving_molit_current_partition
  ON serving_molit_current_transactions(partition_key, api_payload_sha256);

INSERT INTO schema_meta(schema_key,schema_value,updated_at)
VALUES(
  'molit_current_serving_schema_version','1.1.0',
  strftime('%Y-%m-%dT%H:%M:%fZ','now')
)
ON CONFLICT(schema_key) DO UPDATE SET
  schema_value=excluded.schema_value,
  updated_at=excluded.updated_at;
