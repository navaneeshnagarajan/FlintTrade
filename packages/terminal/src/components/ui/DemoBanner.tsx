/**
 * DemoBanner.tsx
 *
 * Reusable banner shown when displaying sample/demo data
 * because OpenAlgo is not connected or the API returned an error.
 */

import { Info } from "lucide-react";

export function DemoBanner() {
  return (
    <div className="flex items-center gap-2 px-3 py-2 mb-4 rounded border border-amber-500/20 bg-amber-500/5 text-amber-400 text-xs">
      <Info size={14} className="shrink-0" />
      <span>Showing sample data — connect OpenAlgo for live data</span>
    </div>
  );
}
