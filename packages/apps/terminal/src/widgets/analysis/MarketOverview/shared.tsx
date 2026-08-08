/**
 * Shared provenance chrome for the Market Overview widget.
 *
 * Every section that can be either live or sample renders a {@link ProvenanceBadge}
 * driven by a fail-closed check on its own source; sections with no live path
 * at all render {@link ProvenanceBadge} unconditionally. The "one badge that
 * lies trains the operator to ignore the one that matters" rule from the
 * source widgets is preserved verbatim.
 */

import { ProvenanceBadge } from "@/components/data/ProvenanceBadge";

/** Per-section Live/Sample chip migrated to canonical four-state atom (Slice 3). */
export function ProvChip({ live }: { live: boolean }) {
  return <ProvenanceBadge label={live ? "Live" : "Sample"} placement="inline" />;
}

/** Unconditional sample affordance migrated to canonical atom (Slice 3). */
export function SampleBadge({ title }: { title: string }) {
  return <ProvenanceBadge label="Sample" placement="inline" title={title} />;
}

/** Uppercase section heading used across the tabs. */
export function SectionHeading({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p id={id} className="text-xxs font-medium text-text-muted uppercase tracking-wide mb-1.5">
      {children}
    </p>
  );
}
