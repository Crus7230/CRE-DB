"use client";

import type { SearchResult } from "@/lib/search-contract";

type Props = { result: SearchResult; onClose: () => void };

function text(value: unknown, fallback = "없음") {
  return typeof value === "string" && value ? value : fallback;
}

export function ArchivedDetailDrawer({ result, onClose }: Props) {
  const locator = text(result.metadata?.archiveLocator);
  const checksum = text(result.metadata?.archiveSnapshotSha256);
  const originalStatus = text(result.metadata?.originalStatus, "보관됨");
  return <div className="drawer-layer" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
    <section className="detail-drawer entity-detail-drawer" role="dialog" aria-modal="true" aria-label="로컬 보관 상세">
      <header className="drawer-header"><div><p className="eyebrow">LOCAL FULL ARCHIVE</p><h2>{result.title}</h2><p>Supabase compact index · 상세 원본은 로컬 authority에 보관</p></div><button type="button" className="icon-button" aria-label="상세 닫기" onClick={onClose}>×</button></header>
      <div className="drawer-body entity-detail-body">
        <section className="domain-narrative"><p className="eyebrow">ARCHIVE STATUS</p><h3>비활성 상세 보관</h3><p>이 항목은 현재 active serving 범위에서 종료됐습니다. 검색용 최소 메타데이터는 Supabase에 남고, 전체 evidence와 lineage는 checksum으로 고정된 로컬 SQLite snapshot에서 복원합니다.</p></section>
        <section className="entity-overview"><p className="eyebrow">COMPACT INDEX</p><h3>보관 메타데이터</h3><div>
          <dl><dt>원래 상태</dt><dd>{originalStatus}</dd></dl>
          <dl><dt>유형</dt><dd>{result.kind}</dd></dl>
          <dl><dt>카테고리</dt><dd>{result.categoryLabel ?? result.category ?? "미분류"}</dd></dl>
          <dl><dt>기준일</dt><dd>{result.date?.slice(0, 10) ?? "날짜 미상"}</dd></dl>
          <dl><dt>출처</dt><dd>{result.source ?? "출처 미상"}</dd></dl>
          <dl><dt>Archive locator</dt><dd>{locator}</dd></dl>
          <dl><dt>Snapshot SHA-256</dt><dd>{checksum}</dd></dl>
        </div></section>
        {result.summary && <section className="entity-relation-section"><h3>요약</h3><p>{result.summary}</p></section>}
        {result.href && <section className="entity-relation-section"><h3>원문</h3><a href={result.href} target="_blank" rel="noreferrer">근거 원문 ↗</a></section>}
      </div>
    </section>
  </div>;
}
