import {afterEach,beforeEach,describe,expect,it,vi} from "vitest";
import {NextRequest} from "next/server";
import {createSessionToken,SESSION_COOKIE} from "@/lib/server/auth-session";
const {authMock}=vi.hoisted(()=>({authMock:vi.fn()}));
vi.mock("@/lib/server/db",()=>({executeAuthSql:authMock}));
import {proxy} from "@/proxy";
const SUBJECT_ID="49caafcd-f6c5-4d79-92bd-6f4cd968cf25",SESSION_SECRET="0123456789abcdef0123456789abcdef";
beforeEach(()=>{process.env.DASHBOARD_SESSION_SECRET=SESSION_SECRET;authMock.mockResolvedValue({rows:[{subject_id:SUBJECT_ID}]})});
afterEach(()=>{delete process.env.DASHBOARD_SESSION_SECRET;authMock.mockReset();vi.useRealTimers()});
describe("dashboard proxy",()=>{
 it("redirects pages and returns 401 JSON for unauthenticated APIs",async()=>{const page=await proxy(new NextRequest("https://example.com/"));expect(page.status).toBe(307);expect(page.headers.get("location")).toBe("https://example.com/login");const api=await proxy(new NextRequest("https://example.com/api/index"));expect(api.status).toBe(401)});
 it("caches an approved signed subject for at most 30 seconds",async()=>{vi.useFakeTimers();vi.setSystemTime(new Date("2026-08-21T00:00:00Z"));const token=await createSessionToken(SUBJECT_ID,SESSION_SECRET),request=new NextRequest("https://example.com/api/index",{headers:{Cookie:`${SESSION_COOKIE}=${token}`}});const first=await proxy(request);expect(first.status).toBe(200);expect(first.headers.get("server-timing")).toMatch(/^authz;dur=\d+\.\d$/u);authMock.mockResolvedValue({rows:[]});vi.advanceTimersByTime(29_999);expect((await proxy(request)).status).toBe(200);expect(authMock).toHaveBeenCalledTimes(1);vi.advanceTimersByTime(1);expect((await proxy(request)).status).toBe(401);expect(authMock).toHaveBeenCalledTimes(2)});
 it("fails closed when current authorization cannot be checked",async()=>{const subject="bcecf135-a093-4ced-a83d-02c8603297d2",token=await createSessionToken(subject,SESSION_SECRET);authMock.mockRejectedValueOnce(new Error("db"));const response=await proxy(new NextRequest("https://example.com/api/index",{headers:{Cookie:`${SESSION_COOKIE}=${token}`}}));expect(response.status).toBe(503);expect(await response.text()).not.toContain("db")});
 it("rejects an expired signed session without querying authorization",async()=>{const issued=new Date("2026-08-21T00:00:00Z"),token=await createSessionToken(SUBJECT_ID,SESSION_SECRET,issued);vi.useFakeTimers();vi.setSystemTime(new Date("2026-08-21T12:00:00Z"));const response=await proxy(new NextRequest("https://example.com/api/index",{headers:{Cookie:`${SESSION_COOKIE}=${token}`}}));expect(response.status).toBe(401);expect(authMock).not.toHaveBeenCalled()});
});
