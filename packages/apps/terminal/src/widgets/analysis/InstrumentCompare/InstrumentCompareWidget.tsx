/**
 * InstrumentCompareWidget — Normalised multi-instrument overlay chart.
 *
 * Features:
 *   - Up to 4 instruments overlaid on a single SVG chart
 *   - All series normalised to % change from the first data point (base = 0%)
 *   - Symbol input per slot (text input + clear button)
 *   - 4 distinct line colours; legend showing symbol + current % change
 *   - Useful for comparing NIFTY vs BANKNIFTY vs sector indices vs stocks
 *   - Sample data built-in; live data from /api/v1/history or /api/v1/quotes
 */

import { useState, useMemo, useCallback, memo } from "react";
import { GitCompare, X, Plus } from "lucide-react";
import { FlintMultiLineChart } from "@flinttrade/design-system";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface SeriesPoint {
  session: number;   // session index 0..N-1
  value: number;     // raw price
}

interface InstrumentSeries {
  symbol: string;
  points: SeriesPoint[];
}

// ---------------------------------------------------------------------------
// Colours (4 slots — fixed palette)
// ---------------------------------------------------------------------------

const SERIES_COLOURS = [
  "#6366f1", // indigo
  "#22c55e", // green
  "#f59e0b", // amber
  "#ec4899", // pink
];

// ---------------------------------------------------------------------------
// Sample data — 20 sessions per instrument
// ---------------------------------------------------------------------------

const SAMPLE_SERIES: InstrumentSeries[] = [
  {
    symbol: "NIFTY",
    points: [
      23100, 23250, 23180, 23420, 23310, 23560, 23480, 23700, 23620, 23850,
      23780, 24020, 23950, 24180, 24100, 24350, 24280, 24510, 24440, 24600,
    ].map((v, i) => ({ session: i, value: v })),
  },
  {
    symbol: "BANKNIFTY",
    points: [
      48200, 48450, 48320, 48780, 48590, 49100, 48980, 49350, 49200, 49700,
      49530, 50100, 49920, 50400, 50200, 50750, 50600, 51100, 50950, 51300,
    ].map((v, i) => ({ session: i, value: v })),
  },
  {
    symbol: "FINNIFTY",
    points: [
      21400, 21550, 21480, 21700, 21620, 21850, 21780, 22050, 21980, 22200,
      22130, 22380, 22310, 22550, 22480, 22720, 22650, 22900, 22830, 23050,
    ].map((v, i) => ({ session: i, value: v })),
  },
];

const DEFAULT_SYMBOLS = ["NIFTY", "BANKNIFTY", "", ""];
const MAX_SLOTS = 4;

// ---------------------------------------------------------------------------
// Normalise: returns % change from base
// ---------------------------------------------------------------------------

function normalise(points: SeriesPoint[]): { session: number; pct: number }[] {
  if (points.length === 0) return [];
  const base = points[0].value;
  if (base === 0) return points.map((p) => ({ session: p.session, pct: 0 }));
  return points.map((p) => ({
    session: p.session,
    pct: ((p.value - base) / base) * 100,
  }));
}

function buildComparisonChart(series: { symbol: string; normalised: { session: number; pct: number }[]; colour: string }[]) {
  const allPcts = series.flatMap((entry) => entry.normalised.map((point) => point.pct));
  const minPct = allPcts.length > 0 ? Math.min(...allPcts) : -5;
  const maxPct = allPcts.length > 0 ? Math.max(...allPcts) : 5;
  const pctRange = maxPct - minPct || 1;
  const minValue = minPct - pctRange * 0.1;
  const maxValue = maxPct + pctRange * 0.1;
  const maxSessions = series.reduce((max, entry) => Math.max(max, entry.normalised.length), 0);
  const maxSessionIndex = Math.max(maxSessions - 1, 1);
  const step = pctRange > 10 ? 5 : pctRange > 4 ? 2 : 1;
  const yTicks: number[] = [];
  const start = Math.ceil(minValue / step) * step;

  for (let value = start; value <= maxValue; value += step) {
    yTicks.push(value);
  }

  return {
    series: series.map((entry) => ({
      id: entry.symbol,
      label: entry.symbol,
      color: entry.colour,
      points: entry.normalised.map((point) => ({
        x: point.session,
        y: point.pct,
        label: `${entry.symbol} ${point.pct.toFixed(2)}%`,
      })),
    })),
    xDomain: [0, maxSessionIndex] as const,
    yDomain: [minValue, maxValue] as const,
    yTicks,
  };
}

// ---------------------------------------------------------------------------
// Symbol input slot
// ---------------------------------------------------------------------------

interface SymbolSlotProps {
  index: number;
  value: string;
  colour: string;
  onChange: (i: number, v: string) => void;
  onClear: (i: number) => void;
  disabled?: boolean;
}

function SymbolSlot({ index, value, colour, onChange, onClear, disabled }: SymbolSlotProps) {
  return (
    <div className="flex items-center gap-1">
      <span
        className="inline-block w-2.5 h-2.5 rounded-full flex-none"
        style={{ background: colour }}
        aria-hidden="true"
      />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(index, e.target.value.toUpperCase())}
        placeholder={disabled ? "Add symbol" : `Symbol ${index + 1}`}
        aria-label={`Instrument ${index + 1} symbol input`}
        disabled={disabled}
        className="w-24 px-1.5 py-0.5 text-xs bg-surface-hover border border-border-default rounded text-text-primary placeholder-text-muted focus:outline-none focus:border-accent/60 disabled:opacity-40"
        maxLength={20}
      />
      {value && (
        <button
          onClick={() => onClear(index)}
          aria-label={`Clear instrument ${index + 1}`}
          className="p-0.5 rounded text-text-muted hover:text-loss transition-colors"
        >
          <X size={10} aria-hidden="true" />
        </button>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Legend row
// ---------------------------------------------------------------------------

interface LegendRowProps {
  symbol: string;
  colour: string;
  currentPct: number | null;
}

function LegendRow({ symbol, colour, currentPct }: LegendRowProps) {
  const sign = currentPct !== null && currentPct >= 0 ? "+" : "";
  return (
    <div className="flex items-center gap-1.5 text-xxs">
      <span className="inline-block w-6 h-px" style={{ background: colour }} />
      <span className="text-text-primary font-medium">{symbol}</span>
      {currentPct !== null && (
        <span
          className={`font-mono tabular-nums ${currentPct >= 0 ? "text-profit" : "text-loss"}`}
          aria-label={`${symbol} ${sign}${currentPct.toFixed(2)}%`}
        >
          {sign}{currentPct.toFixed(2)}%
        </span>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function InstrumentCompareWidget() {
  const track = useTrackBehavior();
  // NOTE: We previously read `isConnected = useBrokerConnected()` to gate the
  // "Sample" badge on disconnect-only. The comparison series are still built
  // entirely from `SAMPLE_SERIES` (plus synthetic flat data for unknown
  // symbols) — no /api/v1/history or /api/v1/quotes fetch is wired yet — so the
  // badge is now unconditional. Hiding it while connected masked the fact that
  // a live user was still looking at sample data.
  const [symbols, setSymbols] = useState<string[]>(DEFAULT_SYMBOLS);

  const handleChange = useCallback((i: number, v: string) => {
    setSymbols((prev) => {
      const next = [...prev];
      next[i] = v;
      return next;
    });
    track("trade", "instrumentcompare_symbol_change");
  }, [track]);

  const handleClear = useCallback((i: number) => {
    setSymbols((prev) => {
      const next = [...prev];
      next[i] = "";
      return next;
    });
  }, []);

  // Series for the symbols that have illustrative data. A symbol WITHOUT any
  // is skipped, not invented: this used to synthesise `100 + idx * 0.5` for an
  // unknown symbol, so typing a real ticker drew a smooth rising line that
  // looked like that instrument's performance. The "Sample data" badge does
  // not excuse a fabricated series attributed to a named instrument.
  const activeSeries = useMemo(() => {
    return symbols
      .map((sym, i) => {
        if (!sym) return null;
        const sample = SAMPLE_SERIES.find((s) => s.symbol === sym);
        if (!sample) return null;
        return {
          symbol: sym,
          normalised: normalise(sample.points),
          colour: SERIES_COLOURS[i % SERIES_COLOURS.length],
          index: i,
        };
      })
      .filter((s): s is NonNullable<typeof s> => s !== null);
  }, [symbols]);

  /** Symbols the operator typed that this widget has no series for. */
  const unchartedSymbols = useMemo(
    () => symbols.filter((sym) => sym && !SAMPLE_SERIES.some((s) => s.symbol === sym)),
    [symbols],
  );

  const comparisonChart = useMemo(() => buildComparisonChart(activeSeries), [activeSeries]);
  const activeCount = symbols.filter(Boolean).length;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Instrument Comparison widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <GitCompare size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Instrument Compare</span>
        {/* Honest disclosure — the overlay series come solely from `SAMPLE_SERIES`
            (with synthetic flat data for unknown symbols); no live history/quote
            endpoint is wired yet. The badge previously hid in `isConnected` mode,
            which masked the fact that we were still showing sample data even
            after a broker connection. Keep visible at all times. */}
        <span
          className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
          role="status"
          aria-label="Showing sample data; no live data source is wired yet"
          title="No live data wired yet — showing sample comparison series so the widget is usable in explore mode."
        >
          Sample data
        </span>
        <div className="flex-1" />
        <span className="text-xxs text-text-muted">{activeCount}/{MAX_SLOTS} active</span>
      </div>

      {/* Symbol selectors */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card/40 border-b border-border-default flex-wrap">
        {symbols.map((sym, i) => (
          <SymbolSlot
            key={i}
            index={i}
            value={sym}
            colour={SERIES_COLOURS[i % SERIES_COLOURS.length]}
            onChange={handleChange}
            onClear={handleClear}
            disabled={i > 0 && !symbols.slice(0, i).some(Boolean) && !sym}
          />
        ))}
        {activeCount === 0 && (
          <span className="text-xxs text-text-muted flex items-center gap-1">
            <Plus size={9} aria-hidden="true" />
            Enter symbols to compare
          </span>
        )}
      </div>

      {/* Named, not drawn. A symbol with no illustrative series is listed here
          rather than given an invented line. */}
      {unchartedSymbols.length > 0 && (
        <p className="flex-none px-2 pb-1 text-xxs text-text-muted" role="note">
          No illustrative series for {unchartedSymbols.join(", ")} — this widget
          has no live price source, so nothing is drawn for {unchartedSymbols.length === 1 ? "it" : "them"}.
        </p>
      )}

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-1 pt-1">
        {activeSeries.length >= 1 ? (
          <FlintMultiLineChart
            ariaLabel="Instrument comparison chart"
            series={comparisonChart.series}
            xDomain={comparisonChart.xDomain}
            yDomain={comparisonChart.yDomain}
            yTicks={comparisonChart.yTicks}
            yFormatter={(value) => `${value > 0 ? "+" : ""}${value.toFixed(0)}%`}
            referenceLines={[{ axis: "y", value: 0, dash: "4,2" }]}
            width={520}
            height={180}
          />
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-text-muted">
            Enter at least one symbol above
          </div>
        )}
      </div>

      {/* Legend */}
      {activeSeries.length > 0 && (
        <div className="flex-none px-3 py-1.5 border-t border-border-default flex items-center gap-4 flex-wrap">
          {activeSeries.map((s) => {
            const last = s.normalised[s.normalised.length - 1];
            return (
              <LegendRow
                key={s.symbol}
                symbol={s.symbol}
                colour={s.colour}
                currentPct={last?.pct ?? null}
              />
            );
          })}
          <span className="ml-auto text-xxs text-text-muted">% change from open</span>
        </div>
      )}
    </div>
  );
}

export default memo(InstrumentCompareWidget);
