/**
 * RotationTab — Relative Rotation Graphs for the Market Overview widget.
 *
 * Carried over from the retired SectorMap widget's RRG and Portfolio modes.
 * Rotation is a top-level tab rather than a view under Sectors because it
 * answers a different question (multi-week relative rotation against a
 * benchmark) from the day-change sector map, has its own data plane
 * (/ft-api rrg endpoints vs the positions feed), and gives the retired
 * sectormap RRG deep-links a stable target.
 *
 * Views:
 *   - Sectors:   sector RRG from useRRGData (backend serves sample in
 *                explore; the canvas badge fails closed on is_sample_data).
 *   - Portfolio: custom symbol list plotted on the RRG with constituent
 *                drill-down (PortfolioRRGView).
 */

import { memo, useState } from "react";
import { useRRGData } from "@/hooks/useRRGData";
import { RRGCanvas } from "../RRGCanvas";
import { PortfolioRRGView } from "../PortfolioRRGView";
import { EmptyView } from "../SectorRenderModes";
import type { RotationView } from "../types";

const RRG_TAIL_LENGTH = 8;

interface RotationTabProps {
  /** Opening view — how retired ids reproduce their presentation. */
  initialView?: RotationView;
}

function RotationTab({ initialView }: RotationTabProps) {
  const [view, setView] = useState<RotationView>(initialView ?? "sectors");
  const rrgData = useRRGData(RRG_TAIL_LENGTH);

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* View switcher */}
      <div
        className="flex items-center gap-px px-2 py-1 border-b border-border-default shrink-0"
        role="tablist"
        aria-label="Rotation view"
      >
        {(["sectors", "portfolio"] as const).map((id) => (
          <button
            key={id}
            role="tab"
            aria-selected={view === id}
            onClick={() => setView(id)}
            className={`px-2.5 py-0.5 text-xxs font-medium rounded transition-colors ${
              view === id
                ? "bg-accent/15 text-accent border border-accent/30"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
            }`}
          >
            {id === "sectors" ? "Sectors" : "Portfolio"}
          </button>
        ))}
        <div className="flex-1" />
        <span className="text-xxs text-text-disabled">
          RS-Ratio (x) vs RS-Momentum (y) · 100 = neutral
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {view === "portfolio"
          ? <PortfolioRRGView />
          : rrgData.data
          ? <RRGCanvas data={rrgData.data} tailLength={RRG_TAIL_LENGTH} />
          : <EmptyView />}
      </div>
    </div>
  );
}

export default memo(RotationTab);
