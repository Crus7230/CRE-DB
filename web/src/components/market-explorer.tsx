"use client";

import { type KeyboardEvent, useRef, useState } from "react";
import { BarChart3, Building2, Landmark, Newspaper, Percent } from "lucide-react";
import { DailyArticleWorkspace } from "@/components/daily-article-workspace";
import { DocumentDetailDrawer } from "@/components/document-detail-drawer";
import { MacroTimeseriesWorkspace } from "@/components/macro-timeseries-workspace";
import { PermitTimeseriesWorkspace } from "@/components/permit-timeseries-workspace";
import { QuantitativeMarketPulse } from "@/components/quantitative-market-pulse";

type Workspace = "NEWS" | "TIMESERIES";
type TimeseriesView = "TRANSACTIONS" | "RATES" | "PERMITS";

const workspaceTabs = [
  { key: "NEWS" as const, label: "최신기사", description: "분류된 CRE 기사", icon: Newspaper },
  { key: "TIMESERIES" as const, label: "시계열자료", description: "거래·금리·공급 인허가", icon: BarChart3 },
];

const timeseriesTabs = [
  { key: "TRANSACTIONS" as const, label: "거래시장", description: "서울 대형 비주거 신고", icon: Landmark },
  { key: "RATES" as const, label: "금리·거시", description: "한국·미국 공식 금리", icon: Percent },
  { key: "PERMITS" as const, label: "건축 인허가", description: "서울 허가·착공·사용승인", icon: Building2 },
];

function nextTabIndex(event: KeyboardEvent<HTMLButtonElement>, current: number, length: number) {
  if (event.key === "Home") return 0;
  if (event.key === "End") return length - 1;
  if (event.key === "ArrowLeft") return (current - 1 + length) % length;
  if (event.key === "ArrowRight") return (current + 1) % length;
  return null;
}

export function MarketExplorer() {
  const [workspace, setWorkspace] = useState<Workspace>("NEWS");
  const [visitedWorkspaces, setVisitedWorkspaces] = useState<ReadonlySet<Workspace>>(() => new Set(["NEWS"]));
  const [timeseriesView, setTimeseriesView] = useState<TimeseriesView>("TRANSACTIONS");
  const [visitedTimeseries, setVisitedTimeseries] = useState<ReadonlySet<TimeseriesView>>(() => new Set(["TRANSACTIONS"]));
  const [selectedArticle, setSelectedArticle] = useState<{ id: string; title: string } | null>(null);
  const primaryTabRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const seriesTabRefs = useRef<Array<HTMLButtonElement | null>>([]);

  const selectWorkspace = (next: Workspace) => {
    setWorkspace(next);
    setVisitedWorkspaces((current) => new Set(current).add(next));
    setSelectedArticle(null);
  };

  const selectTimeseries = (next: TimeseriesView) => {
    setTimeseriesView(next);
    setVisitedTimeseries((current) => new Set(current).add(next));
  };

  return <main className="cre-dashboard">
    <header className="dashboard-masthead">
      <a className="dashboard-brand" href="#dashboard-content" aria-label="CRE DB 대시보드 본문으로 이동">
        <span className="dashboard-brand-mark" aria-hidden="true">CRE</span>
        <span><strong>CRE DB</strong><small>Market intelligence</small></span>
      </a>

      <nav className="primary-tabs" aria-label="주요 화면" role="tablist">
        {workspaceTabs.map((tab, index) => {
          const Icon = tab.icon;
          const selected = workspace === tab.key;
          return <button
            ref={(node) => { primaryTabRefs.current[index] = node; }}
            id={`workspace-tab-${tab.key.toLowerCase()}`}
            type="button"
            role="tab"
            key={tab.key}
            aria-controls={`workspace-panel-${tab.key.toLowerCase()}`}
            aria-current={selected ? "page" : undefined}
            aria-selected={selected}
            tabIndex={selected ? 0 : -1}
            onClick={() => selectWorkspace(tab.key)}
            onKeyDown={(event) => {
              const next = nextTabIndex(event, index, workspaceTabs.length);
              if (next === null) return;
              event.preventDefault();
              const target = workspaceTabs[next];
              selectWorkspace(target.key);
              primaryTabRefs.current[next]?.focus();
            }}
          >
            <Icon aria-hidden="true" size={17}/>
            <span><strong>{tab.label}</strong><small>{tab.description}</small></span>
          </button>;
        })}
      </nav>

      <div className="masthead-status" aria-label="시간 기준"><span/>KST 기준</div>
    </header>

    <div id="dashboard-content" className="dashboard-content">
      {visitedWorkspaces.has("NEWS") && <section
        id="workspace-panel-news"
        role="tabpanel"
        aria-labelledby="workspace-tab-news"
        hidden={workspace !== "NEWS"}
      >
        <DailyArticleWorkspace onOpenArticle={(id, title) => setSelectedArticle({ id, title })}/>
      </section>}

      {visitedWorkspaces.has("TIMESERIES") && <section
        id="workspace-panel-timeseries"
        role="tabpanel"
        aria-labelledby="workspace-tab-timeseries"
        className="timeseries-workspace"
        hidden={workspace !== "TIMESERIES"}
      >
        <header className="timeseries-commandbar">
          <div className="commandbar-title"><span>OBSERVED DATA</span><strong>시계열자료</strong><small>해석보다 실제 관측값과 범위를 먼저 확인합니다.</small></div>
          <nav className="secondary-tabs" aria-label="시계열 종류" role="tablist">
            {timeseriesTabs.map((tab, index) => {
              const Icon = tab.icon;
              const selected = timeseriesView === tab.key;
              return <button
                ref={(node) => { seriesTabRefs.current[index] = node; }}
                id={`timeseries-tab-${tab.key.toLowerCase()}`}
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`timeseries-panel-${tab.key.toLowerCase()}`}
                tabIndex={selected ? 0 : -1}
                onClick={() => selectTimeseries(tab.key)}
                onKeyDown={(event) => {
                  const next = nextTabIndex(event, index, timeseriesTabs.length);
                  if (next === null) return;
                  event.preventDefault();
                  const target = timeseriesTabs[next];
                  selectTimeseries(target.key);
                  seriesTabRefs.current[next]?.focus();
                }}
              ><Icon aria-hidden="true" size={16}/><span><strong>{tab.label}</strong><small>{tab.description}</small></span></button>;
            })}
          </nav>
        </header>

        {visitedTimeseries.has("TRANSACTIONS") && <div
          id="timeseries-panel-transactions"
          role="tabpanel"
          aria-labelledby="timeseries-tab-transactions"
          hidden={timeseriesView !== "TRANSACTIONS"}
        ><QuantitativeMarketPulse/></div>}
        {visitedTimeseries.has("RATES") && <div
          id="timeseries-panel-rates"
          role="tabpanel"
          aria-labelledby="timeseries-tab-rates"
          hidden={timeseriesView !== "RATES"}
        ><MacroTimeseriesWorkspace/></div>}
        {visitedTimeseries.has("PERMITS") && <div
          id="timeseries-panel-permits"
          role="tabpanel"
          aria-labelledby="timeseries-tab-permits"
          hidden={timeseriesView !== "PERMITS"}
        ><PermitTimeseriesWorkspace/></div>}
      </section>}
    </div>

    {selectedArticle && <DocumentDetailDrawer documentId={selectedArticle.id} fallbackTitle={selectedArticle.title} onClose={() => setSelectedArticle(null)}/>}
  </main>;
}
