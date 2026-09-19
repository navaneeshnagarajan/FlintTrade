import { useAtomValue } from "jotai";
import { useNavigate } from "react-router";
import { indicesSummaryAtom } from "@/atoms/marketAtoms";
import { isMarketHours } from "@/lib/market";
import type { WsTick } from "@/types/api";
import TickerMarquee, { type TickerMode } from "./TickerMarquee";

// MCX commodity instruments — these stay visible even when NSE/BSE is closed
// because MCX trades until 23:30 IST on weekdays.
const MCX_NAMES = new Set(["GOLD", "SILVER", "CRUDEOIL", "NATGAS"]);

/** True when the MCX session is currently active (weekdays 09:00–23:30 IST). */
function isMcxOpen(): boolean {
  return isMarketHours("MCX");
}

function hasAnyLiveData(indices: { data: WsTick | null }[]): boolean {
  return indices.some((idx) => idx.data !== null && (idx.data.ltp ?? 0) !== 0);
}

export interface TickerBarProps {
  /** Display mode for the dedicated scrolling strip. Default: marquee. */
  mode?: TickerMode;
}

/**
 * TickerBar — the single dedicated scrolling ticker strip under TopBar
 * (FT-UX-002). Reads live prices from indicesSummaryAtom.
 *
 * NSE/BSE indices and MCX commodities share one marquee. An MCX session
 * badge stays pinned at the leading edge so commodity hours stay visible
 * when the cash session is closed.
 */
export default function TickerBar({ mode = "marquee" }: TickerBarProps) {
  const indices = useAtomValue(indicesSummaryAtom);
  const hasData = hasAnyLiveData(indices);
  const navigate = useNavigate();
  const mcxOpen = isMcxOpen();
  const mcxIndices = indices.filter((idx) => MCX_NAMES.has(idx.name));

  return (
    <div
      className="h-7 bg-surface-base border-b border-border-default flex items-center overflow-hidden shrink-0"
      role="region"
      aria-label="Market indices"
      data-testid="ticker-strip"
    >
      {mcxIndices.length > 0 && (
        <div
          className="flex items-center gap-1.5 px-2 shrink-0 border-r border-border-default h-full"
          aria-label="MCX commodities section"
        >
          <span
            className={`text-xxs font-mono uppercase tracking-wider px-1 py-0.5 rounded border ${
              mcxOpen
                ? "text-amber-400 border-amber-500/40 bg-amber-500/10"
                : "text-text-disabled border-border-default"
            }`}
            title={mcxOpen ? "MCX session is open (09:00–23:30 IST)" : "MCX session is closed"}
            aria-label={mcxOpen ? "MCX open" : "MCX closed"}
          >
            MCX
          </span>
        </div>
      )}

      <TickerMarquee
        mode={mode}
        className="flex-1 min-w-0 h-7"
        labelled={false}
        announce={false}
      />

      {!hasData && (
        <button
          onClick={() => navigate("/settings#brokers")}
          className="text-xxs text-text-muted hover:text-accent px-3 select-none transition-colors cursor-pointer focus-visible:ring-2 focus-visible:ring-accent focus-visible:outline-none rounded shrink-0"
        >
          Connect broker for live prices →
        </button>
      )}

      {/* Accessibility: one polite live region summarises all index prices for
          screen readers (Issue #50). The nested marquee stays silent so ticks
          do not double-announce. */}
      <span
        className="sr-only"
        aria-live="polite"
        aria-atomic="true"
      >
        {indices
          .filter((i) => i.data?.ltp != null && (i.data.ltp ?? 0) > 0)
          .map((i) => `${i.name} ${i.data!.ltp}`)
          .join(", ")}
      </span>
    </div>
  );
}
