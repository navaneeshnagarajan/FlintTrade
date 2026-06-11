/**
 * EconomicCalendarWidget — Upcoming economic events for FlintTrade terminal.
 *
 * Timeline view of RBI policy, US Fed, GDP, CPI, and other key events.
 * Filter by country and impact level.
 * Colour-coded: red=high, amber=medium, green=low impact.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { CalendarClock, ChevronDown, ChevronUp } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { getEconomicCalendar, type BackendEconomicEvent } from "@/services/ftApi";
import {
  SAMPLE_EVENTS,
  COUNTRY_FLAGS,
  COUNTRY_LABELS,
} from "./sampleData";
import type { EconomicEvent, Impact, Country } from "./sampleData";

/** Country codes the widget can render (flag + label maps). */
const KNOWN_COUNTRIES = new Set<string>(Object.keys(COUNTRY_FLAGS));

/** Map the backend's macro-event rows to the widget's event shape. */
function mapBackendEvents(rows: BackendEconomicEvent[]): EconomicEvent[] {
  return rows
    .filter((r) => KNOWN_COUNTRIES.has(r.country))
    .map((r, i) => ({
      id: `${r.date}-${i}-${r.event}`,
      date: r.date,
      timeIst: r.time,
      name: r.event,
      country: r.country as Country,
      impact: r.impact,
      previous: r.previous ?? undefined,
      forecast: r.forecast ?? undefined,
      actual: r.actual ?? undefined,
    }));
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IMPACT_COLOURS: Record<Impact, string> = {
  high:   "bg-loss   text-white",
  medium: "bg-warning text-black",
  low:    "bg-profit  text-white",
};

const IMPACT_DOT: Record<Impact, string> = {
  high:   "bg-loss",
  medium: "bg-warning",
  low:    "bg-profit",
};

const IMPACT_LABELS: Record<Impact, string> = {
  high: "High",
  medium: "Medium",
  low: "Low",
};

const COUNTRIES = Object.keys(COUNTRY_FLAGS) as Country[];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function toIsoDate(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function formatEventDate(iso: string): string {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short" });
}

function isToday(iso: string): boolean {
  return iso === toIsoDate(new Date());
}

function isPast(iso: string): boolean {
  const today = toIsoDate(new Date());
  return iso < today;
}

// ---------------------------------------------------------------------------
// Event row
// ---------------------------------------------------------------------------

interface EventRowProps {
  event: EconomicEvent;
  past: boolean;
}

function EventRow({ event, past }: EventRowProps) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div
      className={cn(
        "border-b border-border-subtle px-3 py-2 transition-colors",
        past ? "opacity-60 hover:opacity-100" : "hover:bg-surface-hover",
      )}
    >
      <div className="flex items-start gap-2.5">
        {/* Impact dot */}
        <div className="mt-0.5 shrink-0 flex flex-col items-center gap-1">
          <div className={cn("w-2 h-2 rounded-full shrink-0", IMPACT_DOT[event.impact])} aria-label={`${IMPACT_LABELS[event.impact]} impact`} />
        </div>

        {/* Country flag */}
        <span className="text-sm shrink-0" aria-label={COUNTRY_LABELS[event.country]} role="img">
          {COUNTRY_FLAGS[event.country]}
        </span>

        {/* Main content */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-xs font-medium text-text-primary leading-tight">{event.name}</span>
            <span className={cn(
              "text-xxs font-medium px-1 py-0.5 rounded leading-none",
              IMPACT_COLOURS[event.impact],
            )}>
              {IMPACT_LABELS[event.impact]}
            </span>
            {event.actual && (
              <span className="text-xxs text-profit font-mono font-semibold">
                A: {event.actual}
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5">
            <span className="text-xxs text-text-muted font-mono tabular-nums">{event.timeIst} IST</span>
            {(event.forecast || event.previous) && (
              <button
                onClick={() => setExpanded((v) => !v)}
                className="flex items-center gap-0.5 text-xxs text-text-muted hover:text-text-secondary transition-colors"
                aria-expanded={expanded}
                aria-label={`${expanded ? "Collapse" : "Expand"} ${event.name} details`}
              >
                {expanded ? <ChevronUp size={10} aria-hidden="true" /> : <ChevronDown size={10} aria-hidden="true" />}
                Details
              </button>
            )}
          </div>

          {/* Expanded details */}
          {expanded && (
            <div className="mt-1.5 flex items-center gap-4 text-xxs font-mono">
              {event.previous && (
                <div>
                  <span className="text-text-muted">Prev </span>
                  <span className="text-text-secondary tabular-nums">{event.previous}</span>
                </div>
              )}
              {event.forecast && (
                <div>
                  <span className="text-text-muted">Fcst </span>
                  <span className="text-accent tabular-nums">{event.forecast}</span>
                </div>
              )}
              {event.actual && (
                <div>
                  <span className="text-text-muted">Actual </span>
                  <span className="text-profit tabular-nums">{event.actual}</span>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Date group
// ---------------------------------------------------------------------------

interface DateGroupProps {
  date: string;
  events: EconomicEvent[];
}

function DateGroup({ date, events }: DateGroupProps) {
  const today = isToday(date);
  const past = isPast(date);

  return (
    <div>
      <div className={cn(
        "px-3 py-1 flex items-center gap-2 sticky top-0 z-10 border-b border-border-default",
        today
          ? "bg-accent/10 border-accent/30"
          : past
            ? "bg-surface-base"
            : "bg-surface-elevated",
      )}>
        <span className={cn(
          "text-xxs font-semibold uppercase tracking-wide",
          today ? "text-accent" : "text-text-muted",
        )}>
          {today ? "Today" : formatEventDate(date)}
        </span>
        <span className="text-xxs text-text-muted">{events.length} event{events.length !== 1 ? "s" : ""}</span>
      </div>
      {events.map((ev) => (
        <EventRow key={ev.id} event={ev} past={past && !today} />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function EconomicCalendarWidget() {
  const track = useTrackBehavior();

  const [countryFilter, setCountryFilter] = useState<Country | "all">("all");
  const [impactFilter, setImpactFilter] = useState<Impact | "all">("all");

  useEffect(() => {
    track("trade", "widget_view_economic_calendar");
  }, [track]);

  // Backend is the source of truth (its provider generates a deterministic
  // sample schedule today — see getEconomicCalendar); the bundled
  // SAMPLE_EVENTS are only the offline fallback.
  const calendarQuery = useQuery({
    queryKey: ["economicCalendar"],
    queryFn: () => getEconomicCalendar(30),
  });
  const events = useMemo<EconomicEvent[]>(() => {
    const mapped = calendarQuery.data ? mapBackendEvents(calendarQuery.data.events) : [];
    return mapped.length > 0 ? mapped : SAMPLE_EVENTS;
  }, [calendarQuery.data]);

  const filtered = useMemo(() => {
    return events.filter((ev) => {
      if (countryFilter !== "all" && ev.country !== countryFilter) return false;
      if (impactFilter !== "all" && ev.impact !== impactFilter) return false;
      return true;
    }).sort((a, b) => {
      if (a.date !== b.date) return a.date.localeCompare(b.date);
      return a.timeIst.localeCompare(b.timeIst);
    });
  }, [events, countryFilter, impactFilter]);

  const byDate = useMemo(() => {
    const map = new Map<string, EconomicEvent[]>();
    for (const ev of filtered) {
      const arr = map.get(ev.date) ?? [];
      arr.push(ev);
      map.set(ev.date, arr);
    }
    return map;
  }, [filtered]);

  const sortedDates = useMemo(() => [...byDate.keys()].sort(), [byDate]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <CalendarClock size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Economic Calendar</span>
        {/* Honest disclosure — the backend calendar provider generates a
            deterministic sample schedule (no live macro feed is integrated),
            and the bundled events are the offline fallback. The badge stays
            until the provider gains a real data source. */}
        <span
          className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400 ml-1"
          role="status"
          aria-label="Showing sample data; the calendar provider has no live macro feed yet"
          title="Sample economic schedule — served by the backend's calendar provider, which has no live macro feed integrated yet."
        >
          Sample data
        </span>
        <div className="flex-1" />
        <div className="flex items-center gap-1.5">
          {(["high", "medium", "low"] as Impact[]).map((i) => (
            <div key={i} className="flex items-center gap-1">
              <span className={cn("w-1.5 h-1.5 rounded-full", IMPACT_DOT[i])} aria-hidden="true" />
              <span className="text-xxs text-text-muted capitalize">{i}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Filters */}
      <div className="flex-none flex items-center gap-2 px-3 py-1.5 bg-surface-elevated border-b border-border-subtle">
        <Select value={countryFilter} onValueChange={(v) => setCountryFilter(v as Country | "all")}>
          <SelectTrigger className="h-6 w-28 text-xxs" aria-label="Filter by country">
            <SelectValue placeholder="All countries" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">All Countries</SelectItem>
            {COUNTRIES.map((c) => (
              <SelectItem key={c} value={c} className="text-xs">
                {COUNTRY_FLAGS[c]} {COUNTRY_LABELS[c]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Select value={impactFilter} onValueChange={(v) => setImpactFilter(v as Impact | "all")}>
          <SelectTrigger className="h-6 w-28 text-xxs" aria-label="Filter by impact">
            <SelectValue placeholder="All impact" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all" className="text-xs">All Impact</SelectItem>
            <SelectItem value="high" className="text-xs">High</SelectItem>
            <SelectItem value="medium" className="text-xs">Medium</SelectItem>
            <SelectItem value="low" className="text-xs">Low</SelectItem>
          </SelectContent>
        </Select>

        <span className="text-xxs text-text-muted ml-auto">
          {filtered.length} events
        </span>
      </div>

      {/* Timeline */}
      <div className="flex-1 overflow-auto" aria-label="Economic events timeline" role="list">
        {sortedDates.length === 0 ? (
          <div className="flex items-center justify-center h-full text-text-muted text-sm">
            No events match the selected filters
          </div>
        ) : (
          sortedDates.map((date) => (
            <DateGroup
              key={date}
              date={date}
              events={byDate.get(date) ?? []}
            />
          ))
        )}
      </div>
    </div>
  );
}

export default memo(EconomicCalendarWidget);
