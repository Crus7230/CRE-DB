import {beforeEach,describe,expect,it,vi} from "vitest";
const {timelineMock}=vi.hoisted(()=>({timelineMock:vi.fn()}));
vi.mock("@/lib/server/market-data-cache",()=>({getCachedOperationsTimeline:timelineMock}));
import {GET} from "@/app/api/operations/timeline/route";
const payload={generatedAt:"2026-08-23T00:00:00Z",windowDays:90,publicationKnownCount:1,publicationUnknownCount:0,archivedDocumentExcludedCount:0,series:[]};
beforeEach(()=>{
  timelineMock.mockReset().mockResolvedValue(payload);
});
describe("GET /api/operations/timeline",()=>{
 it("rejects unsupported windows instead of silently falling back",async()=>{const response=await GET(new Request("https://example.com/api/operations/timeline?windowDays=31"));expect(response.status).toBe(400);expect(response.headers.get("cache-control")).toBe("no-store");expect(timelineMock).not.toHaveBeenCalled()});
 it("accepts a supported window",async()=>{const response=await GET(new Request("https://example.com/api/operations/timeline?windowDays=90"));expect(response.status).toBe(200);expect(timelineMock).toHaveBeenCalledWith(90)});
});
