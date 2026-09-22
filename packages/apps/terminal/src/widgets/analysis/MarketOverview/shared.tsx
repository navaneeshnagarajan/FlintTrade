/**
 * Shared provenance chrome for the Market Overview widget.
 *
 * Live sections still show a Live chip. Sample chips are retired: the Mode
 * honesty bar owns that disclaimer, so a sample section stays quiet.
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
