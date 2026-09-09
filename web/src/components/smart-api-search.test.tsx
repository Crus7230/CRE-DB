import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SmartApiSearch } from "@/components/smart-api-search";

const jsonResponse = (value: unknown, status = 200) => new Response(JSON.stringify(value), {
  status,
  headers: { "Content-Type": "application/json" },
});

const candidateResponse = {
  query: "000660",
  kind: "auto",
  stage: "candidates",
  candidates: [{ id: "signed-company-1", kind: "company", title: "SK하이닉스", subtitle: "000660 · 반도체 제조업", sourceLabel: "DART" }],
  cards: [],
  sources: [
    { id: "dart", label: "DART", status: "ok", message: "기업 후보 확인", checkedAt: "2026-09-08T02:00:00Z", asOf: "2026-09-07" },
    { id: "krx", label: "KRX", status: "empty", message: "추가 자료 없음" },
    { id: "vworld", label: "VWorld", status: "unconfigured", message: "API 키 미설정" },
    { id: "public", label: "공공데이터포털", status: "error", message: "출처 오류" },
    { id: "slow", label: "지연 출처", status: "timeout", message: "응답 제한시간 초과" },
  ],
  queriedAt: "2026-09-08T02:00:01Z",
  cacheHit: false,
};

const detailResponse = {
  query: "000660",
  kind: "company",
  stage: "detail",
  candidates: [],
  cards: [{
    id: "dart-company",
    title: "SK하이닉스",
    sourceLabel: "DART 기업개황",
    subtitle: "유가증권시장 · 000660",
    fields: [{ label: "대표자", value: "곽노정" }, { label: "본점", value: "경기도 이천시" }],
    links: [{ label: "공식 원문", url: "https://dart.fss.or.kr/" }, { label: "차단 링크", url: "javascript:alert(1)" }],
    note: "공시 기준 기업정보",
    asOf: "2026-09-07",
  }],
  sources: [{ id: "dart", label: "DART", status: "ok", checkedAt: "2026-09-08T02:00:02Z", asOf: "2026-09-07" }],
  queriedAt: "2026-09-08T02:00:02Z",
  cacheHit: true,
  rawSecret: { providerPayload: "절대 노출 금지" },
};

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SmartApiSearch", () => {
  it("does not call the API while typing or choosing an example and submits only on command", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>(async () => jsonResponse(candidateResponse));
    vi.stubGlobal("fetch", fetchMock);
    render(<SmartApiSearch/>);

    const input = screen.getByRole("textbox", { name: "주소·회사명·종목코드" });
    await user.type(input, "SK하이닉스");
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "000660" }));
    expect(input).toHaveValue("000660");
    expect(fetchMock).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "조회" }));
    expect(await screen.findByText("조회 대상을 선택하세요.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, init] = fetchMock.mock.calls[0];
    expect(JSON.parse(String(init?.body))).toEqual({ query: "000660", kind: "auto" });
  });

  it("moves from a selected candidate to visual cards and separates response time from data as-of", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse(candidateResponse))
      .mockResolvedValueOnce(jsonResponse(detailResponse));
    vi.stubGlobal("fetch", fetchMock);
    render(<SmartApiSearch/>);

    await user.click(screen.getByRole("button", { name: "000660" }));
    await user.click(screen.getByRole("button", { name: "조회" }));
    const candidate = (await screen.findByText("SK하이닉스", { selector: "strong" })).closest("button") as HTMLButtonElement;

    const dartSource = screen.getByText("DART", { selector: "strong" }).closest("article") as HTMLElement;
    expect(within(dartSource).getByText("정상")).toBeInTheDocument();
    expect(screen.getByText("자료 없음")).toBeInTheDocument();
    expect(screen.getByText("연결·승인 필요")).toBeInTheDocument();
    expect(screen.getByText("오류")).toBeInTheDocument();
    expect(screen.getByText("시간 초과")).toBeInTheDocument();

    await user.click(candidate);
    expect(await screen.findByRole("heading", { name: "SK하이닉스", level: 3 })).toBeInTheDocument();
    expect(screen.getByText(/요청 완료/)).toBeInTheDocument();
    expect(screen.getAllByText("자료 기준 2026-09-07").length).toBeGreaterThan(0);
    expect(screen.getByText("대표자").nextElementSibling).toHaveTextContent("곽노정");
    expect(screen.getByRole("link", { name: /공식 원문/ })).toHaveAttribute("href", "https://dart.fss.or.kr/");
    expect(screen.queryByRole("link", { name: /차단 링크/ })).not.toBeInTheDocument();
    expect(screen.queryByText("절대 노출 금지")).not.toBeInTheDocument();
    const [, detailInit] = fetchMock.mock.calls[1];
    expect(JSON.parse(String(detailInit?.body))).toEqual({ query: "000660", kind: "company", selection: "signed-company-1" });

    await user.clear(screen.getByRole("textbox", { name: "주소·회사명·종목코드" }));
    await user.type(screen.getByRole("textbox", { name: "주소·회사명·종목코드" }), "035420");
    expect(screen.queryByRole("heading", { name: "SK하이닉스", level: 3 })).not.toBeInTheDocument();
    expect(screen.getByText("검색어를 입력하고 조회를 실행하세요.")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("aborts an obsolete request and ignores a late response during rapid re-search", async () => {
    const user = userEvent.setup();
    let resolveFirst: ((response: Response) => void) | undefined;
    const secondResponse = { ...candidateResponse, query: "035420", candidates: [{ ...candidateResponse.candidates[0], id: "naver", title: "NAVER", subtitle: "035420 · 정보서비스" }] };
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)) as { query: string };
      if (body.query === "000660") return new Promise<Response>((resolve) => { resolveFirst = resolve; });
      return Promise.resolve(jsonResponse(secondResponse));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SmartApiSearch/>);

    const input = screen.getByRole("textbox", { name: "주소·회사명·종목코드" });
    await user.type(input, "000660");
    await user.click(screen.getByRole("button", { name: "조회" }));
    await screen.findByText("연결된 출처를 확인하고 있습니다.");

    await user.clear(input);
    await user.type(input, "035420");
    await user.click(screen.getByRole("button", { name: "조회" }));
    expect(await screen.findByRole("button", { name: /NAVER/ })).toBeInTheDocument();

    resolveFirst?.(jsonResponse(candidateResponse));
    await waitFor(() => expect(screen.getByRole("button", { name: /NAVER/ })).toBeInTheDocument());
    expect(screen.queryByText("SK하이닉스", { selector: "strong" })).not.toBeInTheDocument();
    expect((fetchMock.mock.calls[0][1]?.signal as AbortSignal).aborted).toBe(true);
  });

  it("shows an honest empty response and keeps the query available for editing", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({
      ...candidateResponse,
      query: "없는 주소 999",
      kind: "address",
      stage: "empty",
      candidates: [],
      sources: [{ id: "vworld", label: "VWorld", status: "empty", checkedAt: "2026-09-08T02:00:00Z" }],
      message: "표준주소 후보를 찾지 못했습니다.",
    })));
    render(<SmartApiSearch/>);

    const input = screen.getByRole("textbox", { name: "주소·회사명·종목코드" });
    await user.type(input, "없는 주소 999");
    await user.click(screen.getByRole("button", { name: "주소" }));
    await user.click(screen.getByRole("button", { name: "조회" }));
    expect(await screen.findByText("일치하는 자료가 없습니다.")).toBeInTheDocument();
    expect(screen.getByText("표준주소 후보를 찾지 못했습니다.")).toBeInTheDocument();
    expect(input).toHaveValue("없는 주소 999");
  });

  it("shows the protected route's safe error and lets the user cancel a slow request", async () => {
    const user = userEvent.setup();
    const fetchMock = vi.fn<typeof fetch>()
      .mockResolvedValueOnce(jsonResponse({ error: "로그인 후 조회해 주세요." }, 401))
      .mockImplementationOnce(() => new Promise<Response>(() => undefined));
    vi.stubGlobal("fetch", fetchMock);
    render(<SmartApiSearch/>);

    const input = screen.getByRole("textbox", { name: "주소·회사명·종목코드" });
    await user.type(input, "000660");
    await user.click(screen.getByRole("button", { name: "조회" }));
    expect(await screen.findByText("로그인 후 조회해 주세요.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /다시 조회/ }));
    expect(await screen.findByRole("button", { name: "취소" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "취소" }));
    expect(screen.getByText("검색어를 입력하고 조회를 실행하세요.")).toBeInTheDocument();
    expect((fetchMock.mock.calls[1][1]?.signal as AbortSignal).aborted).toBe(true);
  });
});
