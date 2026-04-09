/**
 * OptionsFlowWidget — Real-time feed of unusual options activity.
 *
 * Each entry shows:
 *   time · symbol · strike · CE/PE · BUY/SELL · qty · premium · OI change
 *
 * Highlighting rules:
 *   - Large orders (qty ≥ 10× avg)    → amber row
 *   - High premium (≥ 10 L total)     → accent border left
 *   - Activity type badge: sweep / block / unusual OI
 *
 * Filters: symbol, activity type.
 * Sort:    newest first OR largest premium first.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Workflow, ArrowUpDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type OptionType   = "CE" | "PE";
export type ActionType   = "BUY" | "SELL";
export type ActivityType = "sweep" | "block" | "unusual_oi";
export type SortMode     = "time" | "premium";

export interface OptionsFlowEntry {
  id: string;
  time: string;
  symbol: string;
  strike: number;
  optionType: OptionType;
  action: ActionType;
  qty: number;
  premium: number;
  totalPremium: number;  // qty × premium × lot size
  oiChange: number;      // OI delta in contracts
  activityType: ActivityType;
  isLargeOrder: boolean;
  isHighPremium: boolean;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_FLOW: OptionsFlowEntry[] = [
  {
    id: "F001", time: "15:24:12", symbol: "NIFTY",     strike: 22300, optionType: "PE", action: "BUY",
    qty: 2500, premium: 148.5, totalPremium: 3_712_500, oiChange: +12500,
    activityType: "sweep", isLargeOrder: true, isHighPremium: true,
  },
  {
    id: "F002", time: "15:23:47", symbol: "BANKNIFTY",  strike: 48500, optionType: "CE", action: "SELL",
    qty: 750,  premium: 210.0, totalPremium: 3_150_000, oiChange: -3750,
    activityType: "block", isLargeOrder: false, isHighPremium: true,
  },
  {
    id: "F003", time: "15:22:31", symbol: "NIFTY",     strike: 22400, optionType: "CE", action: "BUY",
    qty: 3750, premium:  92.3, totalPremium: 3_461_250, oiChange: +18750,
    activityType: "unusual_oi", isLargeOrder: true, isHighPremium: true,
  },
  {
    id: "F004", time: "15:21:05", symbol: "FINNIFTY",   strike: 23200, optionType: "PE", action: "SELL",
    qty: 500,  premium: 175.0, totalPremium:   875_000, oiChange: -2500,
    activityType: "sweep", isLargeOrder: false, isHighPremium: false,
  },
  {
    id: "F005", time: "15:20:18", symbol: "NIFTY",     strike: 22200, optionType: "PE", action: "BUY",
    qty: 5000, premium:  58.5, totalPremium: 2_925_000, oiChange: +25000,
    activityType: "block", isLargeOrder: true, isHighPremium: true,
  },
  {
    id: "F006", time: "15:19:52", symbol: "BANKNIFTY",  strike: 48000, optionType: "CE", action: "BUY",
    qty: 1250, premium: 315.0, totalPremium: 3_937_500, oiChange: +6250,
    activityType: "unusual_oi", isLargeOrder: false, isHighPremium: true,
  },
  {
    id: "F007", time: "15:18:30", symbol: "NIFTY",     strike: 22500, optionType: "CE", action: "SELL",
    qty: 2000, premium:  44.0, totalPremium:   880_000, oiChange: -10000,
    activityType: "sweep", isLargeOrder: true, isHighPremium: false,
  },
  {
    id: "F008", time: "15:17:14", symbol: "MIDCPNIFTY", strike: 12400, optionType: "PE", action: "BUY",
    qty: 600,  premium: 120.5, totalPremium:   723_000, oiChange: +3000,
    activityType: "block", isLargeOrder: false, isHighPremium: false,
  },
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const ACTIVITY_LABELS: Record<ActivityType, string> = {
  sweep:      "Sweep",
  block:      "Block",
  unusual_oi: "OI Spike",
};

const ACTIVITY_COLOURS: Record<ActivityType, string> = {
  sweep:      "bg-accent/15 text-accent",
  block:      "bg-warning/15 text-warning",
  unusual_oi: "bg-loss/15 text-loss",
};

const INR_COMPACT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  notation: "compact",
  maximumFractionDigits: 1,
});

function fmtPremium(total: number): string {
  return INR_COMPACT.format(total);
}

function fmtOI(delta: number): string {
  const sign = delta > 0 ? "+" : "";
  return `${sign}${(delta / 1000).toFixed(1)}K`;
}

// ---------------------------------------------------------------------------
// Filter bar
// ---------------------------------------------------------------------------

const SYMBOLS_ALL = ["All", "NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const ACTIVITY_ALL = ["All", "sweep", "block", "unusual_oi"] as const;

type ActivityFilter = typeof ACTIVITY_ALL[number];

// ---------------------------------------------------------------------------
// Row
// ---------------------------------------------------------------------------

function FlowRow({ entry }: { entry: OptionsFlowEntry }) {
  return (
    <tr
      className={cn(
        "border-b border-border-subtle transition-colors hover:bg-surface-hover",
        entry.isLargeOrder && "bg-warning/5",
        entry.isHighPremium && "border-l-2 border-l-accent",
      )}
      aria-label={`${entry.symbol} ${entry.strike} ${entry.optionType} ${entry.action}`}
    >
      <td className="py-1 px-1 text-xxs text-text-muted font-mono whitespace-nowrap">{entry.time}</td>
      <td className="py-1 px-1 text-xs text-text-secondary font-semibold whitespace-nowrap">{entry.symbol}</td>
      <td className="py-1 px-1 text-xs font-mono tabular-nums text-text-primary text-right">{entry.strike}</td>
      <td className="py-1 px-1 text-center">
        <span className={cn(
          "text-xxs font-bold px-1 rounded",
          entry.optionType === "CE" ? "text-profit" : "text-loss",
        )}>
          {entry.optionType}
        </span>
      </td>
      <td className="py-1 px-1 text-center">
        <span className={cn(
          "text-xxs font-bold px-1 rounded",
          entry.action === "BUY" ? "text-profit" : "text-loss",
        )}>
          {entry.action}
        </span>
      </td>
      <td className="py-1 px-1 text-xs font-mono tabular-nums text-text-secondary text-right whitespace-nowrap">
        {entry.qty.toLocaleString("en-IN")}
      </td>
      <td className="py-1 px-1 text-xs font-mono tabular-nums text-text-primary text-right whitespace-nowrap">
        {fmtPremium(entry.totalPremium)}
      </td>
      <td className="py-1 px-1 text-xs font-mono tabular-nums text-right whitespace-nowrap">
        <span className={entry.oiChange > 0 ? "text-profit" : "text-loss"}>
          {fmtOI(entry.oiChange)}
        </span>
      </td>
      <td className="py-1 px-1 text-center">
        <span className={cn("text-xxs px-1.5 py-0.5 rounded font-medium", ACTIVITY_COLOURS[entry.activityType])}>
          {ACTIVITY_LABELS[entry.activityType]}
        </span>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function OptionsFlowWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbolFilter, setSymbolFilter] = useState("All");
  const [activityFilter, setActivityFilter] = useState<ActivityFilter>("All");
  const [sortMode, setSortMode] = useState<SortMode>("time");

  useEffect(() => {
    track("trade", "widget_view_options_flow");
  }, [track]);

  const filtered = useMemo(() => {
    let rows = SAMPLE_FLOW;
    if (symbolFilter !== "All") rows = rows.filter((r) => r.symbol === symbolFilter);
    if (activityFilter !== "All") rows = rows.filter((r) => r.activityType === activityFilter);
    if (sortMode === "premium") {
      rows = [...rows].sort((a, b) => b.totalPremium - a.totalPremium);
    }
    return rows;
  }, [symbolFilter, activityFilter, sortMode]);

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Options Flow widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Workflow size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Options Flow</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <span className="text-xxs text-text-muted font-mono">{filtered.length} entries</span>
      </div>

      {/* Filter bar */}
      <div
        className="flex-none flex items-center gap-1.5 px-2 py-1.5 bg-surface-card border-b border-border-subtle flex-wrap"
        aria-label="Filter controls"
      >
        {/* Symbol */}
        <select
          value={symbolFilter}
          onChange={(e) => setSymbolFilter(e.target.value)}
          className="px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
          aria-label="Filter by symbol"
        >
          {SYMBOLS_ALL.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Activity type */}
        <select
          value={activityFilter}
          onChange={(e) => setActivityFilter(e.target.value as ActivityFilter)}
          className="px-2 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary focus:outline-none focus:border-accent/50"
          aria-label="Filter by activity type"
        >
          {ACTIVITY_ALL.map((a) => (
            <option key={a} value={a}>
              {a === "All" ? "All Types" : ACTIVITY_LABELS[a as ActivityType]}
            </option>
          ))}
        </select>

        {/* Sort toggle */}
        <button
          onClick={() => setSortMode((m) => m === "time" ? "premium" : "time")}
          className={cn(
            "flex items-center gap-1 px-2 py-0.5 text-xs rounded border transition-colors",
            sortMode === "premium"
              ? "bg-accent/15 text-accent border-accent/30"
              : "bg-surface-hover text-text-muted border-border-default hover:text-text-primary",
          )}
          aria-label={`Sort by ${sortMode === "time" ? "premium" : "time"}`}
          aria-pressed={sortMode === "premium"}
        >
          <ArrowUpDown size={10} />
          {sortMode === "time" ? "Newest" : "Largest"}
        </button>
      </div>

      {/* Table */}
      <div className="flex-1 min-h-0 overflow-auto">
        <table className="w-full text-xs" aria-label="Options flow table">
          <thead className="sticky top-0 bg-surface-card z-10">
            <tr className="border-b border-border-default">
              <th className="text-left py-1 px-1 text-xxs text-text-muted font-medium">Time</th>
              <th className="text-left py-1 px-1 text-xxs text-text-muted font-medium">Symbol</th>
              <th className="text-right py-1 px-1 text-xxs text-text-muted font-medium">Strike</th>
              <th className="text-center py-1 px-1 text-xxs text-text-muted font-medium">Type</th>
              <th className="text-center py-1 px-1 text-xxs text-text-muted font-medium">Side</th>
              <th className="text-right py-1 px-1 text-xxs text-text-muted font-medium">Qty</th>
              <th className="text-right py-1 px-1 text-xxs text-text-muted font-medium">Premium</th>
              <th className="text-right py-1 px-1 text-xxs text-text-muted font-medium">OI Δ</th>
              <th className="text-center py-1 px-1 text-xxs text-text-muted font-medium">Activity</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={9} className="py-8 text-center text-text-muted text-xs">
                  No flow entries match the current filters
                </td>
              </tr>
            ) : (
              filtered.map((entry) => <FlowRow key={entry.id} entry={entry} />)
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default memo(OptionsFlowWidget);
