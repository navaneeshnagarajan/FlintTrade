/**
 * FillsWidget — canonical fills blotter (terminal dedup merge 2.11).
 *
 * Replaces the TradeBook and TradeLog widgets: one table of executed fills —
 * broker tradebook rows joined with backend auto-journal enrichment
 * (exchange, entry/exit prices, realised P&L, fees, strategy) and per-fill
 * screenshot annotations ported from the Trade Journal tool.
 *
 * This is a thin workspace-panel wrapper; all behaviour lives in the embeddable
 * {@link FillsTable}, which the Trade Review tool reuses for its Log tab.
 */

import { memo, useEffect } from "react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import type { WidgetProps } from "@/types/widgets";
import { FillsTable } from "./FillsTable";

function FillsWidget(_props: WidgetProps) {
  const track = useTrackBehavior();

  useEffect(() => {
    track("trade", "widget_view_fills");
  }, [track]);

  return (
    <div className="h-full flex flex-col overflow-hidden bg-surface-base" aria-label="Fills widget">
      <FillsTable />
    </div>
  );
}

export default memo(FillsWidget);
