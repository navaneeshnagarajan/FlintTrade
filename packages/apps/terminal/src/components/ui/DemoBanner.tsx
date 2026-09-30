/**
 * DemoBanner.tsx
 *
 * Reusable banner shown when displaying sample/demo data
 * because no broker data source is connected or the API returned an error.
 */

import type { ReactNode } from "react";
import { Info } from "lucide-react";

import { useModeStore } from "@/stores/modeStore";

export const SAMPLE_DATA_BANNER = "Example data. Connect a broker to see your own.";

export function DemoBanner({
  message = SAMPLE_DATA_BANNER,
}: {
  message?: ReactNode;
}) {
  // The sample-data banner never appears in Practice. A caller that passes
  // its own message (the tax ledger, for example) keeps that sentence.
  // Invest views use ExampleChip instead of this banner.
  const mode = useModeStore((s) => s.mode);
  if (mode === "practice" && message === SAMPLE_DATA_BANNER) return null;
  return (
    <div className="flex items-center gap-2 px-3 py-2 mb-4 rounded border border-amber-500/20 bg-amber-500/5 text-amber-400 text-xs">
      <Info size={14} className="shrink-0" />
      <span>{message}</span>
    </div>
  );
}
