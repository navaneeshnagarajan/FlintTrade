/**
 * EarningsCalendarWidget — Upcoming and past earnings results for FlintTrade.
 *
 * Features:
 *   - Monthly calendar grid with company earnings dates
 *   - Past dates: beat (green dot) / missed (red dot) / inline (grey dot)
 *   - Future dates: highlighted with accent colour
 *   - Filter by sector
 *   - Local sample data (with a visible "Sample data" badge) in explore
 *     mode; ft-api data in connected mode. The backend earnings source is
 *     currently synthetic-only and flags itself via is_sample_data, so the
 *     badge derives from the RESPONSE flag as well as connection state — a
 *     connected user still sees the badge while the rows are fabricated.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { ChevronLeft, ChevronRight, CalendarDays } from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { SAMPLE_EARNINGS, SAMPLE_SECTORS } from "./sampleData";
import type { EarningsEntry } from "./sampleData";
import { useQuery } from "@tanstack/react-query";
import { getEarningsCalendar } from "@/services/ftApi";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const DAY_LABELS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

function getMonthMatrix(year: number, month: number): (Date | null)[][] {
  const firstDay = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (Date | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => new Date(year, month, i + 1)),
  ];
  // Pad to complete last row
  while (cells.length % 7 !== 0) cells.push(null);
  const rows: (Date | null)[][] = [];
  for (let i = 0; i < cells.length; i += 7) rows.push(cells.slice(i, i + 7));
  return rows;
}

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

type ResultDot = "beat" | "missed" | "inline";

const DOT_CLASS: Record<ResultDot, string> = {
  beat: "bg-profit",
  missed: "bg-loss",
  inline: "bg-text-muted",
};

const DOT_LABEL: Record<ResultDot, string> = {
  beat: "Beat expectations",
  missed: "Missed expectations",
  inline: "In line with expectations",
};

// ---------------------------------------------------------------------------
// Day cell
// ---------------------------------------------------------------------------

interface DayCellProps {
  date: Date | null;
  entries: EarningsEntry[];
  isToday: boolean;
}

function DayCell({ date, entries, isToday }: DayCellProps) {
  if (!date) return <td className="border border-border-subtle bg-surface-base" />;

  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const isPast = date < today;
  const isFuture = date > today;

  return (
    <td
      className={cn(
        "border border-border-subtle p-1 align-top min-w-8 min-h-14",
        isToday && "bg-accent/10 border-accent/40",
        isFuture && !isToday && "bg-surface-elevated",
        isPast && "bg-surface-base",
      )}
    >
      <div
        className={cn(
          "text-xxs font-mono mb-0.5",
          isToday ? "text-accent font-bold" : "text-text-muted",
        )}
      >
        {date.getDate()}
      </div>
      <div className="flex flex-wrap gap-0.5">
        {entries.map((e) => (
          <div
            key={e.symbol}
            title={`${e.symbol} — ${e.result ? DOT_LABEL[e.result] : "Upcoming"}`}
            className={cn(
              "text-xxs px-1 py-px rounded font-mono leading-tight cursor-default",
              isFuture
                ? "bg-accent/20 text-accent border border-accent/30"
                : e.result === "beat"
                  ? "bg-profit/15 text-profit border border-profit/20"
                  : e.result === "missed"
                    ? "bg-loss/15 text-loss border border-loss/20"
                    : "bg-surface-hover text-text-secondary border border-border-subtle",
            )}
          >
            {e.result && (
              <span
                className={cn("inline-block w-1.5 h-1.5 rounded-full mr-0.5 align-middle", DOT_CLASS[e.result])}
                aria-label={DOT_LABEL[e.result]}
              />
            )}
            {e.symbol}
          </div>
        ))}
      </div>
    </td>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function EarningsCalendarWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const now = new Date();
  const [year, setYear] = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());
  const [sectorFilter, setSectorFilter] = useState<string>("all");

  useEffect(() => {
    track("trade", "widget_view_earnings_calendar");
  }, [track]);

  const { data: liveData } = useQuery({
    queryKey: ["earningsCalendar", year, month],
    queryFn: () => getEarningsCalendar(year, month + 1),
    enabled: isConnected,
    staleTime: 60 * 60 * 1000, // 1h
  });

  // The local SAMPLE constant is reserved for the not-connected/explore
  // branch only — when connected, the widget renders the backend rows (an
  // empty response shows an honest empty state, never the local constant).
  // BUT the backend earnings source is itself synthetic-only today and
  // declares it via is_sample_data, so the "Sample data" badge must key off
  // the response flag too: badging on `!isConnected` alone rendered
  // fabricated result dates and EPS estimates as live the moment a broker
  // connected.
  const liveEntries = (liveData?.entries as EarningsEntry[] | undefined) ?? [];
  const usingLocalSample = !isConnected;
  const showingSample = usingLocalSample || liveData?.is_sample_data === true;
  const allEntries: EarningsEntry[] = usingLocalSample ? SAMPLE_EARNINGS : liveEntries;
  const hasEntries = allEntries.length > 0;

  const sectors = useMemo(
    () => (usingLocalSample ? SAMPLE_SECTORS : [...new Set(allEntries.map((e) => e.sector))].sort()),
    [allEntries, usingLocalSample],
  );

  const filtered = useMemo(
    () =>
      sectorFilter === "all"
        ? allEntries
        : allEntries.filter((e) => e.sector === sectorFilter),
    [allEntries, sectorFilter],
  );

  const byDate = useMemo(() => {
    const map: Record<string, EarningsEntry[]> = {};
    for (const e of filtered) {
      if (!map[e.date]) map[e.date] = [];
      map[e.date].push(e);
    }
    return map;
  }, [filtered]);

  const matrix = useMemo(() => getMonthMatrix(year, month), [year, month]);

  const todayIso = toIsoDate(now);
  const monthLabel = new Date(year, month, 1).toLocaleString("en-IN", {
    month: "long",
    year: "numeric",
  });

  function prevMonth() {
    if (month === 0) { setYear((y) => y - 1); setMonth(11); }
    else setMonth((m) => m - 1);
  }

  function nextMonth() {
    if (month === 11) { setYear((y) => y + 1); setMonth(0); }
    else setMonth((m) => m + 1);
  }

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <CalendarDays size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Earnings Calendar</span>
        {showingSample && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample data
          </span>
        )}
        <div className="flex-1" />
        <Select value={sectorFilter} onValueChange={setSectorFilter}>
          <SelectTrigger className="h-6 w-28 text-xxs" aria-label="Filter by sector">
            <SelectValue placeholder="All sectors" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">All Sectors</SelectItem>
            {sectors.map((s) => (
              <SelectItem key={s} value={s} className="text-xs">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Month nav */}
      <div className="flex-none flex items-center justify-between px-3 py-1.5 bg-surface-elevated border-b border-border-subtle">
        <button
          onClick={prevMonth}
          className="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors"
          aria-label="Previous month"
        >
          <ChevronLeft size={14} aria-hidden="true" />
        </button>
        <span className="text-xs font-medium text-text-primary">{monthLabel}</span>
        <button
          onClick={nextMonth}
          className="p-0.5 rounded hover:bg-surface-hover text-text-muted hover:text-text-primary transition-colors"
          aria-label="Next month"
        >
          <ChevronRight size={14} aria-hidden="true" />
        </button>
      </div>

      {/* Legend */}
      <div className="flex-none flex items-center gap-3 px-3 py-1 bg-surface-base border-b border-border-subtle">
        {(["beat", "missed", "inline"] as const).map((r) => (
          <div key={r} className="flex items-center gap-1">
            <span className={cn("w-1.5 h-1.5 rounded-full inline-block", DOT_CLASS[r])} />
            <span className="text-xxs text-text-muted capitalize">{r}</span>
          </div>
        ))}
        <div className="flex items-center gap-1">
          <span className="w-1.5 h-1.5 rounded bg-accent/40 inline-block" />
          <span className="text-xxs text-text-muted">Upcoming</span>
        </div>
      </div>

      {/* Honest empty state — connected but no live earnings for this month.
          We never fall back to sample rows for a connected user. */}
      {!hasEntries && (
        <div className="flex-none px-3 py-2 text-xxs text-text-muted border-b border-border-subtle">
          No earnings results available for this month.
        </div>
      )}

      {/* Calendar grid */}
      <div className="flex-1 overflow-auto">
        <table className="w-full border-collapse table-fixed text-xs" aria-label="Earnings calendar">
          <thead>
            <tr>
              {DAY_LABELS.map((d) => (
                <th
                  key={d}
                  className="border border-border-subtle px-1 py-1 text-xxs font-medium text-text-muted bg-surface-card text-center"
                >
                  {d}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {matrix.map((row, ri) => (
              <tr key={ri}>
                {row.map((date, ci) => (
                  <DayCell
                    key={ci}
                    date={date}
                    entries={date ? (byDate[toIsoDate(date)] ?? []) : []}
                    isToday={date ? toIsoDate(date) === todayIso : false}
                  />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default memo(EarningsCalendarWidget);
