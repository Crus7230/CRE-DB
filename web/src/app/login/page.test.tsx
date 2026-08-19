import { afterEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "@/app/login/page";

afterEach(() => vi.restoreAllMocks());

it("shows a clear error when the shared access code is rejected", async () => {
  const user = userEvent.setup();
  vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: "접근코드가 올바르지 않습니다." }), { status: 401, headers: { "Content-Type": "application/json" } }));
  render(<LoginPage/>);
  expect(screen.getByRole("heading", { name: "CRE Intelligence 접속" })).toBeInTheDocument();
  await user.type(screen.getByLabelText("팀 공용 접근코드"), "wrong-code");
  await user.click(screen.getByRole("button", { name: "대시보드 열기" }));
  expect(await screen.findByText("접근코드가 올바르지 않습니다.")).toBeInTheDocument();
});
