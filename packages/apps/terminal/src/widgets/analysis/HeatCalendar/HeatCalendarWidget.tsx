/**
 * HeatCalendarWidget — Monthly returns heatmap calendar for FlintTrade terminal.
 *
 * Features:
 *   - Monthly calendar grid coloured by daily return magnitude
 *   - Hover tooltip with exact return % and volume
 *   - Month/year navigation
 *   - Monthly return summary row
 *   - Sample data only — no live history endpoint is wired yet, so the
 *     "Sample data" badge is shown unconditionally (it must never imply the
 *     returns are live), mirroring SessionStatsWidget.
 */

import { useState, useMemo, useCallback, memo } from "react";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface DayReturn {
  date: string;      // ISO YYYY-MM-DD
  returnPct: number; // e.g. 1.23 means +1.23%
  volume: number;    // units
}

interface TooltipState {
  date: string;
  returnPct: number;
  volume: number;
  x: number;
  y: number;
}

// ---------------------------------------------------------------------------
// Sample data — covers current month window
// ---------------------------------------------------------------------------

function buildSampleData(year: number, month: number): DayReturn[] {
  const daysInMonth = new Date(year, month, 0).getDate();
  const seed = [1.2, -0.4, 2.8, -1.7, 0.3, -3.2, 0.8, 1.5, -0.9, 3.4,
                -2.1, 0.6, 1.1, -0.5, 2.3, -1.3, 0.7, -0.2, 1.9, -0.8,
                3.1, -2.6, 0.4, 1.6, -1.1, 2.0, -0.3, 0.9, -1.8, 0.5, 1.4];
  const result: DayReturn[] = [];
  for (let d = 1; d <= daysInMonth; d++) {
    const dow = new Date(year, month - 1, d).getDay();
    if (dow === 0 || dow === 6) continue; // skip weekends
    result.push({
      date: `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`,
      returnPct: seed[(d - 1) % seed.length],
      volume: Math.round(12_000_000 + seed[(d - 1) % seed.length] * 800_000),
    });
  }
  return result;
}

// ---------------------------------------------------------------------------
// Colour helpers
// ---------------------------------------------------------------------------

function returnColour(pct: number): string {
  if (pct <= -3) return "bg-[#7f1d1d] text-white";
  if (pct < -1) return "bg-[#b91c1c] text-white";
  if (pct < 1) return "bg-surface-hover text-text-secondary";
  if (pct < 3) return "bg-[#166534] text-white";
  return "bg-[#14532d] text-white";
}

function returnTextColour(pct: number): string {
  if (pct <= -3) return "text-[#fca5a5]";
  if (pct < -1) return "text-loss";
  if (pct < 0) return "text-[#fca5a5]";
  if (pct === 0) return "text-text-muted";
  if (pct < 1) return "text-text-muted";
  if (pct < 3) return "text-profit";
  return "text-[#86efac]";
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

function Tooltip({ tip }: { tip: TooltipState }) {
  const sign = tip.returnPct >= 0 ? "+" : "";
  const colourClass = tip.returnPct >= 0 ? "text-profit" : "text-loss";
  return (
    <div
      role="tooltip"
      className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded shadow-lg px-2.5 py-2 text-xs min-w-32.5"
      style={{ left: tip.x + 12, top: tip.y - 8 }}
    >
      <div className="font-semibold text-text-primary mb-1">{tip.date}</div>
      <div className={`font-mono font-semibold ${colourClass}`}>
        {sign}{tip.returnPct.toFixed(2)}%
      </div>
      <div className="text-text-muted mt-0.5">
        Vol: {(tip.volume / 1_000_000).toFixed(2)}M
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Calendar grid
// ---------------------------------------------------------------------------

const DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri"];

interface CalendarGridProps {
  year: number;
  month: number;
  days: DayReturn[];
  onHover: (tip: TooltipState | null) => void;
}

function CalendarGrid({ year, month, days, onHover }: CalendarGridProps) {
  // Build a map for fast lookup
  const byDate = useMemo(() => {
    const m = new Map<string, DayReturn>();
    days.forEach((d) => m.set(d.date, d));
    return m;
  }, [days]);

  // First day of month (Mon=0 offset)
  const firstDow = new Date(year, month - 1, 1).getDay();
  const offset = firstDow === 0 ? 6 : firstDow - 1; // Mon-based grid
  const daysInMonth = new Date(year, month, 0).getDate();

  const cells: Array<{ day: number | null }> = [];
  for (let i = 0; i < offset; i++) cells.push({ day: null });
  for (let d = 1; d <= daysInMonth; d++) cells.push({ day: d });

  return (
    <div aria-label="Monthly returns calendar grid">
      {/* Day-of-week header */}
      <div className="grid grid-cols-5 gap-px mb-1">
        {DOW_LABELS.map((lbl) => (
          <div key={lbl} className="text-center text-xxs text-text-muted py-0.5 font-medium">
            {lbl}
          </div>
        ))}
      </div>

      {/* Cells — only Mon–Fri columns */}
      <div className="grid grid-cols-5 gap-px">
        {cells.map((cell, idx) => {
          if (cell.day === null) {
            return <div key={`e-${idx}`} className="h-9 rounded" />;
          }
          const dateStr = `${year}-${String(month).padStart(2, "0")}-${String(cell.day).padStart(2, "0")}`;
          const entry = byDate.get(dateStr);
          // Skip weekend cells that fall in Mon-Fri grid columns
          const dow = new Date(year, month - 1, cell.day).getDay();
          if (dow === 0 || dow === 6) {
            return <div key={`s-${idx}`} className="h-9 rounded opacity-0" />;
          }

          if (!entry) {
            return (
              <div
                key={dateStr}
                className="h-9 rounded bg-surface-hover/30 flex items-center justify-center"
              >
                <span className="text-xxs text-text-muted">{cell.day}</span>
              </div>
            );
          }

          const sign = entry.returnPct >= 0 ? "+" : "";
          return (
            <div
              key={dateStr}
              className={`h-9 rounded flex flex-col items-center justify-center cursor-default select-none transition-opacity hover:opacity-80 ${returnColour(entry.returnPct)}`}
              onMouseEnter={(e) =>
                onHover({
                  date: dateStr,
                  returnPct: entry.returnPct,
                  volume: entry.volume,
                  x: e.clientX,
                  y: e.clientY,
                })
              }
              onMouseMove={(e) =>
                onHover({
                  date: dateStr,
                  returnPct: entry.returnPct,
                  volume: entry.volume,
                  x: e.clientX,
                  y: e.clientY,
                })
              }
              onMouseLeave={() => onHover(null)}
              aria-label={`${dateStr}: ${sign}${entry.returnPct.toFixed(2)}%`}
            >
              <span className="text-xxs opacity-70 leading-none">{cell.day}</span>
              <span className="text-xxs font-mono font-semibold leading-none mt-0.5">
                {sign}{entry.returnPct.toFixed(1)}%
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

function HeatCalendarWidget() {
  const track = useTrackBehavior();
  // NOTE: We previously read `isConnected = useBrokerConnected()` to gate the
  // "Sample" badge on disconnect-only. The widget always renders
  // `buildSampleData()` because no live history endpoint exists yet, so the
  // badge is now unconditional (see header comment) and the hook is unused.

  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth() + 1);
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const days = useMemo(() => buildSampleData(year, month), [year, month]);

  const monthlyTotal = useMemo(
    () => days.reduce((sum, d) => sum + d.returnPct, 0),
    [days],
  );

  const goBack = useCallback(() => {
    setMonth((m) => {
      if (m === 1) { setYear((y) => y - 1); return 12; }
      return m - 1;
    });
    track("trade", "heatcalendar_nav_back");
  }, [track]);

  const goForward = useCallback(() => {
    setMonth((m) => {
      if (m === 12) { setYear((y) => y + 1); return 1; }
      return m + 1;
    });
    track("trade", "heatcalendar_nav_forward");
  }, [track]);

  const sign = monthlyTotal >= 0 ? "+" : "";
  const totalColour = returnTextColour(monthlyTotal);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Calendar size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Heat Calendar</span>
        {/* Honest disclosure — `buildSampleData()` is the only data source
            today; no live history endpoint is wired yet. The badge previously
            hid in `isConnected` mode, which masked the fact that we were still
            showing sample returns even after a broker connection. Keep visible
            at all times so nothing implies these returns are live. */}
        <span
          className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live data source is wired yet"
          title="No live data wired yet — showing sample returns so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />

        {/* Month navigation */}
        <button
          onClick={goBack}
          aria-label="Previous month"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <ChevronLeft size={12} aria-hidden="true" />
        </button>
        <span className="text-xs text-text-primary font-medium tabular-nums w-28 text-center">
          {MONTH_NAMES[month - 1]} {year}
        </span>
        <button
          onClick={goForward}
          aria-label="Next month"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <ChevronRight size={12} aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-3">

        {/* Calendar grid */}
        <CalendarGrid
          year={year}
          month={month}
          days={days}
          onHover={setTooltip}
        />

        {/* Monthly summary row */}
        <div className="bg-surface-card border border-border-default rounded p-2 flex items-center justify-between">
          <span className="text-xxs text-text-muted uppercase tracking-wide">Monthly Total Return</span>
          <span className={`text-sm font-mono font-semibold tabular-nums ${totalColour}`}>
            {sign}{monthlyTotal.toFixed(2)}%
          </span>
        </div>

        {/* Legend */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xxs text-text-muted">Legend:</span>
          {[
            { label: "≤ -3%", cls: "bg-[#7f1d1d]" },
            { label: "-1 to -3%", cls: "bg-[#b91c1c]" },
            { label: "±1%", cls: "bg-surface-hover" },
            { label: "+1 to +3%", cls: "bg-[#166534]" },
            { label: "≥ +3%", cls: "bg-[#14532d]" },
          ].map(({ label, cls }) => (
            <div key={label} className="flex items-center gap-1">
              <div className={`w-3 h-3 rounded ${cls} border border-border-default`} />
              <span className="text-xxs text-text-muted">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {tooltip && <Tooltip tip={tooltip} />}
    </div>
  );
}

export default memo(HeatCalendarWidget);
