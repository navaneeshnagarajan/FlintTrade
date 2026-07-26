/**
 * FlowTape — the large-trade options tape, folded in from the retired
 * Options Flow widget (ruling D1, 2026-07-26).
 *
 * Options Flow rendered sweep / block / OI-spike tagged rows of large trades,
 * but it had NO data source — an unconditional hardcoded sample behind a
 * permanent badge. Its unusual-OI third was already dominated by this
 * widget's real `/v1/oi/unusual` feed, so what survives here is the tape
 * PRESENTATION as a collapsed, clearly-labelled illustrative section: the
 * shape a large-trade feed will render into if one ever exists. No element
 * of it may be mistaken for live data.
 */

import { useMemo, useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type FlowActivityType = "sweep" | "block" | "unusual_oi";

export interface FlowTapeEntry {
  id: string;
  time: string;
  symbol: string;
  strike: number;
  optionType: "CE" | "PE";
  action: "BUY" | "SELL";
  qty: number;
  totalPremium: number;
  oiChange: number;
  activityType: FlowActivityType;
  isLargeOrder: boolean;
  isHighPremium: boolean;
}

// ---------------------------------------------------------------------------
// Sample rows (carried from Options Flow — illustrative only)
// ---------------------------------------------------------------------------

export const SAMPLE_FLOW_TAPE: readonly FlowTapeEntry[] = [
  { id: "f1", time: "09:21:14", symbol: "NIFTY", strike: 24500, optionType: "CE", action: "BUY", qty: 5250, totalPremium: 6_800_000, oiChange: 41_000, activityType: "sweep", isLargeOrder: true, isHighPremium: true },
  { id: "f2", time: "09:34:02", symbol: "BANKNIFTY", strike: 52000, optionType: "PE", action: "SELL", qty: 1740, totalPremium: 4_200_000, oiChange: -12_500, activityType: "block", isLargeOrder: false, isHighPremium: true },
  { id: "f3", time: "10:05:48", symbol: "NIFTY", strike: 24400, optionType: "PE", action: "BUY", qty: 9800, totalPremium: 11_300_000, oiChange: 87_000, activityType: "unusual_oi", isLargeOrder: true, isHighPremium: true },
  { id: "f4", time: "10:42:31", symbol: "FINNIFTY", strike: 23300, optionType: "CE", action: "SELL", qty: 780, totalPremium: 950_000, oiChange: 6_200, activityType: "sweep", isLargeOrder: false, isHighPremium: false },
  { id: "f5", time: "11:18:09", symbol: "NIFTY", strike: 24600, optionType: "CE", action: "BUY", qty: 6400, totalPremium: 5_500_000, oiChange: 33_400, activityType: "block", isLargeOrder: true, isHighPremium: true },
  { id: "f6", time: "12:03:55", symbol: "BANKNIFTY", strike: 51500, optionType: "PE", action: "BUY", qty: 2300, totalPremium: 3_100_000, oiChange: 19_800, activityType: "unusual_oi", isLargeOrder: false, isHighPremium: true },
];

const ACTIVITY_LABELS: Record<FlowActivityType, string> = {
  sweep: "Sweep",
  block: "Block",
  unusual_oi: "OI Spike",
};

const ACTIVITY_COLOURS: Record<FlowActivityType, string> = {
  sweep: "bg-accent/15 text-accent",
  block: "bg-warning/15 text-warning",
  unusual_oi: "bg-loss/15 text-loss",
};

const INR_COMPACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  notation: "compact",
  maximumFractionDigits: 1,
});

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function FlowTapeSection() {
  const [open, setOpen] = useState(false);
  const [sortByPremium, setSortByPremium] = useState(false);

  const rows = useMemo(
    () =>
      sortByPremium
        ? [...SAMPLE_FLOW_TAPE].sort((a, b) => b.totalPremium - a.totalPremium)
        : SAMPLE_FLOW_TAPE,
    [sortByPremium],
  );

  return (
    <div className="flex-none border-t border-border-subtle" data-testid="flow-tape-section">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-xxs text-text-muted hover:text-text-primary transition-colors"
      >
        {open ? <ChevronDown size={11} aria-hidden="true" /> : <ChevronRight size={11} aria-hidden="true" />}
        Large-trade tape
        <span className="px-1.5 py-0.5 rounded border border-warning/30 bg-warning/10 text-warning font-medium">
          Illustrative sample — no large-trade feed exists yet
        </span>
      </button>

      {open && (
        <div className="max-h-44 overflow-y-auto px-1 pb-1">
          <div className="flex items-center justify-end px-1 pb-1">
            <button
              type="button"
              onClick={() => setSortByPremium((s) => !s)}
              aria-pressed={sortByPremium}
              className="text-xxs text-text-muted hover:text-text-primary"
            >
              {sortByPremium ? "Sorted by premium" : "Sorted by time"}
            </button>
          </div>
          <table className="w-full text-left">
            <tbody>
              {rows.map((entry) => (
                <tr
                  key={entry.id}
                  className={cn(
                    "border-b border-border-subtle",
                    entry.isLargeOrder && "bg-warning/5",
                    entry.isHighPremium && "border-l-2 border-l-accent",
                  )}
                >
                  <td className="py-0.5 px-1 text-xxs text-text-muted font-mono whitespace-nowrap">{entry.time}</td>
                  <td className="py-0.5 px-1 text-xxs text-text-secondary font-semibold whitespace-nowrap">{entry.symbol}</td>
                  <td className="py-0.5 px-1 text-xxs font-mono tabular-nums text-text-primary text-right">{entry.strike}</td>
                  <td className={cn("py-0.5 px-1 text-xxs font-bold text-center", entry.optionType === "CE" ? "text-profit" : "text-loss")}>
                    {entry.optionType}
                  </td>
                  <td className={cn("py-0.5 px-1 text-xxs font-bold text-center", entry.action === "BUY" ? "text-profit" : "text-loss")}>
                    {entry.action}
                  </td>
                  <td className="py-0.5 px-1 text-xxs font-mono tabular-nums text-right">{entry.qty.toLocaleString("en-IN")}</td>
                  <td className="py-0.5 px-1 text-xxs font-mono tabular-nums text-right">{INR_COMPACT.format(entry.totalPremium)}</td>
                  <td className="py-0.5 px-1 text-center">
                    <span className={cn("text-xxs px-1.5 py-0.5 rounded font-medium", ACTIVITY_COLOURS[entry.activityType])}>
                      {ACTIVITY_LABELS[entry.activityType]}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
