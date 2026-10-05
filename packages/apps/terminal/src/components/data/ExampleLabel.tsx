/**
 * Visible "Example" mark for fabricated Home and Invest figures.
 *
 * A card that still draws placeholder
 * numbers needs this word on the figure, so it cannot be read as the Practice
 * account.
 */

import { cn } from "@/lib/utils";

export function ExampleLabel({
  testId = "example-label",
  className,
}: {
  testId?: string;
  className?: string;
}) {
  return (
    <span
      data-testid={testId}
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[9px] font-medium uppercase tracking-wide",
        className,
      )}
      style={{
        background: "var(--color-surface-active)",
        color: "var(--color-text-muted)",
      }}
      title="Example — not your account or a live quote"
    >
      Example
    </span>
  );
}
