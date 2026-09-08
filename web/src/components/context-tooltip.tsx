"use client";

import { type KeyboardEvent, type ReactNode, useId } from "react";

type ContextTooltipProps = {
  label: string;
  detail: string;
  children: ReactNode;
  href?: string;
  align?: "start" | "center" | "end";
};

export function ContextTooltip({ label, detail, children, href, align = "center" }: ContextTooltipProps) {
  const id = useId();
  const dismiss = (event: KeyboardEvent<HTMLSpanElement>) => {
    if (event.key !== "Escape") return;
    event.stopPropagation();
    (event.currentTarget.ownerDocument.activeElement as HTMLElement | null)?.blur();
    event.currentTarget.blur();
  };
  return <span className="context-tooltip" data-align={align} data-context-info tabIndex={0} aria-describedby={id} onKeyDown={dismiss}>
    <span className="context-tooltip-trigger">{children}</span>
    <span className="context-tooltip-popover" id={id} role="tooltip">
      <b>{label}</b>
      <span>{detail}</span>
      {href && <a href={href} target="_blank" rel="noreferrer">공식 출처 열기 ↗</a>}
    </span>
  </span>;
}
