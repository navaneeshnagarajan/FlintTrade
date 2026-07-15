/**
 * DemoBanner.tsx
 *
 * Reusable banner shown when displaying sample/demo data
 * because no broker data source is connected or the API returned an error.
 */

import type { ReactNode } from "react";
import { Info } from "lucide-react";

export function DemoBanner({
  message = "Showing sample data — connect a broker for live data",
}: {
  message?: ReactNode;
}) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 mb-4 rounded border border-amber-500/20 bg-amber-500/5 text-amber-400 text-xs">
      <Info size={14} className="shrink-0" />
      <span>{message}</span>
    </div>
  );
}
