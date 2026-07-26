/**
 * CalendarTab — daily P&L heat calendar over real journalled trades
 * (Trade Review tool, merge 2.12).
 *
 * Union of two retired surfaces:
 *   - The P&L Dashboard tool's Calendar tab supplied the real-data calendar:
 *     the 3-month grid, the ₹-magnitude colour ramp relative to the window's
 *     largest day, the summary strip, and the IST "today" semantics — the
 *     ring and the future-greying both compare ISO day keys against
 *     ``istToday()``, never a UTC date (``toISOString`` reads yesterday for
 *     the whole 00:00–05:29 IST window).
 *   - The HeatCalendar widget supplied the rendering affordances that
 *     survive: month navigation, the hover tooltip and the colour legend. Its
 *     data plane does not survive — it was sample-only (percentage returns
 *     invented by ``buildSampleData``), strictly dominated by this real-trade
 *     calendar; its %-threshold colour buckets are meaningless for ₹ P&L and
 *     are replaced by the magnitude-relative ramp.
 *
 * Data: daily net P&L via ``lib/journalAnalytics.computeDayPnl`` (IST day
 * buckets) over the auto-fill journal, fetched for the visible 3-month window
 * with the backend's maximum page size. Explore mode renders the disclosed
 * sample journal (badged); the backend is never queried.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Calendar, ChevronLeft, ChevronRight } from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { computeDayPnl } from "@/lib/journalAnalytics";
import { istParts, istToday } from "@/lib/ist";
import { getTradeJournal, type JournalTrade } from "@/services/ftApi";
import { useModeStore } from "@/stores/modeStore";
import { getSampleJournalTrades } from "./sampleJournal";

// ---------------------------------------------------------------------------
// Helpers (exported for tests)
// ---------------------------------------------------------------------------

/** Backend maximum page size for ``/api/v1/trades/journal``. */
const JOURNAL_MAX_LIMIT = 1000;

function pad2(value: number): string {
  return String(value).padStart(2, "0");
}

/** Days in a calendar month — pure day-number arithmetic, no host zone. */
function daysInMonth(year: number, month0: number): number {
  return new Date(Date.UTC(year, month0 + 1, 0)).getUTCDate();
}

export interface CalendarMonth {
  year: number;
  /** Month index, 0 = January. */
  month0: number;
  /** e.g. "Jul 26". */
  label: string;
}

/**
 * The three calendar months ending at the anchor month, oldest first, with the
 * inclusive ISO date window that covers them.
 */
export function monthWindow(year: number, month0: number): {
  months: CalendarMonth[];
  start: string;
  end: string;
} {
  const months: CalendarMonth[] = [];
  for (let i = 2; i >= 0; i--) {
    const d = new Date(year, month0 - i, 1);
    months.push({
      year: d.getFullYear(),
      month0: d.getMonth(),
      label: d.toLocaleString("en-IN", { month: "short", year: "2-digit" }),
    });
  }
  const first = months[0];
  const last = months[months.length - 1];
  return {
    months,
    start: `${first.year}-${pad2(first.month0 + 1)}-01`,
    end: `${last.year}-${pad2(last.month0 + 1)}-${pad2(daysInMonth(last.year, last.month0))}`,
  };
}

function formatINR(value: number): string {
  const abs = Math.abs(value);
  let formatted: string;
  if (abs >= 10_000_000) {
    formatted = `${(abs / 10_000_000).toFixed(2)}Cr`;
  } else if (abs >= 100_000) {
    formatted = `${(abs / 100_000).toFixed(2)}L`;
  } else if (abs >= 1_000) {
    formatted = `${(abs / 1_000).toFixed(2)}K`;
  } else {
    formatted = abs.toFixed(2);
  }
  return `${value < 0 ? "-" : ""}₹${formatted}`;
}

function pnlClass(v: number) {
  if (v > 0) return "text-profit";
  if (v < 0) return "text-loss";
  return "text-text-secondary";
}

/**
 * Heat cell colour: ₹ magnitude relative to the window's largest day (ported
 * from the P&L Dashboard calendar; replaces HeatCalendar's %-threshold ramp).
 */
export function heatmapColor(pnl: number, maxAbs: number): string {
  if (maxAbs === 0) return "bg-surface-elevated";
  const ratio = Math.abs(pnl) / maxAbs;
  if (pnl > 0) {
    if (ratio > 0.75) return "bg-emerald-600";
    if (ratio > 0.4) return "bg-emerald-700/80";
    return "bg-emerald-900/60";
  }
  if (pnl < 0) {
    if (ratio > 0.75) return "bg-red-600";
    if (ratio > 0.4) return "bg-red-700/80";
    return "bg-red-900/60";
  }
  return "bg-surface-elevated";
}

// ---------------------------------------------------------------------------
// Hover tooltip (ported from HeatCalendar, re-keyed to ₹ + trade count)
// ---------------------------------------------------------------------------

interface TooltipState {
  date: string;
  pnl: number;
  tradeCount: number;
  x: number;
  y: number;
}

function DayTooltip({ tip }: { tip: TooltipState }) {
  return (
    <div
      role="tooltip"
      className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded shadow-lg px-2.5 py-2 text-xs min-w-32.5"
      style={{ left: tip.x + 12, top: tip.y - 8 }}
    >
      <div className="font-semibold text-text-primary mb-1">{tip.date}</div>
      <div className={`font-mono font-semibold ${pnlClass(tip.pnl)}`}>
        {formatINR(tip.pnl)}
      </div>
      <div className="text-text-muted mt-0.5">
        {tip.tradeCount} trade{tip.tradeCount === 1 ? "" : "s"}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DOW_LABELS = ["M", "T", "W", "T", "F", "S", "S"];

export function CalendarTab() {
  const isExplore = useModeStore((s) => s.mode === "explore");

  // Anchor month defaults to the current IST month — a UTC/local read shows
  // last month for the whole IST early morning of the 1st.
  const initial = useMemo(() => istParts(), []);
  const [anchor, setAnchor] = useState<{ year: number; month0: number }>({
    year: initial.year,
    month0: initial.month,
  });
  const [tooltip, setTooltip] = useState<TooltipState | null>(null);

  const { months, start, end } = useMemo(
    () => monthWindow(anchor.year, anchor.month0),
    [anchor],
  );

  const journalQuery = useQuery({
    queryKey: ["tradeJournal", "calendar", start, end],
    queryFn: () => getTradeJournal(start, end, undefined, JOURNAL_MAX_LIMIT),
    enabled: !isExplore,
  });

  const sampleRows = useMemo<JournalTrade[]>(
    () => (isExplore ? getSampleJournalTrades(start, end, undefined, JOURNAL_MAX_LIMIT) : []),
    [isExplore, start, end],
  );
  const rows = isExplore ? sampleRows : journalQuery.data?.trades ?? [];

  const daily = useMemo(() => computeDayPnl(rows), [rows]);

  const pnlByDate = useMemo(() => {
    const m: Record<string, { pnl: number; tradeCount: number }> = {};
    daily.forEach(({ date, pnl, tradeCount }) => { m[date] = { pnl, tradeCount }; });
    return m;
  }, [daily]);

  const maxAbs = useMemo(
    () => Math.max(...daily.map((d) => Math.abs(d.pnl)), 1),
    [daily],
  );

  const totalPnl = daily.reduce((s, d) => s + d.pnl, 0);
  const tradingDays = daily.filter((d) => d.pnl !== 0).length;
  const greenDays = daily.filter((d) => d.pnl > 0).length;
  const redDays = daily.filter((d) => d.pnl < 0).length;

  // Both keys are ISO ``YYYY-MM-DD``, so a string compare is the calendar
  // compare — no re-parsing into a zone.
  const todayKey = istToday();

  function goBack() {
    setAnchor(({ year, month0 }) =>
      month0 === 0 ? { year: year - 1, month0: 11 } : { year, month0: month0 - 1 });
  }

  function goForward() {
    setAnchor(({ year, month0 }) =>
      month0 === 11 ? { year: year + 1, month0: 0 } : { year, month0: month0 + 1 });
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Daily P&L calendar">

      {/* Header: navigation (ported from HeatCalendar) + provenance */}
      <div className="flex-none flex items-center gap-2 px-3 py-1.5 bg-surface-card border-b border-border-default">
        <Calendar size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Daily P&L Calendar</span>
        {isExplore && (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            role="status"
            aria-label="Showing sample journal data — explore mode"
          >
            Sample data
          </span>
        )}
        {!isExplore && journalQuery.isError && (
          <span className="ml-1 text-xxs text-loss" role="status">Failed to load journal</span>
        )}
        <div className="flex-1" />
        <button
          onClick={goBack}
          aria-label="Previous month"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <ChevronLeft size={12} aria-hidden="true" />
        </button>
        <span className="text-xs text-text-primary font-medium tabular-nums w-28 text-center">
          {MONTH_NAMES[anchor.month0]} {anchor.year}
        </span>
        <button
          onClick={goForward}
          aria-label="Next month"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
        >
          <ChevronRight size={12} aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto px-3 py-2 space-y-3">

        {/* Summary strip */}
        <div className="grid grid-cols-4 gap-2">
          {[
            { label: "Total P&L", value: formatINR(totalPnl), pos: totalPnl >= 0 },
            { label: "Trading Days", value: String(tradingDays), pos: undefined },
            { label: "Green Days", value: String(greenDays), pos: true },
            { label: "Red Days", value: String(redDays), pos: redDays === 0 },
          ].map(({ label, value, pos }) => (
            <Card key={label} className="bg-surface-card border-border-default">
              <CardContent className="p-3">
                <div className="text-xs text-text-secondary uppercase tracking-wider mb-1">{label}</div>
                <div className={`text-base font-bold font-mono tabular-nums ${pos === undefined ? "text-text-primary" : pos ? "text-profit" : "text-loss"}`}>{value}</div>
              </CardContent>
            </Card>
          ))}
        </div>

        {/* Calendar heatmap — 3 months ending at the anchor month */}
        {months.map(({ year, month0, label }) => {
          const startOffsetRaw = new Date(year, month0, 1).getDay() - 1;
          const startOffset = startOffsetRaw < 0 ? 6 : startOffsetRaw;

          const cells: (number | null)[] = Array(startOffset).fill(null);
          for (let d = 1; d <= daysInMonth(year, month0); d++) cells.push(d);
          while (cells.length % 7 !== 0) cells.push(null);

          const monthPrefix = `${year}-${pad2(month0 + 1)}-`;
          const monthTotal = daily
            .filter((d) => d.date.startsWith(monthPrefix))
            .reduce((s, d) => s + d.pnl, 0);

          return (
            <Card key={`${year}-${month0}`} className="bg-surface-card border-border-default">
              <CardHeader className="p-3 pb-1">
                <div className="flex items-center justify-between">
                  <CardTitle className="text-xs font-medium text-text-secondary">{label}</CardTitle>
                  <span
                    className={`text-xs font-mono font-semibold tabular-nums ${pnlClass(monthTotal)}`}
                    aria-label={`${label} total P&L ${formatINR(monthTotal)}`}
                  >
                    {formatINR(monthTotal)}
                  </span>
                </div>
              </CardHeader>
              <CardContent className="p-3 pt-0">
                {/* Day-of-week header */}
                <div className="grid grid-cols-7 gap-1 mb-1">
                  {DOW_LABELS.map((l, i) => (
                    <div key={i} className="text-center text-xxs text-text-muted">{l}</div>
                  ))}
                </div>
                {/* Weeks */}
                {Array.from({ length: cells.length / 7 }).map((_, wi) => (
                  <div key={wi} className="grid grid-cols-7 gap-1 mb-1">
                    {cells.slice(wi * 7, wi * 7 + 7).map((day, di) => {
                      if (!day) return <div key={di} className="h-7" />;
                      const dateStr = `${monthPrefix}${pad2(day)}`;
                      const entry = pnlByDate[dateStr];
                      const isToday = dateStr === todayKey;
                      const isFuture = dateStr > todayKey;
                      return (
                        <div
                          key={di}
                          title={entry !== undefined ? `${dateStr}: ${formatINR(entry.pnl)}` : dateStr}
                          onMouseEnter={(e) =>
                            entry !== undefined &&
                            setTooltip({ date: dateStr, pnl: entry.pnl, tradeCount: entry.tradeCount, x: e.clientX, y: e.clientY })
                          }
                          onMouseMove={(e) =>
                            entry !== undefined &&
                            setTooltip({ date: dateStr, pnl: entry.pnl, tradeCount: entry.tradeCount, x: e.clientX, y: e.clientY })
                          }
                          onMouseLeave={() => setTooltip(null)}
                          className={`h-7 rounded flex items-center justify-center text-xxs font-mono cursor-default transition-colors
                            ${isFuture ? "bg-surface-base text-text-disabled" :
                              entry !== undefined ? `${heatmapColor(entry.pnl, maxAbs)} text-white/80` :
                              "bg-surface-elevated text-text-muted"}
                            ${isToday ? "ring-1 ring-ring" : ""}`}
                        >
                          {day}
                        </div>
                      );
                    })}
                  </div>
                ))}
              </CardContent>
            </Card>
          );
        })}

        {/* Legend (ported from HeatCalendar; buckets are relative to the
            window's largest daily ₹ move, not fixed % thresholds) */}
        <div className="flex items-center gap-1.5 flex-wrap">
          <span className="text-xxs text-text-muted">Legend:</span>
          {[
            { label: "Big loss", cls: "bg-red-600" },
            { label: "Loss", cls: "bg-red-700/80" },
            { label: "Flat / no trades", cls: "bg-surface-elevated" },
            { label: "Profit", cls: "bg-emerald-700/80" },
            { label: "Big profit", cls: "bg-emerald-600" },
          ].map(({ label, cls }) => (
            <div key={label} className="flex items-center gap-1">
              <div className={`w-3 h-3 rounded ${cls} border border-border-default`} />
              <span className="text-xxs text-text-muted">{label}</span>
            </div>
          ))}
        </div>
      </div>

      {tooltip && <DayTooltip tip={tooltip} />}
    </div>
  );
}
