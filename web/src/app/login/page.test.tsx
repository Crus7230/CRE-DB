import { afterEach, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import LoginPage from "@/app/login/page";

afterEach(() => vi.restoreAllMocks());

it("submits a normalized email and shows the generic access rejection", async () => {
  const user = userEvent.setup();
  const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ error: "이메일 주소 또는 접속 권한을 확인해 주세요." }), { status: 401, headers: { "Content-Type": "application/json" } }));
  render(<LoginPage/>);

  const input = screen.getByLabelText("본인 이메일 주소");
  expect(input).toHaveAttribute("type", "email");
  expect(input).toHaveAttribute("autocomplete", "email");
  await user.type(input, "  Person@Example.COM ");
  expect(screen.queryByLabelText("팀 공용 접근코드")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "대시보드 열기" }));

  const request = fetchMock.mock.calls[0][1] as RequestInit;
  expect(JSON.parse(String(request.body))).toEqual({ email: "person@example.com" });
  expect(await screen.findByText("이메일 주소 또는 접속 권한을 확인해 주세요.")).toBeInTheDocument();
});
