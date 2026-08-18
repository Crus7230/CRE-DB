import type { DocumentDetail } from "@/lib/server/document-intelligence";

type ApiRecord = Record<string, unknown>;

function text(value: unknown) { return value == null || value === "" ? null : String(value); }
function number(value: unknown) { const parsed = Number(String(value ?? "").replaceAll(",", "")); return Number.isFinite(parsed) ? parsed : null; }
function amountLabel(value: unknown) {
  const manwon = number(value);
  if (manwon == null) return "금액 미상";
  if (manwon >= 10_000) return `${(manwon / 10_000).toLocaleString("ko-KR", { maximumFractionDigits: 2 })}억원`;
  return `${manwon.toLocaleString("ko-KR")}만원`;
}
function band(area: number | null) { return area == null ? "UNKNOWN" : area <= 1000 ? "EXCLUDED" : area <= 3300 ? "REVIEW" : "KEEP"; }
const bandLabels = { EXCLUDED: "범위 제외 ≤1,000㎡", REVIEW: "검토 대상 1,000~3,300㎡", KEEP: "유지 대상 >3,300㎡", UNKNOWN: "면적 확인 필요" } as const;

export function TransactionCard({ metadata }: { metadata: Record<string, unknown> }) {
  const record = (metadata.apiRecord ?? {}) as ApiRecord;
  const area = number(record.buildingAr);
  const amount = number(record.dealAmount);
  const unitPrice = area && amount != null ? amount / area : null;
  const address = [record.sggNm, record.umdNm, record.jibun].map(text).filter(Boolean).join(" ");
  const currentBand = band(area);
  return <div className="transaction-card-template">
    <div className="transaction-card-head"><strong>{amountLabel(record.dealAmount)}</strong><span className={`screening-band ${currentBand.toLowerCase()}`}>{bandLabels[currentBand]}</span></div>
    <h3>{address || "주소 미상"}</h3>
    <div className="transaction-card-metrics">
      <span><small>거래일</small>{text(metadata.dealDate) ?? "미상"}</span>
      <span><small>건물면적</small>{area == null ? "미상" : `${area.toLocaleString("ko-KR")}㎡`}</span>
      <span><small>㎡당 가격</small>{unitPrice == null ? "미상" : `${Math.round(unitPrice).toLocaleString("ko-KR")}만원`}</span>
      <span><small>용도</small>{text(record.buildingUse) ?? "미상"}</span>
    </div>
    <p>{[record.buildingType, record.dealingGbn, record.buyerGbn && `매수 ${record.buyerGbn}`, record.slerGbn && `매도 ${record.slerGbn}`].map(text).filter(Boolean).join(" · ")}</p>
  </div>;
}

export function TransactionDetail({ transaction }: { transaction: NonNullable<DocumentDetail["transaction"]> }) {
  const area = number(transaction.buildingAr);
  const amount = number(transaction.dealAmount);
  const unitPrice = area && amount != null ? amount / area : null;
  const fields = [
    ["거래일", transaction.dealDate], ["거래금액", amountLabel(transaction.dealAmount)],
    ["건물면적", area == null ? null : `${area.toLocaleString("ko-KR")}㎡`],
    ["토지면적", transaction.plottageAr ? `${number(transaction.plottageAr)?.toLocaleString("ko-KR")}㎡` : null],
    ["㎡당 가격", unitPrice == null ? null : `${Math.round(unitPrice).toLocaleString("ko-KR")}만원/㎡`],
    ["건물용도", transaction.buildingUse], ["건물유형", transaction.buildingType],
    ["준공연도", transaction.buildYear], ["층", transaction.floor], ["토지이용", transaction.landUse],
    ["거래방식", transaction.dealingType], ["매수자", transaction.buyerType], ["매도자", transaction.sellerType],
    ["지분거래", transaction.shareType], ["중복 순번", String(transaction.duplicateOccurrence)],
  ].filter((item) => item[1]);
  return <section className="knowledge-section transaction-detail-template">
    <p className="eyebrow">TRANSACTION</p>
    <div className="transaction-detail-head"><div><h3>{transaction.address || "주소 미상"}</h3><strong>{amountLabel(transaction.dealAmount)}</strong></div><span className={`screening-band ${transaction.screeningBand.toLowerCase()}`}>{bandLabels[transaction.screeningBand]}</span></div>
    <div className="transaction-fields">{fields.map(([label,value]) => <dl key={label}><dt>{label}</dt><dd>{value}</dd></dl>)}</div>
    {transaction.cancelDate && <p className="transaction-warning">해제 신고일 {transaction.cancelDate} — 해제 여부 확인 필요</p>}
    <p className="transaction-note">검토 기준은 개별 건물면적 기준입니다. 동일 주소·일자·금액 거래군의 합산면적이 3,300㎡를 초과하는지는 별도 거래군 검토가 필요합니다.</p>
  </section>;
}
