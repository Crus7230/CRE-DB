-- CRE DB Board compact dashboard search-index compaction (PostgreSQL/Supabase)
-- Converts one row per two-character posting to one text[] row per document.
-- Safe on both an existing 1.0.0 installation and a fresh 1.1.0 installation.

BEGIN;

CREATE TABLE IF NOT EXISTS cre_news.article_search_documents (
  dataset_version text NOT NULL,
  document_id text NOT NULL,
  terms text[] NOT NULL CHECK (cardinality(terms) > 0),
  PRIMARY KEY (dataset_version, document_id),
  FOREIGN KEY (dataset_version, document_id)
    REFERENCES cre_news.articles(dataset_version, document_id) ON DELETE CASCADE
);

DO $migration$
BEGIN
  IF to_regclass('cre_news.article_search_terms') IS NOT NULL THEN
    EXECUTE $sql$
      INSERT INTO cre_news.article_search_documents(dataset_version, document_id, terms)
      SELECT dataset_version, document_id, array_agg(term ORDER BY term)
      FROM cre_news.article_search_terms
      GROUP BY dataset_version, document_id
      ON CONFLICT(dataset_version, document_id) DO UPDATE
      SET terms = excluded.terms
    $sql$;
  END IF;
END
$migration$;

CREATE INDEX IF NOT EXISTS ix_cre_article_search_documents_terms
  ON cre_news.article_search_documents USING gin (terms);

ALTER TABLE cre_news.article_search_documents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON cre_news.article_search_documents FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION public.dashboard_contextual_evidence_search(
  q text,
  filters jsonb DEFAULT '{}'::jsonb,
  top_k integer DEFAULT 8,
  p_dataset_version text DEFAULT NULL
)
RETURNS jsonb
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public, extensions, cre_system, cre_news
SET enable_seqscan = off
AS $$
DECLARE
  v_version text;
  v_q text := btrim(COALESCE(q, ''));
  v_filters jsonb := COALESCE(filters, '{}'::jsonb);
  v_top_k integer := LEAST(GREATEST(COALESCE(top_k, 8), 1), 8);
  v_like_pattern text;
  v_from date;
  v_to date;
  v_payload jsonb;
BEGIN
  IF length(v_q) > 200 OR jsonb_typeof(v_filters) <> 'object' THEN
    RAISE EXCEPTION 'invalid evidence search request';
  END IF;
  IF COALESCE(v_filters->>'from', '') <> '' THEN
    v_from := (v_filters->>'from')::date;
  END IF;
  IF COALESCE(v_filters->>'to', '') <> '' THEN
    v_to := (v_filters->>'to')::date;
  END IF;
  IF v_from IS NOT NULL AND v_to IS NOT NULL AND v_from > v_to THEN
    RAISE EXCEPTION 'invalid evidence search range';
  END IF;
  v_like_pattern := '%' || replace(replace(replace(v_q, '\', '\\'), '%', '\%'), '_', '\_') || '%';
  SELECT version.dataset_version INTO v_version
  FROM cre_system.dataset_versions version
  WHERE version.dataset_version = COALESCE(
      p_dataset_version,
      (SELECT dataset_version FROM cre_system.active_manifest WHERE slot = 'dashboard')
    )
    AND version.status_code IN ('ACTIVE', 'RETIRED');
  IF v_version IS NULL THEN RAISE EXCEPTION 'dashboard dataset unavailable'; END IF;

  WITH candidate_ids AS MATERIALIZED (
    SELECT search_document.document_id
    FROM cre_news.article_search_documents search_document
    WHERE v_q <> ''
      AND char_length(v_q) <= 2
      AND search_document.dataset_version = v_version
      AND search_document.terms @> ARRAY[lower(v_q)]
    UNION ALL
    SELECT trigram_article.document_id
    FROM cre_news.articles trigram_article
    WHERE char_length(v_q) > 2
      AND trigram_article.dataset_version = v_version
      AND trigram_article.search_text ILIKE v_like_pattern ESCAPE '\'
    UNION ALL
    SELECT unfiltered_article.document_id
    FROM cre_news.articles unfiltered_article
    WHERE v_q = ''
      AND unfiltered_article.dataset_version = v_version
  ), matching AS MATERIALIZED (
    SELECT article.*,
           CASE WHEN v_q = '' THEN 0::double precision
                WHEN char_length(v_q) <= 2 THEN 1::double precision
                ELSE similarity(article.search_text, lower(v_q)) END AS score
    FROM candidate_ids candidate_id
    JOIN cre_news.articles article
      ON article.dataset_version = v_version
     AND article.document_id = candidate_id.document_id
    WHERE (v_from IS NULL OR article.article_date >= v_from)
      AND (v_to IS NULL OR article.article_date <= v_to)
      AND (COALESCE(v_filters->>'publisher', '') = ''
           OR article.publisher_name = v_filters->>'publisher')
      AND (COALESCE(v_filters->>'topic', '') = '' OR EXISTS (
        SELECT 1 FROM cre_news.article_topics topic
        WHERE topic.dataset_version = article.dataset_version
          AND topic.document_id = article.document_id
          AND topic.term_code = v_filters->>'topic'
      ))
  ), candidates AS MATERIALIZED (
    SELECT * FROM matching
    ORDER BY score DESC, published_at DESC, document_id
    LIMIT v_top_k
  )
  SELECT jsonb_build_object(
    'datasetVersion', v_version,
    'query', v_q,
    'generatedAt', clock_timestamp(),
    'filters', v_filters,
    'total', (SELECT count(*) FROM matching),
    'returned', count(*),
    'truncated', (SELECT count(*) FROM matching) > count(*),
    'items', COALESCE(jsonb_agg(jsonb_build_object(
      'documentId', candidate.document_id,
      'title', candidate.title,
      'publisher', candidate.publisher_name,
      'publishedAt', candidate.published_at,
      'href', candidate.canonical_url,
      'evidenceText', candidate.evidence_text,
      'score', round(candidate.score::numeric, 6)
    ) ORDER BY candidate.score DESC, candidate.published_at DESC, candidate.document_id),
    '[]'::jsonb)
  ) INTO v_payload
  FROM candidates candidate;
  RETURN v_payload;
END;
$$;

REVOKE ALL ON FUNCTION public.dashboard_contextual_evidence_search(text,jsonb,integer,text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.dashboard_contextual_evidence_search(text,jsonb,integer,text)
  TO service_role;

DROP TABLE IF EXISTS cre_news.article_search_terms;

INSERT INTO cre_system.schema_meta(schema_key, schema_value)
VALUES ('compact_dashboard_schema_version', '1.1.0')
ON CONFLICT (schema_key) DO UPDATE
SET schema_value = excluded.schema_value, updated_at = clock_timestamp();

NOTIFY pgrst, 'reload schema';
COMMIT;
