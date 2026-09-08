import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ContextTooltip } from "@/components/context-tooltip";

describe("ContextTooltip", () => {
  it("connects the trigger to explanatory text and an optional official link", () => {
    render(<ContextTooltip label="공식 출처" detail="기준월과 산식" href="https://example.com/source"><strong>2.2조 원</strong></ContextTooltip>);
    const trigger = screen.getByText("2.2조 원").closest("[data-context-info]") as HTMLElement;
    const tooltip = screen.getByRole("tooltip");
    expect(trigger).toHaveAttribute("tabindex", "0");
    expect(trigger).toHaveAttribute("aria-describedby", tooltip.id);
    expect(tooltip).toHaveTextContent("공식 출처");
    expect(tooltip).toHaveTextContent("기준월과 산식");
    const link = screen.getByRole("link", { name: /공식 출처 열기/ });
    expect(link).toHaveAttribute("href", "https://example.com/source");
    link.focus();
    expect(link).toHaveFocus();
    fireEvent.keyDown(link, { key: "Escape" });
    expect(link).not.toHaveFocus();
  });

  it("dismisses keyboard focus with Escape and omits a link when no URL exists", () => {
    render(<ContextTooltip label="숫자 정의" detail="보수적 집계"><span>12건</span></ContextTooltip>);
    const trigger = screen.getByText("12건").closest("[data-context-info]") as HTMLElement;
    trigger.focus();
    expect(trigger).toHaveFocus();
    fireEvent.keyDown(trigger, { key: "Escape" });
    expect(trigger).not.toHaveFocus();
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });
});
