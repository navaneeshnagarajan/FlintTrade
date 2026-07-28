/**
 * SeasonalityWidget — monthly / weekday / day-of-month return patterns.
 *
 * Wires the previously-unconsumed `flinttrade_indicators.seasonality` module:
 * when a broker is connected the widget fetches ~10 years of daily bars via
 * the shared `/api/v1/history` path and runs them through the screener's
 * seasonality analyser (`/v1/analytics/seasonality`) — showing a "Live"
 * badge. Disconnected, it renders the deterministic SAMPLE statistics behind
 * an explicit guard with an amber "Sample data" badge; connected-but-failed
 * fetches show the error instead (fail closed — never sample rows as live).
 *
 * Follows the instrument broadcast on its FDC3 user channel (red by
 * default) with a local selector fallback, like the other analysis widgets.
 *
 * Panel params:
 *   `view` — "monthly" (default), "weekday" or "dom" (day-of-month);
 *   persisted via a PARTIAL `updateParameters` patch on change.
 *   `channel` — FDC3 user-channel membership (services/fdc3/channels.ts).
 */

import { memo, useCallback, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  CalendarClock,
  CalendarDays,
  CalendarRange,
  ChevronDown,
  Loader2,
} from "lucide-react";
import {
  FlintWeightedHeatmap,
  type FlintWeightedHeatmapEntry,
} from "@flinttrade/design-system";
import type { WidgetProps } from "@/types/widgets";
import type { WsInstrument } from "@/types/api";
import { useChannelInstrument, useChannelMembership } from "@/services/fdc3/hooks";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { fetchSeasonality, type SeasonalityData } from "./api";
import { SAMPLE_SEASONALITY } from "./sampleData";

// ---------------------------------------------------------------------------
// Panel params
// ---------------------------------------------------------------------------

/** Which calendar aggregation the heat strip shows. */
type SeasonalityView = "monthly" | "weekday" | "dom";

const VIEWS: readonly SeasonalityView[] = ["monthly", "weekday", "dom"];

const VIEW_LABELS: Record<SeasonalityView, string> = {
  monthly: "Monthly view",
  weekday: "Weekday view",
  dom: "Day-of-month view",
};

const VIEW_ICONS: Record<SeasonalityView, typeof CalendarRange> = {
  monthly: CalendarRange,
  weekday: CalendarDays,
  dom: CalendarClock,
};

/** Resolves the workspace `params.view` panel parameter, defaulting to monthly. */
function resolveView(value: unknown): SeasonalityView {
  return typeof value === "string" && (VIEWS as readonly string[]).includes(value)
    ? (value as SeasonalityView)
    : "monthly";
}

interface SeasonalityPanelParams {
  /** Initial calendar view. */
  view?: string;
  /** FDC3 user-channel membership — resolved through `channelFromParams`. */
  channel?: string;
}

// ---------------------------------------------------------------------------
// Instrument fallback
// ---------------------------------------------------------------------------

const FALLBACK_SYMBOLS: WsInstrument[] = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "RELIANCE", exchange: "NSE" },
  { symbol: "TCS", exchange: "NSE" },
  { symbol: "HDFCBANK", exchange: "NSE" },
];

// ---------------------------------------------------------------------------
// Heat-strip helpers
// ---------------------------------------------------------------------------

function formatPct(value: number, decimals = 2): string {
  const fixed = value.toFixed(decimals);
  return value > 0 ? `+${fixed}%` : `${fixed}%`;
}

/**
 * Return-heat tile colour: green for positive months/days, red for negative,
 * neutral grey near zero; opacity scales with magnitude within the view.
 */
function heatColour(value: number, maxAbs: number): string {
  if (!Number.isFinite(value) || maxAbs <= 0 || Math.abs(value) < 1e-9) {
    return "rgba(113, 113, 122, 0.35)";
  }
  const alpha = 0.25 + 0.55 * Math.min(Math.abs(value) / maxAbs, 1);
  return value > 0
    ? `rgba(34, 197, 94, ${alpha.toFixed(2)})`
    : `rgba(239, 68, 68, ${alpha.toFixed(2)})`;
}

function maxAbsReturn(values: number[]): number {
  return values.reduce(
    (acc, value) => (Number.isFinite(value) ? Math.max(acc, Math.abs(value)) : acc),
    0,
  );
}

function monthlyEntries(data: SeasonalityData): FlintWeightedHeatmapEntry[] {
  const maxAbs = maxAbsReturn(data.monthly.map((row) => row.avg_return_pct));
  return data.monthly.map((row) => ({
    id: `month-${row.month}`,
    label: row.month_name.slice(0, 3),
    valueLabel: formatPct(row.avg_return_pct),
    detailLabel: `${Math.round(row.positive_rate * 100)}% +ve · ${row.years_count}y`,
    weight: Math.max(Math.abs(row.avg_return_pct), 0.15),
    color: heatColour(row.avg_return_pct, maxAbs),
    textColor: "#ffffff",
  }));
}

function weekdayEntries(data: SeasonalityData): FlintWeightedHeatmapEntry[] {
  const maxAbs = maxAbsReturn(data.weekday.map((row) => row.avg_return_pct));
  return data.weekday.map((row) => ({
    id: `weekday-${row.weekday}`,
    label: row.weekday_name,
    valueLabel: formatPct(row.avg_return_pct, 3),
    detailLabel: `${Math.round(row.positive_rate * 100)}% +ve · ${row.sample_count}d`,
    weight: Math.max(Math.abs(row.avg_return_pct), 0.01),
    color: heatColour(row.avg_return_pct, maxAbs),
    textColor: "#ffffff",
  }));
}

function dayOfMonthEntries(data: SeasonalityData): FlintWeightedHeatmapEntry[] {
  const maxAbs = maxAbsReturn(data.day_of_month.map((row) => row.avg_return_pct));
  return data.day_of_month.map((row) => ({
    id: `dom-${row.day}`,
    label: `Day ${row.day}`,
    valueLabel: formatPct(row.avg_return_pct, 2),
    weight: 1, // equal-width grid: the colour carries the signal
    color: heatColour(row.avg_return_pct, maxAbs),
    textColor: "#ffffff",
  }));
}

// ---------------------------------------------------------------------------
// Local selector (fallback when no channel broadcast has arrived)
// ---------------------------------------------------------------------------

function Selector({
  value,
  options,
  onChange,
}: {
  value: string;
  options: string[];
  onChange: (v: string) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Selected symbol: ${value}`}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-20"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div
          className="absolute top-full right-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full max-h-48 overflow-y-auto"
          role="listbox"
          aria-label="Symbol selection"
        >
          {options.map((opt) => (
            <button
              key={opt}
              type="button"
              role="option"
              aria-selected={opt === value}
              onClick={() => {
                onChange(opt);
                setOpen(false);
              }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${opt === value ? "text-accent" : "text-text-primary"}`}
            >
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function SeasonalityWidget(props: WidgetProps) {
  const panelParams = props.params as SeasonalityPanelParams | undefined;
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();
  const channelInstrument = useChannelInstrument(
    useChannelMembership(props.api.id, props.params),
  );
  const [manual, setManual] = useState<WsInstrument | null>(null);
  const [view, setView] = useState<SeasonalityView>(() => resolveView(panelParams?.view));

  // The channel's broadcast wins unless the user picked one locally after that.
  const instrument = manual ?? channelInstrument ?? FALLBACK_SYMBOLS[0];

  const query = useQuery({
    queryKey: ["seasonality", instrument.symbol, instrument.exchange],
    queryFn: () => fetchSeasonality(instrument.symbol, instrument.exchange),
    enabled: isConnected,
    staleTime: 5 * 60_000,
    retry: false,
  });

  const live = query.data;
  const isLive = isConnected && live !== undefined && !live.is_sample_data;
  // Fail closed: connected shows ONLY analyser output (or a loading/error
  // state) — the sample statistics render exclusively behind this guard,
  // beside the amber badge below.
  const data: SeasonalityData | null = isConnected ? live ?? null : SAMPLE_SEASONALITY;
  // True only when fabricated rows are actually on screen (explore mode, or a
  // backend that flagged its own payload) — drives the amber affordances.
  const showingSample = !isConnected || (live !== undefined && live.is_sample_data);

  const entries = useMemo<FlintWeightedHeatmapEntry[]>(() => {
    if (!data) return [];
    if (view === "monthly") return monthlyEntries(data);
    if (view === "weekday") return weekdayEntries(data);
    return dayOfMonthEntries(data);
  }, [data, view]);

  // Best/worst month footer (monthly view only).
  const monthlyExtremes = useMemo(() => {
    if (!data || data.monthly.length === 0) return null;
    const best = data.monthly.reduce((a, b) => (b.avg_return_pct > a.avg_return_pct ? b : a));
    const worst = data.monthly.reduce((a, b) => (b.avg_return_pct < a.avg_return_pct ? b : a));
    return { best, worst };
  }, [data]);

  // Persist the chosen view into the panel params (PARTIAL patch only) so a
  // saved layout reopens on the same calendar aggregation.
  const handleViewChange = useCallback(
    (next: SeasonalityView) => {
      if (next === view) return;
      setView(next);
      props.api.updateParameters({ view: next });
      track("trade", "seasonality_view_change");
    },
    [props.api, track, view],
  );

  const handleSymbolSelect = useCallback(
    (symbol: string) => {
      setManual(FALLBACK_SYMBOLS.find((s) => s.symbol === symbol) ?? null);
      track("trade", "seasonality_symbol_change");
    },
    [track],
  );

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="Seasonality widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <CalendarRange size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Seasonality</span>
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-emerald-500/40 bg-emerald-500/10 px-1.5 py-0.5 text-[10px] font-medium text-emerald-400"
            role="status"
            aria-label="Live: seasonality computed from real daily price history"
            title="Live — calendar-return statistics computed from the connected broker's daily bars."
          >
            Live
          </span>
        ) : showingSample ? (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for live seasonality statistics"
            title="Sample calendar statistics so the widget is usable in explore mode — connect a broker for live seasonality from real price history."
          >
            Sample data
          </span>
        ) : null}
        {isConnected && query.isLoading && (
          <Loader2 size={12} className="animate-spin text-text-muted" aria-label="Loading" />
        )}
        <div className="flex-1" />

        {/* View toggle */}
        <div className="flex items-center gap-0.5 rounded border border-border-default p-0.5">
          {VIEWS.map((candidate) => {
            const Icon = VIEW_ICONS[candidate];
            return (
              <button
                key={candidate}
                type="button"
                onClick={() => handleViewChange(candidate)}
                className={`flex h-6 w-6 items-center justify-center rounded transition-colors ${
                  view === candidate
                    ? "bg-surface-hover text-text-primary"
                    : "text-text-muted hover:text-text-secondary"
                }`}
                aria-pressed={view === candidate}
                aria-label={VIEW_LABELS[candidate]}
                title={VIEW_LABELS[candidate]}
              >
                <Icon size={12} aria-hidden="true" />
              </button>
            );
          })}
        </div>

        <Selector
          value={instrument.symbol}
          options={FALLBACK_SYMBOLS.map((s) => s.symbol)}
          onChange={handleSymbolSelect}
        />
      </div>

      {/* Body */}
      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">
        <p className="text-[10px] text-text-muted">
          {instrument.symbol} · average {view === "monthly" ? "monthly" : "daily"} return by{" "}
          {view === "monthly" ? "calendar month" : view === "weekday" ? "trading weekday" : "day of month"}
          {showingSample && <span className="ml-1 text-amber-500">· Demo data</span>}
        </p>

        {data === null ? (
          <div className="flex-1 flex items-center justify-center py-8 text-xs text-text-muted text-center">
            {query.isLoading
              ? "Computing seasonality from daily history…"
              : query.error instanceof Error
                ? `Seasonality unavailable: ${query.error.message}`
                : "Seasonality unavailable — no daily history returned."}
          </div>
        ) : entries.length === 0 ? (
          <div className="flex-1 flex items-center justify-center py-8 text-xs text-text-muted text-center">
            Not enough history for this view.
          </div>
        ) : (
          <FlintWeightedHeatmap
            entries={entries}
            ariaLabel={`${instrument.symbol} ${VIEW_LABELS[view].toLowerCase()} seasonality heat strip`}
            minWidthPercent={view === "dom" ? 8 : 14}
            maxWidthPercent={view === "dom" ? 11 : 24}
          />
        )}

        {/* Footer summary — monthly extremes */}
        {data !== null && view === "monthly" && monthlyExtremes && (
          <div className="flex items-center gap-4 flex-wrap text-xxs text-text-muted border-t border-border-default pt-1.5">
            <span>
              Best month:{" "}
              <span className="text-profit font-medium">
                {monthlyExtremes.best.month_name} {formatPct(monthlyExtremes.best.avg_return_pct)}
              </span>
            </span>
            <span>
              Weakest month:{" "}
              <span className="text-loss font-medium">
                {monthlyExtremes.worst.month_name} {formatPct(monthlyExtremes.worst.avg_return_pct)}
              </span>
            </span>
            <span>{monthlyExtremes.best.years_count} years of history</span>
          </div>
        )}
      </div>
    </div>
  );
}

export default memo(SeasonalityWidget);
