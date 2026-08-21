"use client";

import { useEffect, useState } from "react";
import type { EntityDetail } from "@/lib/server/entity-intelligence";
import { viewTemplates } from "@/lib/view-template-registry";

type Props = { kind: "EVENT" | "ASSET"; id: string; fallbackTitle: string; onClose: () => void };

function RelationSection({ title, items }: { title: string; items: Array<{ id: string; title: string; meta: string | null; href?: string | null }> }) {
  return <section className="entity-relation-section"><h3>{title}<b>{items.length}</b></h3>{items.length === 0 ? <p className="empty-relation">연결된 항목이 없습니다.</p> : items.map((item) => <article key={item.id}><strong>{item.title}</strong>{item.meta && <p>{item.meta}</p>}{item.href && <a href={item.href} target="_blank" rel="noreferrer">근거 원문 ↗</a>}</article>)}</section>;
}

function entityNarrative(detail: EntityDetail, kind: "EVENT" | "ASSET"): string {
  const facts = detail.overview.slice(0, 4).map((row) => `${row.label} ${row.value}`).join(" · ");
  if (kind === "EVENT") return `${detail.title} 이벤트의 현재 구조화 정보는 ${facts || "핵심 필드 미연결"}입니다. 관련 자산 ${detail.assets.length}건, 참여 조직 ${detail.organizations.length}건, 기관자금·매각절차 ${(detail.capital?.length ?? 0) + (detail.processes?.length ?? 0)}건, 근거 문서 ${detail.documents.length}건이 연결되어 있습니다.`;
  return `${detail.title} 자산의 현재 구조화 정보는 ${facts || "핵심 필드 미연결"}입니다. 관련 이벤트 ${detail.events.length}건, 관련 회사 ${detail.organizations.length}건, 기관자금·매각절차 ${(detail.capital?.length ?? 0) + (detail.processes?.length ?? 0)}건, 근거 문서 ${detail.documents.length}건이 연결되어 있습니다.`;
}

export function EntityDetailDrawer({ kind, id, fallbackTitle, onClose }: Props) {
  const [detail, setDetail] = useState<EntityDetail | null>(null);
  const [error, setError] = useState(false);
  const template = viewTemplates[kind];

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/entities/${kind.toLowerCase()}/${encodeURIComponent(id)}`, { signal: controller.signal })
      .then((response) => { if (!response.ok) throw new Error(); return response.json() as Promise<EntityDetail>; })
      .then(setDetail).catch((reason: unknown) => { if (!(reason instanceof DOMException && reason.name === "AbortError")) setError(true); });
    return () => controller.abort();
  }, [kind, id]);

  return <div className="drawer-layer" onMouseDown={(event) => event.currentTarget === event.target && onClose()}>
    <section className="detail-drawer entity-detail-drawer" role="dialog" aria-modal="true" aria-label={kind === "EVENT" ? "이벤트 상세" : "자산 상세"}>
      <header className="drawer-header"><div><p className="eyebrow">{template.eyebrow}</p><h2>{detail?.title ?? fallbackTitle}</h2><p>{detail ? `${detail.subtitle ?? template.title} · ${template.purpose}` : `${template.title} 관계정보 조회 중`}</p></div><button type="button" className="icon-button" aria-label="상세 닫기" onClick={onClose}>×</button></header>
      {!detail && !error && <div className="state-block"><span className="spinner"/><strong>관계정보 조회 중</strong></div>}
      {error && <div className="state-block error-state"><strong>상세정보를 불러오지 못했습니다.</strong></div>}
      {detail && <div className="drawer-body entity-detail-body">
        <section className="domain-narrative"><p className="eyebrow">STRUCTURED SUMMARY</p><h3>{kind === "EVENT" ? "이벤트 핵심 설명" : "자산 핵심 설명"}</h3><p>{entityNarrative(detail, kind)}</p></section>
        <section className="entity-overview"><p className="eyebrow">OVERVIEW</p><h3>{template.primarySections[0]}</h3><div>{detail.overview.map((row) => <dl key={row.label}><dt>{row.label}</dt><dd>{row.value}</dd></dl>)}</div></section>
        {kind === "EVENT" && <RelationSection title="관련 자산" items={detail.assets}/>}
        <RelationSection title="관련 이벤트" items={detail.events}/>
        <RelationSection title={kind === "EVENT" ? "참여 조직" : "관련 회사"} items={detail.organizations}/>
        {(detail.projects?.length ?? 0) > 0 && <RelationSection title="관련 프로젝트" items={detail.projects}/>}
        {(detail.capital?.length ?? 0) > 0 && <RelationSection title="기관자금 프로그램" items={detail.capital}/>}
        {(detail.processes?.length ?? 0) > 0 && <RelationSection title="매각 절차" items={detail.processes}/>}
        <RelationSection title="근거 문서" items={detail.documents}/>
      </div>}
    </section>
  </div>;
}
