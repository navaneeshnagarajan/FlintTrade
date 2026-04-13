/**
 * BreadthCard — Advances/Declines/Unchanged with bar chart.
 */

import { BentoCard } from "@/components/bento/BentoCard";
import { BarChart2 } from "lucide-react";

// Placeholder data — will be replaced by real breadth API in Phase 2
const BREADTH = {
  advances: 1320,
  declines: 780,
  unchanged: 200,
};

export function BreadthCard() {
  const total = BREADTH.advances + BREADTH.declines + BREADTH.unchanged;
  const advPct = (BREADTH.advances / total) * 100;
  const decPct = (BREADTH.declines / total) * 100;
  const unchPct = (BREADTH.unchanged / total) * 100;

  return (
    <BentoCard size="default" label="Market Breadth" data-testid="breadth-card">
      <div className="p-4 h-full flex flex-col gap-3">
        <div className="flex items-center gap-2">
          <BarChart2 size={13} className="text-[#505068]" aria-hidden="true" />
          <p className="text-[10px] font-medium uppercase tracking-widest text-[#505068]">
            Market Breadth
          </p>
        </div>

        {/* Bar */}
        <div
          className="flex h-2 rounded-full overflow-hidden"
          role="img"
          aria-label={`Advances: ${BREADTH.advances}, Declines: ${BREADTH.declines}, Unchanged: ${BREADTH.unchanged}`}
        >
          <div style={{ width: `${advPct}%`, background: "#22c55e" }} />
          <div style={{ width: `${unchPct}%`, background: "#505068" }} />
          <div style={{ width: `${decPct}%`, background: "#ef4444" }} />
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-2 text-center">
          <div>
            <p className="font-mono text-sm font-semibold text-[#22c55e]">
              {BREADTH.advances.toLocaleString()}
            </p>
            <p className="text-[10px] text-[#505068]">Adv</p>
          </div>
          <div>
            <p className="font-mono text-sm font-semibold text-[#9090b0]">
              {BREADTH.unchanged.toLocaleString()}
            </p>
            <p className="text-[10px] text-[#505068]">Unch</p>
          </div>
          <div>
            <p className="font-mono text-sm font-semibold text-[#ef4444]">
              {BREADTH.declines.toLocaleString()}
            </p>
            <p className="text-[10px] text-[#505068]">Dec</p>
          </div>
        </div>

        <p className="text-[10px] text-[#505068] text-center mt-auto">
          NSE · {total.toLocaleString()} total
        </p>
      </div>
    </BentoCard>
  );
}
