/**
 * Marks a widget that is showing built-in example figures outside Explore.
 *
 * Explore already says "Example data" on the Mode line, so the badge stays
 * hidden there. In Practice and Live a widget has no other way to tell the
 * operator that the numbers are not market or account data.
 */

import { cn } from "@/lib/utils";
import { useModeStore } from "@/stores/modeStore";

export interface ExampleDataBadgeProps {
  className?: string;
  label?: string;
}

export function ExampleDataBadge({ className, label = "Example data" }: ExampleDataBadgeProps) {
  const isExplore = useModeStore((s) => s.mode === "explore");
  if (isExplore) return null;
  return (
    <span
      role="status"
      data-testid="example-data-badge"
      title="These figures are built-in examples, not market or account data."
      className={cn(
        "inline-flex shrink-0 items-center gap-1 rounded border border-warning/30 px-1.5 py-0.5 text-xxs font-medium text-[var(--color-warning-text,var(--color-warning))]",
        className,
      )}
    >
      {label}
    </span>
  );
}

export default ExampleDataBadge;
