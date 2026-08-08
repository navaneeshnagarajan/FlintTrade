import React from "react";

export type ProvenanceKind = "Sample" | "Unavailable" | "Live" | "Stale";

const DEFAULT_TITLES: Record<ProvenanceKind, string> = {
  Sample: "Sample data — not live",
  Unavailable: "Data unavailable",
  Live: "Live data",
  Stale: "Stale data — may be out of date",
};

export interface ProvenanceBadgeProps extends React.HTMLAttributes<HTMLSpanElement> {
  label?: ProvenanceKind;
  title?: string;
  testId?: string;
  placement?: "corner" | "inline";
  className?: string;
  style?: React.CSSProperties;
}

export function ProvenanceBadge({
  label = "Sample",
  title,
  testId,
  placement = "corner",
  className,
  style,
  ...rest
}: ProvenanceBadgeProps) {
  const isCorner = placement === "corner";
  const baseClasses = "rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide";
  const cornerClasses = isCorner ? "absolute right-2 top-2 z-10" : "";
  const mergedClassName = [baseClasses, cornerClasses, className].filter(Boolean).join(" ");

  const mergedStyle = {
    background: "var(--color-surface-active)",
    color: "var(--color-text-muted)",
    ...(style || {}),
  };

  const effectiveTestId = testId || (isCorner ? "provenance-badge" : "provenance-badge-inline");

  return (
    <span
      {...rest}
      className={mergedClassName}
      style={mergedStyle}
      data-testid={effectiveTestId}
      data-provenance={label}
      title={title ?? DEFAULT_TITLES[label]}
    >
      {label}
    </span>
  );
}
