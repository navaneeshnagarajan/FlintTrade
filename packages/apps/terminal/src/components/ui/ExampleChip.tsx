/**
 * One example marker for a view that is showing example data.
 *
 * Invest uses this chip instead of the sample-data banner, so a view does
 * not show both. Practice hides it unless the figures are example data in
 * every mode (`always`): Practice itself is simulated fills, not sample prices.
 */

import { Compass } from "lucide-react";

import { useModeStore } from "@/stores/modeStore";

export function ExampleChip({ always = false }: { always?: boolean }) {
  const isExample = useModeStore((s) => s.mode === "explore");
  if (!always && !isExample) return null;
  return (
    <span
      data-testid="example-chip"
      className="inline-flex items-center gap-1 h-7 px-2.5 rounded text-xs font-medium font-heading bg-text-muted/15 text-text-secondary border border-text-muted/25"
      aria-label="Example"
    >
      <Compass size={12} aria-hidden="true" />
      Example
    </span>
  );
}
