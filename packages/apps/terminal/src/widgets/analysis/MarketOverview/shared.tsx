/**
 * Shared provenance chrome for the Market Overview widget.
 *
 * Every section that can be either live or sample renders a {@link ProvChip}
 * driven by a fail-closed check on its own source; sections with no live path
 * at all render {@link SampleBadge} unconditionally. The "one badge that
 * lies trains the operator to ignore the one that matters" rule from the
 * source widgets is preserved verbatim.
 */

import { cn } from "@/lib/utils";

/** Per-section Live/Sample chip (from the retired MarketSummary widget). */
export function ProvChip({ live }: { live: boolean }) {
  return (
    <span
      role="status"
      className={cn(
        "ml-1.5 px-1 py-0.5 text-xxs rounded border align-middle",
        live
          ? "text-profit bg-profit/10 border-profit/30"
          : "text-warning bg-warning/10 border-warning/30",
      )}
    >
      {live ? "Live" : "Sample"}
    </span>
  );
}

/** Unconditional sample affordance for surfaces with no live path. */
export function SampleBadge({ title }: { title: string }) {
  return (
    <span
      className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
      role="status"
      aria-label={title}
      title={title}
    >
      Sample data
    </span>
  );
}

/** Uppercase section heading used across the tabs. */
export function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p id={id} className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
      {children}
    </p>
  );
}
