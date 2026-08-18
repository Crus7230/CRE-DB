export type ViewTemplateKey =
  | "ARTICLE" | "DISCLOSURE" | "OFFICIAL_NOTICE" | "TRANSACTION"
  | "EVENT" | "ASSET" | "COMPANY" | "INSTITUTIONAL_CAPITAL" | "SALE_PROCESS";

export type ViewTemplate = {
  key: ViewTemplateKey;
  eyebrow: string;
  title: string;
  purpose: string;
  primarySections: string[];
  sourceLabel: string;
};

export const viewTemplates: Record<ViewTemplateKey, ViewTemplate> = {
  ARTICLE: { key: "ARTICLE", eyebrow: "ARTICLE INSPECT", title: "기사·시장문서", purpose: "본문을 요약하고 키워드·회사·자산·이벤트로 연결", primarySections: ["원문 기반 요약", "추출 키워드", "연결 이벤트", "원문 발췌"], sourceLabel: "원문 열기" },
  DISCLOSURE: { key: "DISCLOSURE", eyebrow: "DISCLOSURE INSPECT", title: "기업공시", purpose: "공시 핵심내용과 저장 본문·회사·거래 관계를 검증", primarySections: ["공시 핵심내용", "추출 키워드", "연결 이벤트", "저장 공시본문"], sourceLabel: "공시 원문" },
  OFFICIAL_NOTICE: { key: "OFFICIAL_NOTICE", eyebrow: "NOTICE INSPECT", title: "공고·입찰문서", purpose: "공고기관·접수기한·선정절차·근거를 구조화", primarySections: ["공고 핵심내용", "절차·기한", "연결 이벤트", "원문 발췌"], sourceLabel: "공고 원문" },
  TRANSACTION: { key: "TRANSACTION", eyebrow: "TRANSACTION INSPECT", title: "실거래 원자료", purpose: "금액·면적·단가·당사자·검토구간을 비교", primarySections: ["거래 개요", "가격·면적", "당사자·거래방식", "원천 API"], sourceLabel: "원천 API" },
  EVENT: { key: "EVENT", eyebrow: "EVENT INSPECT", title: "시장 이벤트", purpose: "단계·일자·자산·참여자·근거문서를 한 흐름으로 검증", primarySections: ["이벤트 개요", "관련 자산", "참여 조직", "근거 문서"], sourceLabel: "근거문서" },
  ASSET: { key: "ASSET", eyebrow: "ASSET INSPECT", title: "자산", purpose: "입지·자산유형·관련 이벤트·참여회사·문서를 연결", primarySections: ["자산 개요", "관련 이벤트", "관련 회사", "근거 문서"], sourceLabel: "근거문서" },
  COMPANY: { key: "COMPANY", eyebrow: "COMPANY 360", title: "회사", purpose: "시가총액·업종·이벤트·자산·문서·점유관계를 통합", primarySections: ["회사 개요", "이벤트", "자산", "문서·점유"], sourceLabel: "근거문서" },
  INSTITUTIONAL_CAPITAL: { key: "INSTITUTIONAL_CAPITAL", eyebrow: "CAPITAL INSPECT", title: "기관자금", purpose: "LP→프로그램→금액 basis→선정→집행→근거를 추적", primarySections: ["Mandate", "금액·basis", "선정", "집행·근거"], sourceLabel: "근거문서" },
  SALE_PROCESS: { key: "SALE_PROCESS", eyebrow: "SALE PROCESS", title: "매각절차", purpose: "일정·입찰라운드·후보·결정·자금조달·근거를 추적", primarySections: ["프로세스 개요", "마일스톤", "입찰·결정", "자금조달·근거"], sourceLabel: "근거문서" },
};

export function documentTemplateKey(documentType: string, hasTransaction: boolean): ViewTemplateKey {
  if (hasTransaction || documentType === "API_RECORD") return "TRANSACTION";
  if (["DISCLOSURE", "OFFICIAL_FILING"].includes(documentType)) return "DISCLOSURE";
  if (["BID_NOTICE", "NOTICE", "PRESS_RELEASE"].includes(documentType)) return "OFFICIAL_NOTICE";
  return "ARTICLE";
}
