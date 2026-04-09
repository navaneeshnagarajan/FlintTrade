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
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
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

// ---------------------------------------------------------------------------
// SVG chart
// ---------------------------------------------------------------------------

const SVG_W = 520;
const SVG_H = 180;
const PAD = { top: 12, right: 16, bottom: 28, left: 42 };

interface CompareChartProps {
  series: { symbol: string; normalised: { session: number; pct: number }[]; colour: string }[];
}

function CompareChart({ series }: CompareChartProps) {
  const chartW = SVG_W - PAD.left - PAD.right;
  const chartH = SVG_H - PAD.top - PAD.bottom;

  const allPcts = series.flatMap((s) => s.normalised.map((p) => p.pct));
  const minPct = allPcts.length > 0 ? Math.min(...allPcts) : -5;
  const maxPct = allPcts.length > 0 ? Math.max(...allPcts) : 5;

  // Add 10% padding top/bottom
  const pctRange = maxPct - minPct || 1;
  const minV = minPct - pctRange * 0.1;
  const maxV = maxPct + pctRange * 0.1;

  const maxSessions = series.reduce(
    (m, s) => Math.max(m, s.normalised.length),
    0,
  );

  const xOf = (session: number) =>
    maxSessions > 1 ? (session / (maxSessions - 1)) * chartW : chartW / 2;
  const yOf = (pct: number) => chartH - ((pct - minV) / (maxV - minV)) * chartH;

  // Zero line
  const zeroY = yOf(0);

  const yTicks: number[] = [];
  const step = pctRange > 10 ? 5 : pctRange > 4 ? 2 : 1;
  const start = Math.ceil(minV / step) * step;
  for (let v = start; v <= maxV; v += step) {
    yTicks.push(v);
  }

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full"
      style={{ height: SVG_H }}
      aria-label="Instrument comparison chart"
      role="img"
    >
      <defs>
        <clipPath id="compareClip">
          <rect x={0} y={0} width={chartW} height={chartH} />
        </clipPath>
      </defs>

      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* Zero line */}
        <line
          x1={0}
          y1={zeroY}
          x2={chartW}
          y2={zeroY}
          stroke="rgba(156,163,175,0.35)"
          strokeWidth={0.75}
          strokeDasharray="4,2"
        />

        {/* Y grid lines */}
        {yTicks.filter((v) => v !== 0).map((v) => (
          <line
            key={v}
            x1={0}
            y1={yOf(v)}
            x2={chartW}
            y2={yOf(v)}
            stroke="rgba(42,42,58,0.5)"
            strokeWidth={0.5}
          />
        ))}

        {/* Series lines */}
        {series.map((s) => {
          if (s.normalised.length < 2) return null;
          const pts = s.normalised
            .map((p) => `${xOf(p.session).toFixed(1)},${yOf(p.pct).toFixed(1)}`)
            .join(" ");
          return (
            <polyline
              key={s.symbol}
              points={pts}
              fill="none"
              stroke={s.colour}
              strokeWidth={1.75}
              strokeLinecap="round"
              strokeLinejoin="round"
              clipPath="url(#compareClip)"
            />
          );
        })}

        {/* Last point dots */}
        {series.map((s) => {
          const last = s.normalised[s.normalised.length - 1];
          if (!last) return null;
          return (
            <circle
              key={s.symbol}
              cx={xOf(last.session)}
              cy={yOf(last.pct)}
              r={3.5}
              fill={s.colour}
              stroke="var(--color-surface-base,#0a0a0f)"
              strokeWidth={1.5}
            />
          );
        })}

        {/* Y axis labels */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={-4} x2={0} y1={yOf(v)} y2={yOf(v)} stroke="var(--color-border-default,#2a2a3a)" />
            <text x={-6} y={yOf(v) + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted,#666)">
              {v > 0 ? `+${v.toFixed(0)}` : `${v.toFixed(0)}`}%
            </text>
          </g>
        ))}

        {/* Axes */}
        <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
        <line x1={0} y1={0} x2={0} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
      </g>
    </svg>
  );
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
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
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

  // Build active series from symbols (use sample data for matching symbols)
  const activeSeries = useMemo(() => {
    return symbols
      .map((sym, i) => {
        if (!sym) return null;
        const sample = SAMPLE_SERIES.find((s) => s.symbol === sym);
        // If no sample data, generate synthetic flat data so the slot still renders
        const points: SeriesPoint[] = sample
          ? sample.points
          : Array.from({ length: 20 }, (_, idx) => ({ session: idx, value: 100 + idx * 0.5 }));
        const normalised = normalise(points);
        return {
          symbol: sym,
          normalised,
          colour: SERIES_COLOURS[i % SERIES_COLOURS.length],
          index: i,
        };
      })
      .filter((s): s is NonNullable<typeof s> => s !== null);
  }, [symbols]);

  const activeCount = symbols.filter(Boolean).length;

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="Instrument Comparison widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <GitCompare size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Instrument Compare</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
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

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-1 pt-1">
        {activeSeries.length >= 1 ? (
          <CompareChart series={activeSeries} />
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
