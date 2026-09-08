import type { CompanyDetailResponse, CompanyListRequest, CompanyListResponse } from "@/lib/intelligence-contract";
import type { SqlExecutor } from "@/lib/server/market-search";

// location_subjects(organization_id, organization_name) must be declared before
// this fragment. Managed taxonomy is authoritative when present; legacy event
// mentions remain a clearly labelled discovery layer until review catches up.
const locationEvidenceCtes = `
managed_location_category_candidates AS (
  SELECT r.target_id AS document_id,t.term_code AS source_category,
         r.review_status AS classification_review_status,
         r.evidence_status AS classification_evidence_status,
         r.confidence AS classification_confidence,
         row_number() OVER (
           PARTITION BY r.target_id
           ORDER BY r.is_primary DESC,
             CASE t.term_code WHEN 'RELOCATION' THEN 1 ELSE 2 END,
             (r.confidence IS NULL),r.confidence DESC,r.assigned_at DESC,r.record_classification_id
         ) AS category_rank
  FROM record_classifications r
  JOIN classification_schemes s
    ON s.classification_scheme_id=r.classification_scheme_id
  JOIN classification_terms t
    ON t.classification_scheme_id=r.classification_scheme_id
   AND t.classification_term_id=r.classification_term_id
  WHERE r.target_kind='DOCUMENT'
    AND s.scheme_code='MARKET_CATEGORY'
    AND t.term_code IN ('LEASE','RELOCATION')
    AND r.review_status<>'REJECTED'
), managed_location_categories AS (
  SELECT document_id,source_category,classification_review_status,
         classification_evidence_status,classification_confidence
  FROM managed_location_category_candidates
  WHERE category_rank=1
), legacy_location_mention_candidates AS (
  SELECT dv.document_id,ec.code AS source_category,em.status_code AS mention_status,
         em.confidence,em.title_raw,em.summary_raw,em.stage_code_hint,
         row_number() OVER (
           PARTITION BY dv.document_id
           ORDER BY CASE em.status_code WHEN 'APPROVED' THEN 1 WHEN 'REVIEW_READY' THEN 2
                    WHEN 'RESOLUTION_REQUIRED' THEN 3 ELSE 4 END,
             (em.confidence IS NULL),em.confidence DESC,dv.version_no DESC,em.event_mention_id
         ) AS mention_rank
  FROM event_mentions em
  JOIN event_categories ec ON ec.event_category_id=em.event_category_id
  JOIN extraction_runs er ON er.extraction_run_id=em.extraction_run_id
  JOIN document_versions dv ON dv.document_version_id=er.document_version_id
  WHERE ec.code IN ('LEASE','CORPORATE_RELOCATION') AND em.status_code<>'REJECTED'
), legacy_location_mentions AS (
  SELECT document_id,source_category,mention_status,confidence,title_raw,summary_raw,stage_code_hint
  FROM legacy_location_mention_candidates
  WHERE mention_rank=1
), location_document_metadata AS (
  SELECT m.document_id,m.source_category,'MANAGED_TAXONOMY' AS classification_basis,
         m.classification_review_status,m.classification_evidence_status,
         coalesce(m.classification_confidence,l.confidence) AS confidence,
         l.mention_status,l.title_raw,l.summary_raw,l.stage_code_hint
  FROM managed_location_categories m
  LEFT JOIN legacy_location_mentions l ON l.document_id=m.document_id
  UNION ALL
  SELECT l.document_id,l.source_category,'LEGACY_DISCOVERY' AS classification_basis,
         NULL AS classification_review_status,NULL AS classification_evidence_status,
         l.confidence,l.mention_status,l.title_raw,l.summary_raw,l.stage_code_hint
  FROM legacy_location_mentions l
  LEFT JOIN managed_location_categories m ON m.document_id=l.document_id
  WHERE m.document_id IS NULL
), location_document_version_candidates AS (
  SELECT dv.document_id,dv.document_version_id,dv.title,dv.published_at,dv.snippet_text,dv.version_no,
         row_number() OVER (
           PARTITION BY dv.document_id
           ORDER BY dv.version_no DESC,dv.document_version_id DESC
         ) AS version_rank
  FROM document_versions dv
  JOIN location_document_metadata meta ON meta.document_id=dv.document_id
), location_document_corpus AS (
  SELECT meta.*,dv.document_version_id,dv.title,dv.published_at,dv.snippet_text,
         sd.publisher_name AS publisher,sd.canonical_url AS href,sd.document_type,
         lower(trim(concat_ws(' ',
           CASE WHEN nullif(sd.publisher_name,'') IS NULL THEN lower(coalesce(dv.title,''))
                ELSE replace(lower(coalesce(dv.title,'')),lower(sd.publisher_name),'') END,
           CASE WHEN nullif(sd.publisher_name,'') IS NULL THEN lower(coalesce(dv.snippet_text,''))
                ELSE replace(lower(coalesce(dv.snippet_text,'')),lower(sd.publisher_name),'') END,
           CASE WHEN nullif(sd.publisher_name,'') IS NULL THEN lower(coalesce(meta.title_raw,''))
                ELSE replace(lower(coalesce(meta.title_raw,'')),lower(sd.publisher_name),'') END,
           CASE WHEN nullif(sd.publisher_name,'') IS NULL THEN lower(coalesce(meta.summary_raw,''))
                ELSE replace(lower(coalesce(meta.summary_raw,'')),lower(sd.publisher_name),'') END
         ))) AS content_text,
         nullif(substr(trim(replace(replace(replace(
           CASE WHEN nullif(sd.publisher_name,'') IS NULL
                THEN coalesce(nullif(meta.summary_raw,''),nullif(meta.title_raw,''),
                  CASE WHEN ltrim(coalesce(dv.snippet_text,'')) LIKE '{%' THEN NULL ELSE dv.snippet_text END)
                ELSE replace(coalesce(nullif(meta.summary_raw,''),nullif(meta.title_raw,''),
                  CASE WHEN ltrim(coalesce(dv.snippet_text,'')) LIKE '{%' THEN NULL ELSE dv.snippet_text END),sd.publisher_name,'')
           END,char(13),' '),char(10),' '),char(9),' ')),1,420),'') AS evidence_excerpt
  FROM location_document_metadata meta
  JOIN location_document_version_candidates dv
    ON dv.document_id=meta.document_id AND dv.version_rank=1
  JOIN source_documents sd ON sd.document_id=meta.document_id
), action_location_documents AS (
  SELECT *
  FROM location_document_corpus
  WHERE instr(content_text,'잔류')>0 OR instr(content_text,'재계약')>0
     OR instr(content_text,'계약 갱신')>0 OR instr(content_text,'임대차 갱신')>0
     OR instr(content_text,'본사')>0 OR instr(content_text,'사옥')>0
     OR instr(content_text,'오피스')>0 OR instr(content_text,'사무실')>0
     OR instr(content_text,'사업장')>0 OR instr(content_text,'사무소')>0
     OR instr(content_text,'선임차')>0 OR instr(content_text,'임대차 계약')>0
     OR instr(content_text,'임차 계약')>0 OR instr(content_text,'입주 예정')>0
     OR instr(content_text,'임차인')>0 OR instr(content_text,'테넌트')>0
     OR instr(replace(content_text,' ',''),'"status":"contracted"')>0
), location_name_positions AS (
  SELECT s.organization_id,s.organization_name,d.*,
         instr(d.content_text,lower(s.organization_name)) AS match_position
  FROM location_subjects s
  JOIN action_location_documents d ON length(s.organization_name)>=3
), location_name_matches AS (
  SELECT p.*,
         substr(p.content_text,max(p.match_position-120,1),length(p.organization_name)+360) AS evidence_window
  FROM location_name_positions p
  WHERE p.match_position>0
    AND (
      p.match_position=1
      OR instr(' ' || char(9) || char(10) || char(13) || '.,:;!?()[]{}"/\\·…-–—' || char(39),
               substr(p.content_text,p.match_position-1,1))>0
    )
    AND (
      substr(p.content_text,p.match_position+length(p.organization_name),1)=''
      OR instr(' ' || char(9) || char(10) || char(13) || '.,:;!?()[]{}"/\\·…-–—' || char(39),
               substr(p.content_text,p.match_position+length(p.organization_name),1))>0
      OR substr(p.content_text,p.match_position+length(p.organization_name),1)
         IN ('은','는','이','가','을','를','의','도','과','와','에','로')
    )
    AND p.content_text NOT LIKE '%' || lower(p.organization_name) || ' 이어%'
    AND p.content_text NOT LIKE '%' || lower(p.organization_name) || '에 이어%'
    AND p.content_text NOT LIKE '%' || lower(p.organization_name) || '을 이어%'
    AND p.content_text NOT LIKE '%' || lower(p.organization_name) || '를 이어%'
    AND p.content_text NOT LIKE '%' || lower(p.organization_name) || '처럼%'
), typed_location_evidence AS (
  SELECT n.*,
    CASE
      WHEN instr(evidence_window,'잔류')>0 OR instr(evidence_window,'재계약')>0
        OR instr(evidence_window,'계약 갱신')>0 OR instr(evidence_window,'임대차 갱신')>0 THEN 'STAY'
      WHEN instr(evidence_window,'이전')>0 AND (
        (instr(evidence_window,'본사')>0 AND abs(instr(evidence_window,'본사')-instr(evidence_window,'이전'))<=33)
        OR (instr(evidence_window,'사옥')>0 AND abs(instr(evidence_window,'사옥')-instr(evidence_window,'이전'))<=33)
        OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'이전'))<=33)
        OR (instr(evidence_window,'사무실')>0 AND abs(instr(evidence_window,'사무실')-instr(evidence_window,'이전'))<=33)
        OR (instr(evidence_window,'사업장')>0 AND abs(instr(evidence_window,'사업장')-instr(evidence_window,'이전'))<=33)
      ) THEN 'RELOCATION'
      WHEN (instr(evidence_window,'사무소')>0 OR instr(evidence_window,'오피스')>0) AND (
        (instr(evidence_window,'개설')>0 AND (
          (instr(evidence_window,'사무소')>0 AND abs(instr(evidence_window,'사무소')-instr(evidence_window,'개설'))<=27)
          OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'개설'))<=27)))
        OR (instr(evidence_window,'신설')>0 AND (
          (instr(evidence_window,'사무소')>0 AND abs(instr(evidence_window,'사무소')-instr(evidence_window,'신설'))<=27)
          OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'신설'))<=27)))
        OR (instr(evidence_window,'확장')>0 AND (
          (instr(evidence_window,'사무소')>0 AND abs(instr(evidence_window,'사무소')-instr(evidence_window,'확장'))<=27)
          OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'확장'))<=27)))
        OR (instr(evidence_window,'진입')>0 AND (
          (instr(evidence_window,'사무소')>0 AND abs(instr(evidence_window,'사무소')-instr(evidence_window,'진입'))<=27)
          OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'진입'))<=27)))
        OR (instr(evidence_window,'진출')>0 AND (
          (instr(evidence_window,'사무소')>0 AND abs(instr(evidence_window,'사무소')-instr(evidence_window,'진출'))<=27)
          OR (instr(evidence_window,'오피스')>0 AND abs(instr(evidence_window,'오피스')-instr(evidence_window,'진출'))<=27)))
      ) THEN 'EXPANSION'
      WHEN instr(evidence_window,'선임차')>0 OR instr(evidence_window,'임대차 계약')>0
        OR instr(evidence_window,'임차 계약')>0 OR instr(evidence_window,'입주 예정')>0
        OR instr(evidence_window,'임차인')>0 OR instr(evidence_window,'테넌트')>0
        OR instr(replace(evidence_window,' ',''),'"status":"contracted"')>0 THEN 'NEW_LEASE'
      ELSE NULL
    END AS evidence_type,
    CASE
      WHEN instr(evidence_window,'잔류 확정')>0 THEN '잔류 확정'
      WHEN instr(evidence_window,'임대차 갱신')>0 THEN '임대차 갱신'
      WHEN instr(evidence_window,'재계약')>0 THEN '재계약'
      WHEN instr(evidence_window,'본사 이전 확정')>0 THEN '본사 이전 확정'
      WHEN instr(evidence_window,'사옥 이전 확정')>0 THEN '사옥 이전 확정'
      WHEN instr(evidence_window,'본사 이전')>0 THEN '본사 이전'
      WHEN instr(evidence_window,'사옥 이전')>0 THEN '사옥 이전'
      WHEN instr(evidence_window,'오피스 이전')>0 THEN '오피스 이전'
      WHEN instr(evidence_window,'사무실 이전')>0 THEN '사무실 이전'
      WHEN instr(evidence_window,'사업장 이전')>0 THEN '사업장 이전'
      WHEN instr(evidence_window,'선임차 확정')>0 THEN '선임차 확정'
      WHEN instr(evidence_window,'선임차')>0 THEN '선임차'
      WHEN instr(evidence_window,'임대차 계약')>0 THEN '임대차 계약'
      WHEN instr(evidence_window,'임차 계약')>0 THEN '임차 계약'
      WHEN instr(evidence_window,'입주 예정')>0 THEN '입주 예정'
      WHEN instr(evidence_window,'사무소 개설')>0 THEN '사무소 개설'
      WHEN instr(evidence_window,'오피스 신설')>0 THEN '오피스 신설'
      WHEN instr(evidence_window,'사무소 확장')>0 THEN '사무소 확장'
      ELSE NULL
    END AS matched_phrase
  FROM location_name_matches n
), staged_location_evidence AS (
  SELECT t.*,
    CASE
      WHEN instr(evidence_window,'잔류 확정')>0 OR instr(evidence_window,'이전 확정')>0
        OR instr(evidence_window,'계약 체결')>0 OR instr(evidence_window,'선임차 확정')>0
        OR instr(evidence_window,'입주 확정')>0 OR instr(evidence_window,'입주 예정')>0
        OR instr(evidence_window,'이전 완료')>0
        OR instr(replace(evidence_window,' ',''),'"status":"contracted"')>0 THEN 'CONFIRMED_WORDING'
      WHEN instr(evidence_window,'타진')>0 OR instr(evidence_window,'검토')>0
        OR instr(evidence_window,'논의')>0 OR instr(evidence_window,'가능성')>0
        OR instr(evidence_window,'후보')>0 THEN 'EXPLORING_WORDING'
      WHEN instr(evidence_window,'추진')>0 OR instr(evidence_window,'속도')>0
        OR instr(evidence_window,'계획')>0 OR instr(evidence_window,'우선')>0
        OR instr(evidence_window,'선정')>0 OR instr(evidence_window,'진입')>0
        OR instr(evidence_window,'진출')>0 OR instr(evidence_window,'개설')>0
        OR instr(evidence_window,'신설')>0 OR instr(evidence_window,'확장')>0 THEN 'IN_PROGRESS_WORDING'
      ELSE 'REVIEW_REQUIRED'
    END AS wording_stage
  FROM typed_location_evidence t
  WHERE evidence_type IS NOT NULL
    AND NOT (
      instr(evidence_window,'이전')>0 AND (
        (instr(evidence_window,'부인')>0 AND abs(instr(evidence_window,'이전')-instr(evidence_window,'부인'))<=14)
        OR (instr(evidence_window,'취소')>0 AND abs(instr(evidence_window,'이전')-instr(evidence_window,'취소'))<=14)
        OR (instr(evidence_window,'무산')>0 AND abs(instr(evidence_window,'이전')-instr(evidence_window,'무산'))<=14)
        OR (instr(evidence_window,'철회')>0 AND abs(instr(evidence_window,'이전')-instr(evidence_window,'철회'))<=14)
      )
    )
    AND instr(evidence_window,'구사옥')=0
    AND instr(evidence_window,'옛 사옥')=0
), location_evidence AS (
  SELECT s.*,
    CASE evidence_type WHEN 'RELOCATION' THEN '이전 관련 문구'
      WHEN 'STAY' THEN '잔류·갱신 문구'
      WHEN 'NEW_LEASE' THEN '임차·입주 문구'
      ELSE '신설·확장 문구' END AS evidence_label,
    CASE WHEN classification_basis='MANAGED_TAXONOMY'
      THEN '관리형 ' || source_category || ' 분류 문서에서 회사명과 ‘' ||
           coalesce(matched_phrase,CASE evidence_type WHEN 'RELOCATION' THEN '이전' WHEN 'STAY' THEN '잔류·갱신' WHEN 'NEW_LEASE' THEN '임차·입주' ELSE '신설·확장' END) || '’ 표현이 같은 문맥에 등장'
      ELSE '과거 자동분류 문서에서 회사명과 ‘' ||
           coalesce(matched_phrase,CASE evidence_type WHEN 'RELOCATION' THEN '이전' WHEN 'STAY' THEN '잔류·갱신' WHEN 'NEW_LEASE' THEN '임차·입주' ELSE '신설·확장' END) || '’ 표현이 같은 문맥에 등장 · 행위주체 검토 전'
      END AS evidence_reason
  FROM staged_location_evidence s
), managed_location_document_count AS (
  SELECT count(*) AS count FROM managed_location_categories
)`;

const locationEvidenceJsonSql = `json_object(
  'documentId',document_id,'evidenceType',evidence_type,'wordingStage',wording_stage,
  'evidenceLabel',evidence_label,'title',title,'matchedPhrase',matched_phrase,
  'evidenceExcerpt',evidence_excerpt,'evidenceReason',evidence_reason,
  'sourceCategory',source_category,'classificationBasis',classification_basis,
  'classificationReviewStatus',classification_review_status,
  'publishedAt',published_at,'publisher',publisher,'href',href,
  'mentionStatus',mention_status,'confidence',confidence
)`;

const companyListSql = `
WITH universe AS (
  SELECT organization_id,organization_name,industry_name,overall_rank,industry_rank,
         market_cap_decimal,universe_code,snapshot_date
  FROM v_company_universe_current
), selected_universe_candidates AS (
  SELECT u.*,
         row_number() OVER (
           PARTITION BY organization_id
           ORDER BY (market_cap_decimal IS NULL),CAST(market_cap_decimal AS REAL) DESC,
                    (snapshot_date IS NULL),snapshot_date DESC,universe_code
         ) AS market_cap_rank
  FROM universe u
  WHERE (?1='OVERALL' AND universe_code='KRX_MARKET_CAP_TOP_50')
     OR (?1='INDUSTRY' AND universe_code='KRX_INDUSTRY_MARKET_CAP_TOP_10')
     OR (?1='TENANT_SIGNALS')
), selected_universe AS (
  SELECT organization_id,max(organization_name) AS organization_name,
         max(industry_name) AS industry_name,min(overall_rank) AS overall_rank,
         min(industry_rank) AS industry_rank,
         max(CASE WHEN market_cap_rank=1 THEN market_cap_decimal END) AS market_cap,
         max(snapshot_date) AS snapshot_date
  FROM selected_universe_candidates
  GROUP BY organization_id
), location_subjects AS (
  SELECT organization_id,organization_name FROM selected_universe
), ${locationEvidenceCtes},
evidence_counts AS (
  SELECT organization_id,count(DISTINCT document_id) AS document_count,
         count(DISTINCT coalesce(nullif(publisher,''),document_id)) AS publisher_count
  FROM location_evidence GROUP BY organization_id
), evidence_ranked AS (
  SELECT e.*,row_number() OVER (
    PARTITION BY organization_id
    ORDER BY (published_at IS NULL),published_at DESC,
      CASE wording_stage WHEN 'CONFIRMED_WORDING' THEN 1 WHEN 'IN_PROGRESS_WORDING' THEN 2
        WHEN 'EXPLORING_WORDING' THEN 3 ELSE 4 END,
      (confidence IS NULL),confidence DESC,document_id
  ) AS row_no
  FROM location_evidence e
), primary_evidence AS (
  SELECT * FROM evidence_ranked WHERE row_no=1
), occupancy_counts AS (
  SELECT organization_id,count(*) AS count
  FROM organization_property_occupancies
  WHERE tenure_type='TENANT' AND occupancy_status IN ('CONTRACTED','OCCUPIED')
    AND review_status='APPROVED' AND verification_status='VERIFIED'
    AND source_claim_id IS NOT NULL
    AND (asset_id IS NOT NULL OR project_id IS NOT NULL OR region_id IS NOT NULL)
  GROUP BY organization_id
), event_counts AS (
  SELECT organization_id,count(DISTINCT event_id) AS count
  FROM event_participants GROUP BY organization_id
), asset_counts AS (
  SELECT ep.organization_id,count(DISTINCT ea.asset_id) AS count
  FROM event_participants ep
  JOIN event_assets ea ON ea.event_id=ep.event_id
  GROUP BY ep.organization_id
), company_rows AS (
  SELECT u.organization_id,u.organization_name,o.stock_code,u.industry_name,
         u.market_cap AS market_cap_decimal,u.overall_rank,u.industry_rank,
         coalesce(occ.count,0) AS confirmed_occupancy_count,
         coalesce(ev.count,0) AS canonical_event_count,
         coalesce(ast.count,0) AS related_asset_count,
         coalesce(cnt.document_count,0) AS location_evidence_document_count,
         coalesce(cnt.publisher_count,0) AS location_evidence_publisher_count,
         pe.document_id AS evidence_document_id,pe.evidence_type,pe.wording_stage,
         pe.evidence_label,pe.title AS evidence_title,pe.matched_phrase,
         pe.evidence_excerpt,pe.evidence_reason,pe.source_category,
         pe.classification_basis,pe.classification_review_status,
         pe.published_at AS evidence_published_at,pe.publisher AS evidence_publisher,
         pe.href AS evidence_href,pe.mention_status,pe.confidence AS evidence_confidence,
         u.snapshot_date
  FROM selected_universe u
  JOIN organizations o ON o.organization_id=u.organization_id
  LEFT JOIN occupancy_counts occ ON occ.organization_id=u.organization_id
  LEFT JOIN event_counts ev ON ev.organization_id=u.organization_id
  LEFT JOIN asset_counts ast ON ast.organization_id=u.organization_id
  LEFT JOIN evidence_counts cnt ON cnt.organization_id=u.organization_id
  LEFT JOIN primary_evidence pe ON pe.organization_id=u.organization_id
), filtered AS (
  SELECT * FROM company_rows
  WHERE (?2='' OR industry_name=?2)
    AND (?3='' OR lower(organization_name) LIKE '%' || lower(?3) || '%'
         OR lower(coalesce(stock_code,'')) LIKE '%' || lower(?3) || '%')
    AND (?1<>'TENANT_SIGNALS' OR confirmed_occupancy_count>0 OR location_evidence_document_count>0)
), industries AS (
  SELECT industry_name AS name,count(DISTINCT organization_id) AS count
  FROM universe WHERE universe_code='KRX_INDUSTRY_MARKET_CAP_TOP_10'
  GROUP BY industry_name
)
SELECT json_object(
  'snapshotDate',(SELECT max(snapshot_date) FROM universe),
  'items',json((SELECT json_group_array(json_object(
    'organizationId',organization_id,'name',organization_name,'stockCode',stock_code,
    'industry',industry_name,'marketCap',market_cap_decimal,'overallRank',overall_rank,
    'industryRank',industry_rank,'confirmedOccupancyCount',confirmed_occupancy_count,
    'canonicalEventCount',canonical_event_count,'relatedAssetCount',related_asset_count,
    'locationEvidenceDocumentCount',location_evidence_document_count,
    'locationEvidencePublisherCount',location_evidence_publisher_count,
    'primaryLocationEvidence',CASE WHEN evidence_document_id IS NULL THEN NULL ELSE json_object(
      'documentId',evidence_document_id,'evidenceType',evidence_type,'wordingStage',wording_stage,
      'evidenceLabel',evidence_label,'title',evidence_title,'matchedPhrase',matched_phrase,
      'evidenceExcerpt',evidence_excerpt,'evidenceReason',evidence_reason,
      'sourceCategory',source_category,'classificationBasis',classification_basis,
      'classificationReviewStatus',classification_review_status,
      'publishedAt',evidence_published_at,'publisher',evidence_publisher,'href',evidence_href,
      'mentionStatus',mention_status,'confidence',evidence_confidence
    ) END
  )) FROM (SELECT * FROM filtered ORDER BY
    CASE WHEN ?1='TENANT_SIGNALS' THEN (evidence_published_at IS NULL) ELSE 0 END,
    CASE WHEN ?1='TENANT_SIGNALS' THEN evidence_published_at END DESC,
    (market_cap_decimal IS NULL),CAST(market_cap_decimal AS REAL) DESC,organization_name,organization_id
    LIMIT ?4) ordered_items)),
  'industries',json((SELECT json_group_array(json_object('name',name,'count',count))
    FROM (SELECT * FROM industries ORDER BY name) ordered_industries)),
  'coverage',json_object(
    'verifiedOccupancies',(SELECT coalesce(sum(count),0) FROM occupancy_counts),
    'companiesWithLocationEvidence',(SELECT count(*) FROM company_rows WHERE location_evidence_document_count>0),
    'managedLocationDocuments',(SELECT count FROM managed_location_document_count),
    'signalNote','확정 점유는 승인·검증된 관계만 표시합니다. 나머지는 회사명과 입지 행동 표현이 같은 문맥에 등장한 검토 전 문서이며 독립된 이전 사건 수가 아닙니다.'
  )
) AS payload`;

const companyDetailSql = `
WITH target AS (
  SELECT o.organization_id,o.canonical_name,o.organization_type,o.stock_code
  FROM organizations o WHERE o.organization_id=?1
), universe AS (
  SELECT industry_name,market_cap_decimal,overall_rank
  FROM v_company_universe_current WHERE organization_id=?1
  ORDER BY (overall_rank IS NULL),overall_rank,(industry_rank IS NULL),industry_rank LIMIT 1
), location_subjects AS (
  SELECT organization_id,canonical_name AS organization_name FROM target
), ${locationEvidenceCtes},
company_events AS (
  SELECT DISTINCT e.event_id,e.canonical_title AS title,ec.name_ko AS category,
         ep.role_code,e.current_stage_code AS stage,e.event_date_start AS date,
         e.lifecycle_status AS status,e.verification_level AS verification
  FROM event_participants ep
  JOIN events e ON e.event_id=ep.event_id
  LEFT JOIN event_categories ec ON ec.event_category_id=e.primary_category_id
  WHERE ep.organization_id=?1
), company_assets AS (
  SELECT DISTINCT a.asset_id,a.canonical_name AS name,ac.name_ko AS asset_class,
         coalesce(a.road_address,a.jibun_address) AS address
  FROM event_participants ep
  JOIN event_assets ea ON ea.event_id=ep.event_id
  JOIN assets a ON a.asset_id=ea.asset_id
  LEFT JOIN asset_classes ac ON ac.asset_class_id=a.asset_class_id
  WHERE ep.organization_id=?1
  UNION
  SELECT DISTINCT a.asset_id,a.canonical_name,ac.name_ko,coalesce(a.road_address,a.jibun_address)
  FROM organization_property_occupancies op
  JOIN assets a ON a.asset_id=op.asset_id
  LEFT JOIN asset_classes ac ON ac.asset_class_id=a.asset_class_id
  WHERE op.organization_id=?1
), occupancies AS (
  SELECT occupancy_id,occupancy_type,tenure_type,occupancy_status,valid_from,valid_to,
         verification_status,review_status,confidence
  FROM organization_property_occupancies
  WHERE organization_id=?1 AND tenure_type='TENANT'
    AND occupancy_status IN ('CONTRACTED','OCCUPIED')
    AND review_status='APPROVED' AND verification_status='VERIFIED'
    AND source_claim_id IS NOT NULL
    AND (asset_id IS NOT NULL OR project_id IS NOT NULL OR region_id IS NOT NULL)
), canonical_doc_candidates AS (
  SELECT sd.document_id,dv.title,sd.document_type,dv.published_at,sd.publisher_name AS publisher,
         sd.canonical_url AS href,r.relation_basis,
         row_number() OVER (
           PARTITION BY sd.document_id
           ORDER BY CASE r.relation_basis WHEN 'CANONICAL_EVENT' THEN 1 WHEN 'RESOLVED_MENTION' THEN 2
                    WHEN 'VERIFIED_CLAIM' THEN 3 ELSE 4 END,
             (r.confidence IS NULL),r.confidence DESC,dv.version_no DESC
         ) AS document_rank
  FROM v_document_entity_relations r
  JOIN document_versions dv ON dv.document_version_id=r.document_version_id
  JOIN source_documents sd ON sd.document_id=dv.document_id
  WHERE r.entity_kind='ORGANIZATION' AND r.entity_id=?1
), canonical_docs AS (
  SELECT document_id,title,document_type,published_at,publisher,href,relation_basis
  FROM canonical_doc_candidates
  WHERE document_rank=1
), location_docs AS (
  SELECT e.document_id,e.title,e.document_type,e.published_at,e.publisher,e.href,
         'EXACT_NAME_SIGNAL' AS relation_basis
  FROM location_evidence e
  WHERE NOT EXISTS (SELECT 1 FROM canonical_docs c WHERE c.document_id=e.document_id)
), docs AS (
  SELECT * FROM canonical_docs UNION ALL SELECT * FROM location_docs
)
SELECT json_object(
  'organization',(SELECT json_object(
    'organizationId',t.organization_id,'name',t.canonical_name,'organizationType',t.organization_type,
    'stockCode',t.stock_code,'industry',u.industry_name,'marketCap',u.market_cap_decimal,'overallRank',u.overall_rank
  ) FROM target t LEFT JOIN universe u ON 1=1),
  'counts',json_object(
    'events',(SELECT count(*) FROM company_events),'assets',(SELECT count(*) FROM company_assets),
    'documents',(SELECT count(*) FROM docs),'occupancies',(SELECT count(*) FROM occupancies),
    'locationEvidence',(SELECT count(DISTINCT document_id) FROM location_evidence)
  ),
  'events',json((SELECT json_group_array(json_object(
    'event_id',event_id,'title',title,'category',category,'role_code',role_code,
    'stage',stage,'date',date,'status',status,'verification',verification
  )) FROM (SELECT * FROM company_events ORDER BY (date IS NULL),date DESC,event_id) ordered_events)),
  'assets',json((SELECT json_group_array(json_object(
    'asset_id',asset_id,'name',name,'asset_class',asset_class,'address',address
  )) FROM (SELECT * FROM company_assets ORDER BY name,asset_id) ordered_assets)),
  'documents',json((SELECT json_group_array(json_object(
    'documentId',document_id,'title',title,'documentType',document_type,'publishedAt',published_at,
    'publisher',publisher,'href',href,'relationBasis',relation_basis
  )) FROM (SELECT * FROM docs ORDER BY (published_at IS NULL),published_at DESC,document_id) ordered_documents)),
  'occupancies',json((SELECT json_group_array(json_object(
    'occupancy_id',occupancy_id,'occupancy_type',occupancy_type,'tenure_type',tenure_type,
    'occupancy_status',occupancy_status,'valid_from',valid_from,'valid_to',valid_to,
    'verification_status',verification_status,'review_status',review_status,'confidence',confidence
  )) FROM (SELECT * FROM occupancies ORDER BY (valid_from IS NULL),valid_from DESC,occupancy_id) ordered_occupancies)),
  'locationEvidence',json((SELECT json_group_array(${locationEvidenceJsonSql})
    FROM (SELECT * FROM location_evidence
      ORDER BY (published_at IS NULL),published_at DESC,document_id) ordered_location_evidence))
) AS payload`;

function parsePayload<T>(value: unknown): T | undefined {
  if (typeof value === "string") {
    try {
      return JSON.parse(value) as T;
    } catch {
      return undefined;
    }
  }
  return value && typeof value === "object" ? value as T : undefined;
}

export async function getCompanies(execute: SqlExecutor, request: CompanyListRequest): Promise<CompanyListResponse> {
  const query = await execute(companyListSql, [request.view, request.industry, request.q, request.limit]);
  const payload = parsePayload<Omit<CompanyListResponse, "request" | "generatedAt" | "database">>(query.rows[0]?.payload);
  if (!payload?.items) throw new Error("Invalid company intelligence response");
  return { request, ...payload, generatedAt: new Date().toISOString(), database: "turso-libsql" };
}

export async function getCompanyDetail(execute: SqlExecutor, organizationId: string): Promise<CompanyDetailResponse> {
  if (!/^[a-zA-Z0-9_-]{1,80}$/.test(organizationId)) throw new Error("Invalid organization id");
  const query = await execute(companyDetailSql, [organizationId]);
  const payload = parsePayload<Omit<CompanyDetailResponse, "generatedAt" | "database">>(query.rows[0]?.payload);
  if (!payload?.organization) throw new Error("Company not found");
  return { ...payload, generatedAt: new Date().toISOString(), database: "turso-libsql" };
}
