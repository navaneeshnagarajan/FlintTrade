/**
 * IndexStripWidget — compact horizontal strip of index observations.
 *
 * Extracted from the retired Dashboard widget (dedup ruling D5), whose
 * five-index card row was the only part of it no other widget carried. The
 * cards are the canonical index-cards surface: NIFTY 50, BANK NIFTY, SENSEX,
 * FIN NIFTY and India VIX, each with LTP, change, change% and a synthetic
 * OHLC sparkline, plus the VIX>20 warning border.
 *
 * Native REST polling and the explicitly selected Example feed publish into
 * Jotai `tickAtomFamily`; usePrevClose supplies native reference closes.
 * Example mode always badges its simulated observations. Other modes show
 * "Native quotes" only with a finite lead price and reference close. Missing
 * observations render an awaiting state rather than a fabricated level.
 *
 * The Dashboard's position-status tracker did NOT move here: it reads the
 * position book (TanStack Query), not the tick stream, so it lives with the
 * book in the Positions widget.
 */

import { memo } from "react";
import { useAtomValue } from "jotai";
import { TrendingUp, TrendingDown } from "lucide-react";
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { tickKeyFor } from "@/lib/market";
import { cn } from "@/lib/utils";
import { useModeStore } from "@/stores/modeStore";
import type { WsTick } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

interface IndexDef {
  symbol: string;
  exchange: string;
  name: string;
}

/** The five indices the retired Dashboard showed, unchanged. */
export const INDEX_STRIP_INDICES: readonly IndexDef[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX", name: "NIFTY 50" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX", name: "BANK NIFTY" },
  { symbol: "SENSEX", exchange: "BSE_INDEX", name: "SENSEX" },
  { symbol: "FINNIFTY", exchange: "NSE_INDEX", name: "FIN NIFTY" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX", name: "VIX" },
];

/** India VIX above this level gets the warning border, as on Dashboard. */
const VIX_WARNING_LEVEL = 20;

// ---------------------------------------------------------------------------
// Index card
// ---------------------------------------------------------------------------

function hasUsablePrice(tick: WsTick | null): boolean {
  const previous = tick?.prevClose ?? tick?.close;
  return tick !== null && Number.isFinite(tick.ltp) && tick.ltp > 0
    && previous !== undefined && Number.isFinite(previous) && previous > 0;
}

function IndexCard({ symbol, exchange, name, example }: IndexDef & { example: boolean }) {
  const tick: WsTick | null = useAtomValue(tickAtomFamily(tickKeyFor(symbol, exchange)));

  const ltp = tick?.ltp ?? 0;
  // Prefer the explicit session reference; partial native quotes may omit close.
  const prevClose = tick?.prevClose ?? tick?.close ?? 0;

  if (!hasUsablePrice(tick)) {
    // Honest empty state: no tick means no number — never a fabricated level.
    return (
      <div
        className="bg-surface-card border border-border-default rounded-lg p-3 shadow-sm min-w-36 shrink-0"
        aria-label={`${name} awaiting ${example ? "example" : "native"} price`}
      >
        <div className="text-xxs uppercase tracking-wider text-text-muted font-sans mb-1">
          {name}
        </div>
        <div className="text-base font-mono font-bold text-text-muted">—</div>
        <div className="text-xxs text-text-muted mt-1">Awaiting price</div>
      </div>
    );
  }

  const open = tick?.open ?? prevClose;
  const high = tick?.high ?? ltp;
  const low = tick?.low ?? ltp;
  const change = ltp - prevClose;
  const changePct = (change / prevClose) * 100;
  const up = change >= 0;
  const vixHigh = name === "VIX" && ltp > VIX_WARNING_LEVEL;

  // Synthetic 5-point OHLC sparkline from the available tick data.
  const sparkData = [open, low, (open + ltp) / 2, high, ltp];

  return (
    <div
      className={cn(
        "bg-surface-card border rounded-lg p-3 shadow-sm min-w-36 shrink-0",
        vixHigh ? "border-loss/40" : "border-border-default",
      )}
      data-vix-warning={vixHigh || undefined}
    >
      <div className="text-xxs uppercase tracking-wider text-text-muted font-sans mb-1">
        {name}
      </div>
      <div className="text-base font-mono font-bold text-text-primary">
        {INR.format(ltp)}
      </div>
      <div
        className={cn(
          "flex items-center gap-1 text-xs mt-0.5",
          up ? "text-profit" : "text-loss",
        )}
      >
        {up ? (
          <TrendingUp size={11} aria-hidden="true" />
        ) : (
          <TrendingDown size={11} aria-hidden="true" />
        )}
        <span className="font-mono tabular-nums">
          {change >= 0 ? "+" : ""}
          {change.toFixed(2)}
        </span>
        <span className="font-mono tabular-nums text-xxs">
          ({changePct >= 0 ? "+" : ""}
          {changePct.toFixed(2)}%)
        </span>
      </div>
      <FlintMiniSparkline
        ariaLabel={`${name} OHLC sparkline`}
        points={sparkData}
        positive={up}
        className="mt-1.5 h-6"
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function IndexStripWidget(_props: WidgetProps) {
  const example = useModeStore((state) => state.mode === "explore");
  // Every card independently checks its price and reference close; the badge
  // describes provenance rather than promising a streaming transport.
  const leadTick = useAtomValue(
    tickAtomFamily(tickKeyFor(INDEX_STRIP_INDICES[0].symbol, INDEX_STRIP_INDICES[0].exchange)),
  );
  const hasLeadPrice = hasUsablePrice(leadTick);

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      data-tour-target="indexstrip"
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-2 py-1 border-b border-border-default bg-surface-card shrink-0">
        <span className="font-heading font-semibold text-xxs text-text-muted uppercase tracking-widest">
          Indices
        </span>
        <span
          role="status"
          aria-label={
            example
              ? "Index cards show simulated Example prices"
              : hasLeadPrice
                ? "Index cards show native broker quotes from REST polling"
                : "Awaiting a native quote and session reference for the lead index"
          }
          className={cn(
            "px-1.5 py-0.5 text-xxs rounded border",
            example
              ? "text-accent bg-accent/10 border-accent/30"
              : hasLeadPrice
              ? "text-profit bg-profit/10 border-profit/30"
              : "text-warning bg-warning/10 border-warning/30",
          )}
        >
          {example ? "Example" : hasLeadPrice ? "Native quotes" : "Awaiting quotes"}
        </span>
      </div>

      {/* Card strip — horizontal scroll on narrow panels */}
      <div className="flex-1 min-h-0 flex items-start gap-2 p-2 overflow-x-auto overflow-y-auto">
        {INDEX_STRIP_INDICES.map((idx) => (
          <IndexCard key={idx.symbol} {...idx} example={example} />
        ))}
      </div>
    </div>
  );
}

export default memo(IndexStripWidget);
