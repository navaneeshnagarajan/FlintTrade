/**
 * SectorPerformanceWidget — Nifty sectoral index performance bar chart.
 *
 * Features:
 *   - Horizontal bars colour-coded green/red by performance
 *   - All 12 Nifty sectoral indices
 *   - Timeframe toggle: 1D, 1W, 1M, 3M, 1Y
 *   - Sorted best to worst by default
 *   - Sample data only — no live sectoral-index endpoint is wired yet, so the
 *     "Sample data" badge is shown unconditionally and the widget never implies
 *     the figures are live (no auto-refresh, no "last updated" clock).
 */

import { useState, useEffect, memo } from "react";
import { BarChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type Timeframe = "1D" | "1W" | "1M" | "3M" | "1Y";

interface SectorEntry {
  name: string;
  symbol: string;
  changePct: number;
}

// ---------------------------------------------------------------------------
// Sample data — one set per timeframe (deterministic for tests)
// ---------------------------------------------------------------------------

const SAMPLE_DATA: Record<Timeframe, SectorEntry[]> = {
  "1D": [
    { name: "IT",                symbol: "NIFTYIT",       changePct:  1.82 },
    { name: "Pharma",            symbol: "NIFTYPHARMA",   changePct:  0.93 },
    { name: "Auto",              symbol: "NIFTYAUTO",     changePct:  0.67 },
    { name: "FMCG",              symbol: "NIFTYFMCG",     changePct:  0.41 },
    { name: "Financial Svcs",    symbol: "NIFTYFIN",      changePct:  0.18 },
    { name: "Private Bank",      symbol: "NIFTYPVTBANK",  changePct: -0.12 },
    { name: "Energy",            symbol: "NIFTYENERGY",   changePct: -0.28 },
    { name: "Realty",            symbol: "NIFTYREALTY",   changePct: -0.45 },
    { name: "Metal",             symbol: "NIFTYMETAL",    changePct: -0.84 },
    { name: "Media",             symbol: "NIFTYMEDIA",    changePct: -1.07 },
    { name: "PSU Bank",          symbol: "NIFTYPSUBANK",  changePct: -1.36 },
    { name: "Bank",              symbol: "BANKNIFTY",     changePct: -1.71 },
  ],
  "1W": [
    { name: "Pharma",            symbol: "NIFTYPHARMA",   changePct:  4.21 },
    { name: "IT",                symbol: "NIFTYIT",       changePct:  3.56 },
    { name: "Auto",              symbol: "NIFTYAUTO",     changePct:  2.41 },
    { name: "FMCG",              symbol: "NIFTYFMCG",     changePct:  1.87 },
    { name: "Energy",            symbol: "NIFTYENERGY",   changePct:  0.62 },
    { name: "Financial Svcs",    symbol: "NIFTYFIN",      changePct: -0.34 },
    { name: "Realty",            symbol: "NIFTYREALTY",   changePct: -0.91 },
    { name: "Metal",             symbol: "NIFTYMETAL",    changePct: -1.24 },
    { name: "Private Bank",      symbol: "NIFTYPVTBANK",  changePct: -1.58 },
    { name: "Bank",              symbol: "BANKNIFTY",     changePct: -2.03 },
    { name: "PSU Bank",          symbol: "NIFTYPSUBANK",  changePct: -2.78 },
    { name: "Media",             symbol: "NIFTYMEDIA",    changePct: -3.14 },
  ],
  "1M": [
    { name: "Realty",            symbol: "NIFTYREALTY",   changePct:  8.43 },
    { name: "Pharma",            symbol: "NIFTYPHARMA",   changePct:  6.21 },
    { name: "Metal",             symbol: "NIFTYMETAL",    changePct:  4.87 },
    { name: "Energy",            symbol: "NIFTYENERGY",   changePct:  3.62 },
    { name: "Auto",              symbol: "NIFTYAUTO",     changePct:  2.14 },
    { name: "IT",                symbol: "NIFTYIT",       changePct:  1.38 },
    { name: "Financial Svcs",    symbol: "NIFTYFIN",      changePct: -0.87 },
    { name: "FMCG",              symbol: "NIFTYFMCG",     changePct: -1.43 },
    { name: "Bank",              symbol: "BANKNIFTY",     changePct: -2.18 },
    { name: "PSU Bank",          symbol: "NIFTYPSUBANK",  changePct: -3.07 },
    { name: "Private Bank",      symbol: "NIFTYPVTBANK",  changePct: -3.56 },
    { name: "Media",             symbol: "NIFTYMEDIA",    changePct: -5.21 },
  ],
  "3M": [
    { name: "Metal",             symbol: "NIFTYMETAL",    changePct: 18.42 },
    { name: "Realty",            symbol: "NIFTYREALTY",   changePct: 14.87 },
    { name: "Energy",            symbol: "NIFTYENERGY",   changePct: 11.34 },
    { name: "Auto",              symbol: "NIFTYAUTO",     changePct:  7.56 },
    { name: "Pharma",            symbol: "NIFTYPHARMA",   changePct:  5.23 },
    { name: "Financial Svcs",    symbol: "NIFTYFIN",      changePct:  2.18 },
    { name: "IT",                symbol: "NIFTYIT",       changePct: -1.42 },
    { name: "FMCG",              symbol: "NIFTYFMCG",     changePct: -3.87 },
    { name: "Media",             symbol: "NIFTYMEDIA",    changePct: -5.14 },
    { name: "Private Bank",      symbol: "NIFTYPVTBANK",  changePct: -7.34 },
    { name: "PSU Bank",          symbol: "NIFTYPSUBANK",  changePct: -9.12 },
    { name: "Bank",              symbol: "BANKNIFTY",     changePct: -11.83 },
  ],
  "1Y": [
    { name: "Private Bank",      symbol: "NIFTYPVTBANK",  changePct: 34.21 },
    { name: "Financial Svcs",    symbol: "NIFTYFIN",      changePct: 28.14 },
    { name: "IT",                symbol: "NIFTYIT",       changePct: 22.87 },
    { name: "Pharma",            symbol: "NIFTYPHARMA",   changePct: 18.43 },
    { name: "Auto",              symbol: "NIFTYAUTO",     changePct: 15.62 },
    { name: "Bank",              symbol: "BANKNIFTY",     changePct: 11.34 },
    { name: "Metal",             symbol: "NIFTYMETAL",    changePct:  6.87 },
    { name: "FMCG",              symbol: "NIFTYFMCG",     changePct:  3.42 },
    { name: "Energy",            symbol: "NIFTYENERGY",   changePct: -2.18 },
    { name: "PSU Bank",          symbol: "NIFTYPSUBANK",  changePct: -8.43 },
    { name: "Realty",            symbol: "NIFTYREALTY",   changePct: -14.27 },
    { name: "Media",             symbol: "NIFTYMEDIA",    changePct: -21.54 },
  ],
};

const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M", "1Y"];

// ---------------------------------------------------------------------------
// Bar row
// ---------------------------------------------------------------------------

interface BarRowProps {
  entry: SectorEntry;
  maxAbs: number;
}

function BarRow({ entry, maxAbs }: BarRowProps) {
  const isUp = entry.changePct >= 0;
  const barPct = maxAbs > 0 ? (Math.abs(entry.changePct) / maxAbs) * 100 : 0;

  return (
    <div
      className="flex items-center gap-2"
      aria-label={`${entry.name} ${entry.changePct >= 0 ? "+" : ""}${entry.changePct.toFixed(2)}%`}
    >
      <span className="text-xxs text-text-secondary w-20 shrink-0 truncate">{entry.name}</span>
      <div className="flex-1 h-4 bg-surface-hover rounded-sm overflow-hidden relative">
        <div
          className={cn("h-full rounded-sm transition-all duration-300", isUp ? "bg-profit/70" : "bg-loss/70")}
          style={{ width: `${barPct}%` }}
        />
      </div>
      <span
        className={cn(
          "text-xxs font-mono tabular-nums w-14 text-right shrink-0",
          isUp ? "text-profit" : "text-loss",
        )}
      >
        {isUp ? "+" : ""}{entry.changePct.toFixed(2)}%
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function SectorPerformanceWidget() {
  const track = useTrackBehavior();
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  useEffect(() => {
    track("trade", "widget_view_sector_performance");
  }, [track]);

  const sectors = SAMPLE_DATA[timeframe];
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.changePct)), 0.1);
  const positiveCount = sectors.filter((s) => s.changePct >= 0).length;
  const negativeCount = sectors.length - positiveCount;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Sector Performance widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2.5 py-1.5 bg-surface-card border-b border-border-default">
        <BarChart size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Sector Performance</span>
        {/* Honest disclosure — `SAMPLE_DATA[timeframe]` is the only data source
            today; no live sectoral-index endpoint is wired yet. The badge
            previously hid in `isConnected` mode, which masked the fact that we
            were still showing sample figures even after a broker connection.
            Keep it visible at all times, and never imply the data is live
            (no auto-refresh, no "last updated" clock). */}
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live sectoral-index endpoint yet"
          title="No live data wired yet — showing sample sector performance so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
      </div>

      {/* Timeframe tabs */}
      <div
        className="flex-none flex items-center gap-px px-2.5 py-1.5 bg-surface-elevated border-b border-border-subtle"
        role="tablist"
        aria-label="Timeframe"
      >
        {TIMEFRAMES.map((tf) => (
          <button
            key={tf}
            role="tab"
            aria-selected={tf === timeframe}
            onClick={() => setTimeframe(tf)}
            className={cn(
              "px-2.5 py-0.5 text-xxs font-medium rounded transition-colors",
              tf === timeframe
                ? "bg-accent/15 text-accent border border-accent/30"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
          >
            {tf}
          </button>
        ))}
        <div className="flex-1" />
        <span className="text-xxs text-profit font-mono">{positiveCount}↑</span>
        <span className="mx-1 text-border-default">·</span>
        <span className="text-xxs text-loss font-mono">{negativeCount}↓</span>
      </div>

      {/* Bars */}
      <div
        className="flex-1 min-h-0 overflow-y-auto px-2.5 py-2 space-y-1.5"
        aria-label="Sector performance bars"
      >
        {sectors.map((entry) => (
          <BarRow key={entry.symbol} entry={entry} maxAbs={maxAbs} />
        ))}
      </div>
    </div>
  );
}

export default memo(SectorPerformanceWidget);
