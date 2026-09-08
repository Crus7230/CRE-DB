import {beforeEach,describe,expect,it,vi} from "vitest";
const {executeMock,cacheAuthorityMock}=vi.hoisted(()=>({executeMock:vi.fn(),cacheAuthorityMock:vi.fn()}));
vi.mock("@/lib/server/db",()=>({
  executeMarketSql:executeMock,
  getMarketCacheAuthorityNamespace:cacheAuthorityMock,
}));
import {GET} from "@/app/api/operations/timeline/route";
const payload={generatedAt:"2026-08-23T00:00:00Z",windowDays:90,publicationKnownCount:1,publicationUnknownCount:0,archivedDocumentExcludedCount:0,series:[]};
beforeEach(()=>{
  executeMock.mockReset().mockResolvedValue({rows:[{payload}]});
  cacheAuthorityMock.mockReset().mockReturnValue("url-test-authority");
});
describe("GET /api/operations/timeline",()=>{
 it("rejects unsupported windows instead of silently falling back",async()=>{const response=await GET(new Request("https://example.com/api/operations/timeline?windowDays=31"));expect(response.status).toBe(400);expect(response.headers.get("cache-control")).toBe("no-store");expect(executeMock).not.toHaveBeenCalled()});
 it("accepts a supported window",async()=>{const response=await GET(new Request("https://example.com/api/operations/timeline?windowDays=90"));expect(response.status).toBe(200);expect(executeMock.mock.calls[0][1]).toEqual([90])});
});
