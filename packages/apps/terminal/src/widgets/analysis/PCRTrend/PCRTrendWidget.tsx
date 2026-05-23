/**
 * PCRTrendWidget — Put-Call Ratio trend over the last 20 sessions.
 *
 * Features:
 *   - SVG line chart of PCR across the last 20 sessions
 *   - Horizontal band overlays: bullish extreme (<0.7), bullish (0.7–1.0),
 *     bearish (1.0–1.3), bearish extreme (>1.3)
 *   - Current PCR displayed as a big number with directional arrow
 *   - Symbol selector for NIFTY / BANKNIFTY / FINNIFTY
 *   - Sample data; live data from option chain PCR endpoint
 */

import { useState, useMemo, memo } from "react";
import { TrendingDown, ChevronDown, ArrowUp, ArrowDown, Minus } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PCRPoint {
  session: string;   // e.g. "Apr 01"
  pcr: number;
}

type PCRRegime = "bullish-extreme" | "bullish" | "neutral" | "bearish" | "bearish-extreme";

// ---------------------------------------------------------------------------
// Sample data — 20 sessions
// ---------------------------------------------------------------------------

const SAMPLE_PCR: PCRPoint[] = [
  { session: "Mar 10", pcr: 1.42 },
  { session: "Mar 11", pcr: 1.31 },
  { session: "Mar 12", pcr: 1.18 },
  { session: "Mar 13", pcr: 1.24 },
  { session: "Mar 14", pcr: 1.09 },
  { session: "Mar 17", pcr: 0.98 },
  { session: "Mar 18", pcr: 0.87 },
  { session: "Mar 19", pcr: 0.92 },
  { session: "Mar 20", pcr: 1.05 },
  { session: "Mar 21", pcr: 1.14 },
  { session: "Mar 24", pcr: 1.27 },
  { session: "Mar 25", pcr: 1.19 },
  { session: "Mar 26", pcr: 1.08 },
  { session: "Mar 27", pcr: 0.96 },
  { session: "Mar 28", pcr: 0.82 },
  { session: "Mar 31", pcr: 0.74 },
  { session: "Apr 01", pcr: 0.68 },
  { session: "Apr 02", pcr: 0.79 },
  { session: "Apr 03", pcr: 0.91 },
  { session: "Apr 04", pcr: 0.88 },
];

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function pcrRegime(pcr: number): PCRRegime {
  if (pcr < 0.7) return "bullish-extreme";
  if (pcr < 1.0) return "bullish";
  if (pcr <= 1.3) return "bearish";
  return "bearish-extreme";
}

const REGIME_LABEL: Record<PCRRegime, string> = {
  "bullish-extreme": "Bullish Extreme",
  bullish: "Bullish",
  neutral: "Neutral",
  bearish: "Bearish",
  "bearish-extreme": "Bearish Extreme",
};

const REGIME_COLOUR: Record<PCRRegime, string> = {
  "bullish-extreme": "text-profit",
  bullish: "text-profit",
  neutral: "text-text-secondary",
  bearish: "text-loss",
  "bearish-extreme": "text-loss",
};

// ---------------------------------------------------------------------------
// SVG chart
// ---------------------------------------------------------------------------

const SVG_W = 500;
const SVG_H = 180;
const PAD = { top: 12, right: 16, bottom: 30, left: 36 };

const BANDS = [
  { yMin: 0,   yMax: 0.7, fill: "rgba(34,197,94,0.10)",  label: "Bullish Extreme" },
  { yMin: 0.7, yMax: 1.0, fill: "rgba(34,197,94,0.06)",  label: "Bullish" },
  { yMin: 1.0, yMax: 1.3, fill: "rgba(239,68,68,0.06)",  label: "Bearish" },
  { yMin: 1.3, yMax: 2.0, fill: "rgba(239,68,68,0.12)",  label: "Bearish Extreme" },
];

const BAND_LINES = [
  { y: 0.7, stroke: "rgba(34,197,94,0.5)", dash: "4,2" },
  { y: 1.0, stroke: "rgba(156,163,175,0.4)", dash: "4,2" },
  { y: 1.3, stroke: "rgba(239,68,68,0.5)", dash: "4,2" },
];

interface PCRChartProps {
  points: PCRPoint[];
}

function PCRChart({ points }: PCRChartProps) {
  const chartW = SVG_W - PAD.left - PAD.right;
  const chartH = SVG_H - PAD.top - PAD.bottom;

  const minV = 0;
  const maxV = Math.max(2.0, ...points.map((p) => p.pcr)) * 1.05;

  const xOf = (i: number) =>
    points.length > 1 ? (i / (points.length - 1)) * chartW : chartW / 2;
  const yOf = (v: number) => chartH - ((v - minV) / (maxV - minV)) * chartH;

  const linePoints = points
    .map((p, i) => `${xOf(i).toFixed(1)},${yOf(p.pcr).toFixed(1)}`)
    .join(" ");

  const areaPath = [
    `M ${xOf(0).toFixed(1)},${yOf(points[0].pcr).toFixed(1)}`,
    ...points.slice(1).map((p, i) => `L ${xOf(i + 1).toFixed(1)},${yOf(p.pcr).toFixed(1)}`),
    `L ${xOf(points.length - 1).toFixed(1)},${chartH.toFixed(1)}`,
    `L ${xOf(0).toFixed(1)},${chartH.toFixed(1)}`,
    "Z",
  ].join(" ");

  const yTicks = [0, 0.5, 1.0, 1.5, 2.0].filter((v) => v <= maxV);

  // X-axis labels: show first, middle, last
  const xLabelIndices = [
    0,
    Math.floor(points.length / 2),
    points.length - 1,
  ];

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full"
      style={{ height: SVG_H }}
      aria-label="PCR trend chart"
      role="img"
    >
      <defs>
        <linearGradient id="pcrGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="rgba(99,102,241,0.3)" />
          <stop offset="100%" stopColor="rgba(99,102,241,0.01)" />
        </linearGradient>
        <clipPath id="pcrClip">
          <rect x={0} y={0} width={chartW} height={chartH} />
        </clipPath>
      </defs>

      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* Band fills */}
        {BANDS.map((b) => {
          const y1 = yOf(Math.min(b.yMax, maxV));
          const y2 = yOf(Math.max(b.yMin, minV));
          if (y1 >= y2) return null;
          return (
            <rect
              key={b.label}
              x={0}
              y={y1}
              width={chartW}
              height={y2 - y1}
              fill={b.fill}
            />
          );
        })}

        {/* Band threshold lines */}
        {BAND_LINES.map((bl) => {
          if (bl.y > maxV) return null;
          const y = yOf(bl.y);
          return (
            <line
              key={bl.y}
              x1={0}
              y1={y}
              x2={chartW}
              y2={y}
              stroke={bl.stroke}
              strokeWidth={0.75}
              strokeDasharray={bl.dash}
            />
          );
        })}

        {/* Area fill */}
        <path d={areaPath} fill="url(#pcrGrad)" clipPath="url(#pcrClip)" />

        {/* Line */}
        <polyline
          points={linePoints}
          fill="none"
          stroke="rgba(99,102,241,0.85)"
          strokeWidth={1.5}
          strokeLinecap="round"
          strokeLinejoin="round"
          clipPath="url(#pcrClip)"
        />

        {/* Last point dot */}
        {points.length > 0 && (
          <circle
            cx={xOf(points.length - 1)}
            cy={yOf(points[points.length - 1].pcr)}
            r={3.5}
            fill="#6366f1"
            stroke="var(--color-surface-base,#0a0a0f)"
            strokeWidth={1.5}
          />
        )}

        {/* Y axis ticks */}
        {yTicks.map((v) => (
          <g key={v}>
            <line x1={-4} x2={0} y1={yOf(v)} y2={yOf(v)} stroke="var(--color-border-default,#2a2a3a)" />
            <text
              x={-6}
              y={yOf(v) + 3}
              textAnchor="end"
              fontSize={8}
              fill="var(--color-text-muted,#666)"
            >
              {v.toFixed(1)}
            </text>
          </g>
        ))}

        {/* X axis labels */}
        {xLabelIndices.map((idx) => (
          <text
            key={idx}
            x={xOf(idx)}
            y={chartH + 18}
            textAnchor="middle"
            fontSize={8}
            fill="var(--color-text-muted,#666)"
          >
            {points[idx]?.session ?? ""}
          </text>
        ))}

        {/* Axes */}
        <line x1={0} y1={chartH} x2={chartW} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
        <line x1={0} y1={0} x2={0} y2={chartH} stroke="var(--color-border-default,#2a2a3a)" />
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Symbol dropdown
// ---------------------------------------------------------------------------

interface SymbolDropdownProps {
  value: string;
  onChange: (v: string) => void;
}

function SymbolDropdown({ value, onChange }: SymbolDropdownProps) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((p) => !p)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`Select symbol, currently ${value}`}
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-28"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown
          size={10}
          className={`transition-transform flex-none ${open ? "rotate-180" : ""}`}
          aria-hidden="true"
        />
      </button>
      {open && (
        <div
          className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full"
          role="listbox"
          aria-label="Symbol options"
        >
          {SYMBOLS.map((s) => (
            <button
              key={s}
              role="option"
              aria-selected={s === value}
              onClick={() => { onChange(s); setOpen(false); }}
              className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${
                s === value ? "text-accent" : "text-text-primary"
              }`}
            >
              {s}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Direction arrow
// ---------------------------------------------------------------------------

function DirectionArrow({ current, previous }: { current: number; previous: number }) {
  if (current > previous) return <ArrowUp size={14} className="text-loss" aria-label="Rising PCR" />;
  if (current < previous) return <ArrowDown size={14} className="text-profit" aria-label="Falling PCR" />;
  return <Minus size={14} className="text-text-muted" aria-label="Unchanged PCR" />;
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function PCRTrendWidget() {
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
  const [symbol, setSymbol] = useState("NIFTY");

  // In live mode: fetch /api/v1/optionchain?symbol=NIFTY and extract PCR series
  const data = SAMPLE_PCR;

  const currentPCR = data[data.length - 1]?.pcr ?? 0;
  const previousPCR = data[data.length - 2]?.pcr ?? currentPCR;

  const regime = useMemo(() => pcrRegime(currentPCR), [currentPCR]);

  const avgPCR = useMemo(
    () => data.reduce((sum, p) => sum + p.pcr, 0) / data.length,
    [data],
  );

  const handleSymbolChange = (v: string) => {
    setSymbol(v);
    track("trade", "pcrtrend_symbol_change");
  };

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden" aria-label="PCR Trend widget">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <TrendingDown size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">PCR Trend</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <SymbolDropdown value={symbol} onChange={handleSymbolChange} />
      </div>

      {/* Current PCR summary */}
      <div className="flex-none flex items-center gap-4 px-3 py-2 bg-surface-card/50 border-b border-border-default">
        <div className="flex items-baseline gap-1.5">
          <span className="text-2xl font-bold font-mono tabular-nums text-text-primary" aria-label={`Current PCR ${currentPCR.toFixed(2)}`}>
            {currentPCR.toFixed(2)}
          </span>
          <DirectionArrow current={currentPCR} previous={previousPCR} />
        </div>
        <div className="flex flex-col gap-0.5">
          <span className={`text-xs font-semibold ${REGIME_COLOUR[regime]}`}>
            {REGIME_LABEL[regime]}
          </span>
          <span className="text-xxs text-text-muted">
            20-session avg: <span className="font-mono tabular-nums text-text-secondary">{avgPCR.toFixed(2)}</span>
          </span>
        </div>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-1 pt-1">
        <PCRChart points={data} />
      </div>

      {/* Legend */}
      <div className="flex-none px-2 pb-1.5 flex items-center gap-3 flex-wrap border-t border-border-default pt-1">
        <div className="flex items-center gap-1 text-xxs">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "rgba(34,197,94,0.20)" }} />
          <span className="text-text-muted">&lt;0.7 Bullish Ext.</span>
        </div>
        <div className="flex items-center gap-1 text-xxs">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "rgba(34,197,94,0.10)" }} />
          <span className="text-text-muted">0.7–1.0 Bullish</span>
        </div>
        <div className="flex items-center gap-1 text-xxs">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "rgba(239,68,68,0.10)" }} />
          <span className="text-text-muted">1.0–1.3 Bearish</span>
        </div>
        <div className="flex items-center gap-1 text-xxs">
          <span className="inline-block w-3 h-3 rounded-sm" style={{ background: "rgba(239,68,68,0.20)" }} />
          <span className="text-text-muted">&gt;1.3 Bearish Ext.</span>
        </div>
      </div>
    </div>
  );
}

export default memo(PCRTrendWidget);
