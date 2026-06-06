/**
 * GapAnalysisWidget — Gap-up / gap-down analysis from historical data.
 *
 * Features:
 *   - Table of gap events: date, type, gap %, filled, fill time
 *   - Aggregate statistics: avg gap size, gap fill %, avg fill time
 *   - Scatter chart: gap size (X) vs fill probability (Y) with colour-coded dots
 *   - Symbol selector (NSE indices)
 *
 * DATA HONESTY: gap fill statistics (fill rate, fill time) require per-day
 * INTRADAY history that isn't cheaply available, so the widget shows
 * deterministic SAMPLE gap events with an always-visible "Sample data" badge.
 * It carries NO refresh control — a previous one only slept 700 ms and spun a
 * loader while the data never changed, which dishonestly implied a live fetch.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { ArrowUpFromLine } from "lucide-react";
import { FlintScatterChart } from "@flinttrade/design-system";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

type GapType = "gap-up" | "gap-down";

interface GapEvent {
  date: string;
  type: GapType;
  gapPct: number;
  filled: boolean;
  fillMinutes: number | null; // null = not filled
}

// ---------------------------------------------------------------------------
// Sample data — 20 gap events
// ---------------------------------------------------------------------------

export const SAMPLE_GAP_EVENTS: GapEvent[] = [
  { date: "2026-03-28", type: "gap-up",   gapPct:  0.82, filled: true,  fillMinutes:  34 },
  { date: "2026-03-27", type: "gap-down", gapPct: -1.24, filled: true,  fillMinutes:  61 },
  { date: "2026-03-26", type: "gap-up",   gapPct:  0.56, filled: true,  fillMinutes:  18 },
  { date: "2026-03-25", type: "gap-down", gapPct: -0.71, filled: true,  fillMinutes:  45 },
  { date: "2026-03-24", type: "gap-up",   gapPct:  1.38, filled: false, fillMinutes: null },
  { date: "2026-03-21", type: "gap-down", gapPct: -2.05, filled: false, fillMinutes: null },
  { date: "2026-03-20", type: "gap-up",   gapPct:  0.44, filled: true,  fillMinutes:  22 },
  { date: "2026-03-19", type: "gap-down", gapPct: -0.38, filled: true,  fillMinutes:  12 },
  { date: "2026-03-18", type: "gap-up",   gapPct:  0.95, filled: false, fillMinutes: null },
  { date: "2026-03-17", type: "gap-up",   gapPct:  0.62, filled: true,  fillMinutes:  29 },
  { date: "2026-03-14", type: "gap-down", gapPct: -1.61, filled: false, fillMinutes: null },
  { date: "2026-03-13", type: "gap-up",   gapPct:  0.33, filled: true,  fillMinutes:   9 },
  { date: "2026-03-12", type: "gap-down", gapPct: -0.91, filled: true,  fillMinutes:  53 },
  { date: "2026-03-11", type: "gap-up",   gapPct:  1.74, filled: false, fillMinutes: null },
  { date: "2026-03-10", type: "gap-down", gapPct: -0.52, filled: true,  fillMinutes:  36 },
  { date: "2026-03-07", type: "gap-up",   gapPct:  0.27, filled: true,  fillMinutes:   7 },
  { date: "2026-03-06", type: "gap-down", gapPct: -1.09, filled: false, fillMinutes: null },
  { date: "2026-03-05", type: "gap-up",   gapPct:  0.48, filled: true,  fillMinutes:  19 },
  { date: "2026-03-04", type: "gap-down", gapPct: -0.75, filled: true,  fillMinutes:  41 },
  { date: "2026-03-03", type: "gap-up",   gapPct:  1.12, filled: false, fillMinutes: null },
];

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];

// ---------------------------------------------------------------------------
// Stats computation
// ---------------------------------------------------------------------------

interface GapStats {
  total: number;
  gapUpCount: number;
  gapDownCount: number;
  fillCount: number;
  fillPct: number;
  avgGapSize: number;
  avgFillMinutes: number;
}

function computeStats(events: GapEvent[]): GapStats {
  if (events.length === 0) {
    return { total: 0, gapUpCount: 0, gapDownCount: 0, fillCount: 0, fillPct: 0, avgGapSize: 0, avgFillMinutes: 0 };
  }
  const gapUpCount = events.filter((e) => e.type === "gap-up").length;
  const gapDownCount = events.length - gapUpCount;
  const fillCount = events.filter((e) => e.filled).length;
  const fillPct = (fillCount / events.length) * 100;
  const avgGapSize = events.reduce((s, e) => s + Math.abs(e.gapPct), 0) / events.length;
  const filled = events.filter((e) => e.filled && e.fillMinutes !== null);
  const avgFillMinutes = filled.length > 0
    ? filled.reduce((s, e) => s + (e.fillMinutes ?? 0), 0) / filled.length
    : 0;
  return { total: events.length, gapUpCount, gapDownCount, fillCount, fillPct, avgGapSize, avgFillMinutes };
}

// ---------------------------------------------------------------------------
// Scatter chart — gap size (X) vs fill probability by bucket (Y dot)
// ---------------------------------------------------------------------------

const CHART_W = 340;
const CHART_H = 120;

interface ScatterProps {
  events: GapEvent[];
}

function ScatterChart({ events }: ScatterProps) {
  // Bucket by 0.25% gap size increments
  const buckets = useMemo(() => {
    const map = new Map<number, { total: number; filled: number }>();
    for (const e of events) {
      const key = Math.ceil(Math.abs(e.gapPct) * 4) / 4;
      const prev = map.get(key) ?? { total: 0, filled: 0 };
      map.set(key, { total: prev.total + 1, filled: prev.filled + (e.filled ? 1 : 0) });
    }
    return Array.from(map.entries())
      .sort(([a], [b]) => a - b)
      .map(([gapSize, { total, filled }]) => ({
        gapSize,
        fillPct: (filled / total) * 100,
        count: total,
      }));
  }, [events]);

  if (buckets.length === 0) {
    return <p className="text-xxs text-text-muted text-center py-4">No data</p>;
  }

  const maxGap = Math.max(...buckets.map((b) => b.gapSize), 0.25);

  return (
    <FlintScatterChart
      ariaLabel="Scatter chart: gap size vs fill probability"
      points={buckets.map((bucket) => ({
        id: `gap-${bucket.gapSize.toFixed(2)}`,
        label: `Gap ${bucket.gapSize.toFixed(2)}% fill rate ${bucket.fillPct.toFixed(0)}% (${bucket.count} events)`,
        x: bucket.gapSize,
        y: bucket.fillPct,
        radius: Math.min(6, 3 + Math.sqrt(bucket.count) * 1.2),
        color: bucket.fillPct >= 50 ? "rgba(34,197,94,0.75)" : "rgba(239,68,68,0.75)",
      }))}
      xDomain={[0, maxGap]}
      yDomain={[0, 100]}
      xTicks={[0.5, 1.0, 1.5, 2.0]}
      yTicks={[0, 25, 50, 75, 100]}
      xFormatter={(value) => `${value}%`}
      yFormatter={(value) => `${value}%`}
      xAxisLabel="Gap size ->"
      referenceLines={[{ axis: "y", value: 50, color: "rgba(99,102,241,0.3)", dash: "3,2" }]}
      width={CHART_W}
      height={CHART_H}
    />
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GapAnalysisWidget() {
  const track = useTrackBehavior();

  const [symbol, setSymbol] = useState("NIFTY");
  const [filter, setFilter] = useState<"all" | "gap-up" | "gap-down">("all");

  useEffect(() => {
    track("trade", "widget_view_gap_analysis");
  }, [track]);

  const filteredEvents = useMemo(
    () =>
      filter === "all"
        ? SAMPLE_GAP_EVENTS
        : SAMPLE_GAP_EVENTS.filter((e) => e.type === filter),
    [filter],
  );

  const stats = useMemo(() => computeStats(filteredEvents), [filteredEvents]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Gap Analysis widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <ArrowUpFromLine size={13} className="text-text-muted shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Gap Analysis</span>
        {/* Honest disclosure — the widget renders SAMPLE_GAP_EVENTS
            unconditionally (no gap-analysis backend is wired). The badge must
            stay visible even when a broker is connected. */}
        <span
          className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
          role="status"
          aria-label="Showing sample data; no live gap-analysis source is wired yet"
          title="No live data wired yet — showing sample gap events so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
      </div>

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-elevated border-b border-border-subtle">
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="h-6 w-32 text-xs bg-surface-hover border-border-default" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* Filter */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden" role="group" aria-label="Filter gap type">
          {(["all", "gap-up", "gap-down"] as const).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              aria-pressed={filter === f}
              className={cn(
                "px-2.5 py-0.5 text-xs font-medium capitalize transition-colors",
                filter === f
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
            >
              {f === "all" ? "All" : f === "gap-up" ? "Gap Up" : "Gap Down"}
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">

        {/* Stats summary */}
        <div className="px-2 pt-2 pb-1 grid grid-cols-4 gap-1.5">
          {[
            { label: "Total Gaps",  value: String(stats.total) },
            { label: "Fill Rate",   value: `${stats.fillPct.toFixed(1)}%` },
            { label: "Avg Size",    value: `${stats.avgGapSize.toFixed(2)}%` },
            { label: "Avg Fill",    value: stats.avgFillMinutes > 0 ? `${Math.round(stats.avgFillMinutes)}m` : "—" },
          ].map(({ label, value }) => (
            <div key={label} className="flex flex-col gap-0.5 bg-surface-hover rounded px-2 py-1.5 text-center">
              <span className="text-xxs text-text-muted">{label}</span>
              <span className="text-xs font-semibold font-mono text-text-primary">{value}</span>
            </div>
          ))}
        </div>

        {/* Gap Up / Down count pill */}
        <div className="flex items-center gap-2 px-2 py-1">
          <span className="text-xxs px-2 py-0.5 rounded-full bg-profit/15 text-profit font-medium">
            ↑ {stats.gapUpCount} up
          </span>
          <span className="text-xxs px-2 py-0.5 rounded-full bg-loss/15 text-loss font-medium">
            ↓ {stats.gapDownCount} down
          </span>
        </div>

        {/* Scatter chart */}
        <div className="px-2 pt-1 pb-2 border-b border-border-subtle">
          <p className="text-xxs text-text-muted font-medium uppercase tracking-wide mb-1">
            Gap size vs Fill probability
          </p>
          <ScatterChart events={filteredEvents} />
          <p className="text-xxs text-text-muted mt-1">Dot size = event count · Green = &gt;50% fill · Red = &lt;50%</p>
        </div>

        {/* Events table */}
        <div className="overflow-auto">
          <table className="w-full text-xs" aria-label={`Gap events for ${symbol}`}>
            <thead>
              <tr className="sticky top-0 bg-surface-card border-b border-border-default">
                <th className="text-left px-2 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Date</th>
                <th className="text-left px-2 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Type</th>
                <th className="text-right px-2 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Gap %</th>
                <th className="text-center px-2 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Filled</th>
                <th className="text-right px-2 py-1.5 text-xxs font-medium text-text-muted uppercase tracking-wide">Fill time</th>
              </tr>
            </thead>
            <tbody>
              {filteredEvents.map((e) => (
                <tr key={e.date} className="border-b border-border-subtle hover:bg-surface-hover transition-colors">
                  <td className="px-2 py-1.5 font-mono text-text-secondary">{e.date}</td>
                  <td className="px-2 py-1.5">
                    <span className={cn(
                      "px-1.5 py-0.5 rounded text-xxs font-medium",
                      e.type === "gap-up" ? "bg-profit/15 text-profit" : "bg-loss/15 text-loss",
                    )}>
                      {e.type === "gap-up" ? "↑ Gap Up" : "↓ Gap Down"}
                    </span>
                  </td>
                  <td className={cn("px-2 py-1.5 text-right font-mono tabular-nums", e.gapPct >= 0 ? "text-profit" : "text-loss")}>
                    {e.gapPct >= 0 ? "+" : ""}{e.gapPct.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {e.filled
                      ? <span className="text-profit font-bold">✓</span>
                      : <span className="text-loss text-xs">✗</span>
                    }
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono tabular-nums text-text-secondary">
                    {e.fillMinutes !== null ? `${e.fillMinutes}m` : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

export default memo(GapAnalysisWidget);
