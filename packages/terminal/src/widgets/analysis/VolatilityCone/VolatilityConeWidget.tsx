/**
 * VolatilityConeWidget — Historical volatility cone analysis.
 *
 * Features:
 *   - HV at 5 / 10 / 20 / 30 / 60 / 90 day lookback periods
 *   - Percentile bands: 10th, 25th, 50th (median), 75th, 90th — filled SVG areas
 *   - Current IV plotted as a dot at each lookback period
 *   - Helps identify if current IV is cheap or expensive vs history
 *   - Pure SVG rendering — no external chart library
 */

import { useState, useMemo, memo } from "react";
import { Triangle, ChevronDown } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ConePoint {
  period: number;       // days
  p10: number;          // 10th percentile HV
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  currentIV: number;    // spot IV at this lookback period
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_CONE: ConePoint[] = [
  { period: 5,  p10: 8.2,  p25: 11.4, p50: 15.8, p75: 20.3, p90: 26.1, currentIV: 17.4 },
  { period: 10, p10: 9.1,  p25: 12.3, p50: 16.5, p75: 21.2, p90: 27.4, currentIV: 18.2 },
  { period: 20, p10: 10.5, p25: 13.8, p50: 17.9, p75: 22.8, p90: 29.2, currentIV: 19.1 },
  { period: 30, p10: 11.2, p25: 14.6, p50: 18.7, p75: 23.5, p90: 30.4, currentIV: 20.3 },
  { period: 60, p10: 12.8, p25: 16.1, p50: 20.4, p75: 25.9, p90: 33.1, currentIV: 21.8 },
  { period: 90, p10: 13.4, p25: 17.0, p50: 21.6, p75: 27.2, p90: 34.8, currentIV: 22.5 },
];

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function ivStatus(iv: number, p25: number, p75: number): "cheap" | "fair" | "expensive" {
  if (iv < p25) return "cheap";
  if (iv > p75) return "expensive";
  return "fair";
}

const STATUS_COLOUR: Record<string, string> = {
  cheap: "text-profit",
  fair: "text-warning",
  expensive: "text-loss",
};

// ---------------------------------------------------------------------------
// SVG Cone chart
// ---------------------------------------------------------------------------

const SVG_W = 520;
const SVG_H = 200;
const PAD = { top: 16, right: 20, bottom: 32, left: 40 };

function ConeChart({ points }: { points: ConePoint[] }) {
  const chartW = SVG_W - PAD.left - PAD.right;
  const chartH = SVG_H - PAD.top - PAD.bottom;

  const allValues = points.flatMap((p) => [p.p10, p.p90, p.currentIV]);
  const minV = Math.min(...allValues) * 0.9;
  const maxV = Math.max(...allValues) * 1.1;

  const xOf = (i: number) => (i / (points.length - 1)) * chartW;
  const yOf = (v: number) => chartH - ((v - minV) / (maxV - minV)) * chartH;

  function polylinePoints(values: number[]) {
    return values.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(" ");
  }

  function bandPath(upper: number[], lower: number[]) {
    const fwd = upper.map((v, i) => `${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`).join(" L ");
    const bwd = lower
      .map((v, i) => `${xOf(lower.length - 1 - i).toFixed(1)},${yOf(v).toFixed(1)}`)
      .join(" L ");
    return `M ${fwd} L ${bwd} Z`;
  }

  const yTicks = [minV, (minV + maxV) / 2, maxV].map((v) => ({
    label: `${v.toFixed(0)}%`,
    y: yOf(v),
  }));

  return (
    <svg
      viewBox={`0 0 ${SVG_W} ${SVG_H}`}
      className="w-full"
      style={{ height: SVG_H }}
      aria-label="Volatility cone chart"
      role="img"
    >
      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* Bands: p10-p25, p25-p75, p75-p90 */}
        <path
          d={bandPath(points.map((p) => p.p90), points.map((p) => p.p75))}
          fill="rgba(239,68,68,0.12)"
          stroke="none"
        />
        <path
          d={bandPath(points.map((p) => p.p75), points.map((p) => p.p25))}
          fill="rgba(99,102,241,0.12)"
          stroke="none"
        />
        <path
          d={bandPath(points.map((p) => p.p25), points.map((p) => p.p10))}
          fill="rgba(34,197,94,0.12)"
          stroke="none"
        />

        {/* Band border lines */}
        <polyline points={polylinePoints(points.map((p) => p.p90))} fill="none" stroke="rgba(239,68,68,0.4)" strokeWidth={1} strokeDasharray="3,2" />
        <polyline points={polylinePoints(points.map((p) => p.p75))} fill="none" stroke="rgba(239,68,68,0.25)" strokeWidth={0.75} />
        <polyline points={polylinePoints(points.map((p) => p.p50))} fill="none" stroke="rgba(99,102,241,0.5)" strokeWidth={1.25} strokeDasharray="4,2" />
        <polyline points={polylinePoints(points.map((p) => p.p25))} fill="none" stroke="rgba(34,197,94,0.25)" strokeWidth={0.75} />
        <polyline points={polylinePoints(points.map((p) => p.p10))} fill="none" stroke="rgba(34,197,94,0.4)" strokeWidth={1} strokeDasharray="3,2" />

        {/* IV dots */}
        {points.map((p, i) => {
          const cx = xOf(i);
          const cy = yOf(p.currentIV);
          const status = ivStatus(p.currentIV, p.p25, p.p75);
          const fill =
            status === "cheap" ? "#22c55e" : status === "expensive" ? "#ef4444" : "#f59e0b";
          return (
            <g key={p.period}>
              <circle cx={cx} cy={cy} r={4.5} fill={fill} stroke="var(--color-surface-base,#0a0a0f)" strokeWidth={1.5} />
              <title>{`${p.period}d IV: ${p.currentIV.toFixed(1)}% (${status})`}</title>
            </g>
          );
        })}

        {/* X axis labels */}
        {points.map((p, i) => (
          <text
            key={p.period}
            x={xOf(i)}
            y={chartH + 18}
            textAnchor="middle"
            fontSize={9}
            fill="var(--color-text-muted,#666)"
          >
            {p.period}d
          </text>
        ))}

        {/* Y axis labels */}
        {yTicks.map((t) => (
          <g key={t.label}>
            <line x1={-4} x2={0} y1={t.y} y2={t.y} stroke="var(--color-border-default,#2a2a3a)" />
            <text x={-6} y={t.y + 3} textAnchor="end" fontSize={8} fill="var(--color-text-muted,#666)">
              {t.label}
            </text>
          </g>
        ))}

        {/* X axis line */}
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
        className="flex items-center gap-1 px-2 py-1 text-xs font-medium text-text-primary bg-surface-hover border border-border-default rounded hover:border-accent/50 transition-colors min-w-24"
      >
        <span className="flex-1 text-left">{value}</span>
        <ChevronDown size={10} className={`transition-transform flex-none ${open ? "rotate-180" : ""}`} aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute top-full left-0 mt-0.5 z-50 bg-surface-card border border-border-default rounded shadow-lg min-w-full" role="listbox">
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
// Main widget
// ---------------------------------------------------------------------------

function VolatilityConeWidget() {
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
  const [symbol, setSymbol] = useState("NIFTY");

  // In live mode this would fetch from /ft-api/v1/volcone?symbol=NIFTY
  // For now we use sample data always (endpoint not yet implemented)
  const coneData = SAMPLE_CONE;

  const handleSymbolChange = (v: string) => {
    setSymbol(v);
    track("trade", "volcone_symbol_change");
  };

  const cheapCount = useMemo(
    () => coneData.filter((p) => ivStatus(p.currentIV, p.p25, p.p75) === "cheap").length,
    [coneData],
  );
  const expensiveCount = useMemo(
    () => coneData.filter((p) => ivStatus(p.currentIV, p.p25, p.p75) === "expensive").length,
    [coneData],
  );

  const overallStatus: "cheap" | "fair" | "expensive" =
    cheapCount >= 4 ? "cheap" : expensiveCount >= 4 ? "expensive" : "fair";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Triangle size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Volatility Cone</span>
        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <SymbolDropdown value={symbol} onChange={handleSymbolChange} />
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-2 pt-2">
        <ConeChart points={coneData} />
      </div>

      {/* Legend */}
      <div className="flex-none px-3 pb-1.5 flex items-center gap-3 flex-wrap text-xxs">
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px" style={{ background: "rgba(239,68,68,0.4)", borderTop: "1px dashed rgba(239,68,68,0.7)" }} />
          <span className="text-text-muted">90th pct</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px bg-accent/50" />
          <span className="text-text-muted">Median</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-6 h-px" style={{ background: "rgba(34,197,94,0.4)", borderTop: "1px dashed rgba(34,197,94,0.7)" }} />
          <span className="text-text-muted">10th pct</span>
        </div>
        <div className="flex items-center gap-1">
          <span className="inline-block w-2 h-2 rounded-full bg-warning" />
          <span className="text-text-muted">Current IV</span>
        </div>
      </div>

      {/* Summary row */}
      <div className="flex-none bg-surface-card border-t border-border-default px-3 py-1.5 flex items-center gap-4 flex-wrap text-xs">
        <div className="flex items-center gap-1.5">
          <span className="text-text-muted">IV Regime:</span>
          <span className={`font-semibold capitalize ${STATUS_COLOUR[overallStatus]}`}>
            {overallStatus}
          </span>
        </div>
        {coneData.map((p) => (
          <div key={p.period} className="flex items-center gap-1">
            <span className="text-text-muted">{p.period}d</span>
            <span className={`font-mono tabular-nums ${STATUS_COLOUR[ivStatus(p.currentIV, p.p25, p.p75)]}`}>
              {p.currentIV.toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default memo(VolatilityConeWidget);
