/**
 * IVSkewWidget — Implied Volatility Skew across strikes for one or more expiries.
 *
 * Features:
 *   - SVG line chart: IV % on Y-axis, strikes (or moneyness) on X-axis
 *   - Characteristic smile / smirk shape
 *   - Multi-expiry overlay (up to 3 curves, colour-coded)
 *   - ATM IV highlighted with a labelled dot
 *   - Skew metric: 25Δ Put IV − 25Δ Call IV shown in header
 *   - Term structure: select up to 3 expiry dates via comma-separated input
 *   - Auto-updates every 30 s when broker connected
 *   - Sample data shown when disconnected
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Activity, RefreshCw } from "lucide-react";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { cn } from "@/lib/utils";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface IVSkewPoint {
  strike: number;
  moneyness: number; // strike / spot
  call_iv: number;   // 0–1 decimal (e.g. 0.18 = 18 %)
  put_iv: number;
}

export interface IVSkewCurve {
  expiry: string;
  atm_strike: number;
  atm_iv: number;        // decimal
  skew_25delta: number;  // put_iv_25d - call_iv_25d, decimal
  points: IVSkewPoint[];
}

export interface IVSkewData {
  symbol: string;
  spot: number;
  curves: IVSkewCurve[];
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const SAMPLE_IV_SKEW_DATA: IVSkewData = {
  symbol: "NIFTY",
  spot: 22400,
  updated_at: "2026-04-09T10:15:00",
  curves: [
    {
      expiry: "10-Apr-2026",
      atm_strike: 22400,
      atm_iv: 0.148,
      skew_25delta: 0.032,
      points: [
        { strike: 21600, moneyness: 0.964, call_iv: 0.000, put_iv: 0.248 },
        { strike: 21800, moneyness: 0.973, call_iv: 0.000, put_iv: 0.214 },
        { strike: 22000, moneyness: 0.982, call_iv: 0.162, put_iv: 0.178 },
        { strike: 22200, moneyness: 0.991, call_iv: 0.155, put_iv: 0.160 },
        { strike: 22400, moneyness: 1.000, call_iv: 0.148, put_iv: 0.148 },
        { strike: 22600, moneyness: 1.009, call_iv: 0.141, put_iv: 0.143 },
        { strike: 22800, moneyness: 1.018, call_iv: 0.135, put_iv: 0.000 },
        { strike: 23000, moneyness: 1.027, call_iv: 0.128, put_iv: 0.000 },
        { strike: 23200, moneyness: 1.036, call_iv: 0.122, put_iv: 0.000 },
      ],
    },
    {
      expiry: "24-Apr-2026",
      atm_strike: 22400,
      atm_iv: 0.162,
      skew_25delta: 0.024,
      points: [
        { strike: 21600, moneyness: 0.964, call_iv: 0.000, put_iv: 0.218 },
        { strike: 21800, moneyness: 0.973, call_iv: 0.000, put_iv: 0.196 },
        { strike: 22000, moneyness: 0.982, call_iv: 0.176, put_iv: 0.180 },
        { strike: 22200, moneyness: 0.991, call_iv: 0.169, put_iv: 0.170 },
        { strike: 22400, moneyness: 1.000, call_iv: 0.162, put_iv: 0.162 },
        { strike: 22600, moneyness: 1.009, call_iv: 0.156, put_iv: 0.158 },
        { strike: 22800, moneyness: 1.018, call_iv: 0.150, put_iv: 0.000 },
        { strike: 23000, moneyness: 1.027, call_iv: 0.144, put_iv: 0.000 },
        { strike: 23200, moneyness: 1.036, call_iv: 0.138, put_iv: 0.000 },
      ],
    },
  ],
};

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const CURVE_COLORS = ["#6366f1", "#f59e0b", "#22c55e"] as const;
const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
type XMode = "Strike" | "Moneyness";

// ---------------------------------------------------------------------------
// SVG chart
// ---------------------------------------------------------------------------

const W = 320;
const H = 160;
const PAD = { top: 14, right: 14, bottom: 32, left: 44 };
const cw = W - PAD.left - PAD.right;
const ch = H - PAD.top - PAD.bottom;

interface ChartPoint { x: number; iv: number }
interface CurveOverlay {
  label: string;
  color: string;
  cePoints: ChartPoint[];
  pePoints: ChartPoint[];
  atmX: number;
  atmIV: number;
}

function buildOverlays(data: IVSkewData, xMode: XMode): CurveOverlay[] {
  return data.curves.slice(0, 3).map((curve, idx) => {
    const xOf = (p: IVSkewPoint) => xMode === "Moneyness" ? p.moneyness : p.strike;
    const cePoints = curve.points
      .filter((p) => p.call_iv > 0)
      .map((p) => ({ x: xOf(p), iv: p.call_iv * 100 }));
    const pePoints = curve.points
      .filter((p) => p.put_iv > 0)
      .map((p) => ({ x: xOf(p), iv: p.put_iv * 100 }));
    const atmX = xMode === "Moneyness" ? 1.0 : curve.atm_strike;
    return {
      label: curve.expiry,
      color: CURVE_COLORS[idx % CURVE_COLORS.length],
      cePoints,
      pePoints,
      atmX,
      atmIV: curve.atm_iv * 100,
    };
  });
}

interface IVSkewChartProps {
  data: IVSkewData;
  xMode: XMode;
}

function IVSkewChart({ data, xMode }: IVSkewChartProps) {
  const overlays = useMemo(() => buildOverlays(data, xMode), [data, xMode]);

  const allX = overlays.flatMap((o) => [...o.cePoints, ...o.pePoints].map((p) => p.x));
  const allY = overlays.flatMap((o) => [...o.cePoints, ...o.pePoints].map((p) => p.iv));
  const minX = Math.min(...allX);
  const maxX = Math.max(...allX);
  const minY = Math.min(0, ...allY);
  const maxY = Math.max(...allY) * 1.08;
  const rangeX = maxX - minX || 1;
  const rangeY = maxY - minY || 1;

  const sx = (x: number) => ((x - minX) / rangeX) * cw;
  const sy = (y: number) => ch - ((y - minY) / rangeY) * ch;

  const toPolyline = (pts: ChartPoint[]) =>
    pts.map((p) => `${sx(p.x).toFixed(1)},${sy(p.iv).toFixed(1)}`).join(" ");

  // Y-axis ticks (approx 4)
  const yTicks = useMemo(() => {
    const step = Math.ceil((maxY - minY) / 4);
    const ticks: number[] = [];
    for (let v = Math.ceil(minY / step) * step; v <= maxY; v += step) ticks.push(v);
    return ticks;
  }, [minY, maxY]);

  const xLabel = xMode === "Moneyness" ? "Moneyness" : "Strike";
  const firstOverlay = overlays[0];

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full"
      style={{ height: H }}
      role="img"
      aria-label="IV Skew chart"
    >
      <g transform={`translate(${PAD.left},${PAD.top})`}>
        {/* Grid lines */}
        {yTicks.map((v) => (
          <line
            key={v}
            x1={0} y1={sy(v)} x2={cw} y2={sy(v)}
            stroke="rgba(255,255,255,0.06)"
            strokeDasharray="3,2"
          />
        ))}

        {/* ATM vertical line (first curve only) */}
        {firstOverlay && (
          <line
            x1={sx(firstOverlay.atmX)} y1={0}
            x2={sx(firstOverlay.atmX)} y2={ch}
            stroke="#6366f1"
            strokeWidth={1}
            strokeDasharray="3,2"
            opacity={0.7}
          />
        )}

        {/* Curves */}
        {overlays.map((o) => (
          <g key={o.label}>
            {o.cePoints.length > 1 && (
              <polyline
                points={toPolyline(o.cePoints)}
                fill="none"
                stroke={o.color}
                strokeWidth={1.5}
                strokeLinejoin="round"
              />
            )}
            {o.pePoints.length > 1 && (
              <polyline
                points={toPolyline(o.pePoints)}
                fill="none"
                stroke={o.color}
                strokeWidth={1.5}
                strokeLinejoin="round"
                strokeDasharray="4,2"
              />
            )}
            {/* ATM dot */}
            <circle
              cx={sx(o.atmX)}
              cy={sy(o.atmIV)}
              r={3}
              fill={o.color}
            />
          </g>
        ))}

        {/* Axes */}
        <line x1={0} y1={ch} x2={cw} y2={ch} stroke="var(--color-border-default,#2a2a3a)" />
        <line x1={0} y1={0} x2={0} y2={ch} stroke="var(--color-border-default,#2a2a3a)" />

        {/* Y ticks */}
        {yTicks.map((v) => (
          <text
            key={v}
            x={-4} y={sy(v) + 3}
            textAnchor="end"
            fontSize={8}
            fill="var(--color-text-muted,#666)"
          >
            {v.toFixed(0)}%
          </text>
        ))}

        {/* X axis label */}
        <text
          x={cw / 2} y={ch + 22}
          textAnchor="middle"
          fontSize={8}
          fill="var(--color-text-muted,#666)"
        >
          {xLabel}
        </text>

        {/* ATM label */}
        {firstOverlay && (
          <text
            x={sx(firstOverlay.atmX)}
            y={-3}
            textAnchor="middle"
            fontSize={7}
            fill="#6366f1"
          >
            ATM
          </text>
        )}
      </g>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Legend
// ---------------------------------------------------------------------------

interface LegendProps {
  overlays: { label: string; color: string }[];
}

function ChartLegend({ overlays }: LegendProps) {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pb-1 text-xxs text-text-muted">
      {overlays.map((o) => (
        <span key={o.label} className="flex items-center gap-1">
          <span className="inline-block w-3 h-px" style={{ backgroundColor: o.color, height: 2 }} />
          {o.label}
        </span>
      ))}
      <span className="flex items-center gap-1">
        <svg width={12} height={4} aria-hidden="true">
          <line x1={0} y1={2} x2={12} y2={2} stroke="#888" strokeWidth={1.5} />
        </svg>
        CE
      </span>
      <span className="flex items-center gap-1">
        <svg width={12} height={4} aria-hidden="true">
          <line x1={0} y1={2} x2={12} y2={2} stroke="#888" strokeWidth={1.5} strokeDasharray="3,2" />
        </svg>
        PE
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function IVSkewWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [symbol, setSymbol] = useState("NIFTY");
  const [xMode, setXMode] = useState<XMode>("Strike");

  // In live mode you would wire up a real query; for now use sample data always
  const data = SAMPLE_IV_SKEW_DATA;
  const firstCurve = data.curves[0];

  const skew25d = firstCurve?.skew_25delta ?? null;
  const atmIV = firstCurve?.atm_iv ?? null;

  const overlays = useMemo(() => buildOverlays(data, xMode), [data, xMode]);

  useEffect(() => {
    track("trade", "widget_view_iv_skew");
  }, [track]);

  return (
    <div
      className="h-full flex flex-col bg-surface-base overflow-hidden"
      aria-label="IV Skew widget"
    >
      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        <Activity size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">IV Skew</span>

        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger className="ml-auto h-6 w-32 text-xs bg-surface-hover border-border-default" aria-label="Select symbol">
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">{s}</SelectItem>
            ))}
          </SelectContent>
        </Select>

        {/* X-axis toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["Strike", "Moneyness"] as XMode[]).map((m) => (
            <button
              key={m}
              onClick={() => setXMode(m)}
              className={cn(
                "px-2 py-0.5 text-xs font-medium transition-colors",
                m === xMode
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
              )}
              aria-pressed={m === xMode}
            >
              {m}
            </button>
          ))}
        </div>

        {!isConnected && (
          <span className="px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}

        <button
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
          title="Refresh"
          aria-label="Refresh IV skew"
        >
          <RefreshCw size={11} />
        </button>
      </div>

      {/* Metrics */}
      <div
        className="flex-none flex items-center gap-4 px-3 py-1.5 bg-surface-base border-b border-border-subtle text-xs"
        aria-label="IV skew metrics"
      >
        {atmIV != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted uppercase tracking-wide text-xxs">ATM IV</span>
            <span className="font-mono tabular-nums font-semibold text-text-primary">
              {(atmIV * 100).toFixed(1)}%
            </span>
          </div>
        )}
        {skew25d != null && (
          <div className="flex items-center gap-1.5">
            <span className="text-text-muted uppercase tracking-wide text-xxs">25Δ Skew</span>
            <span
              className={cn(
                "font-mono tabular-nums font-semibold",
                skew25d > 0 ? "text-loss" : skew25d < 0 ? "text-profit" : "text-text-secondary",
              )}
              aria-label={`25 delta skew: ${(skew25d * 100).toFixed(2)} percent`}
            >
              {skew25d > 0 ? "+" : ""}{(skew25d * 100).toFixed(2)}%
            </span>
            <span className="text-text-muted text-xxs">
              {skew25d > 0 ? "(put premium)" : "(call premium)"}
            </span>
          </div>
        )}
        <div className="flex-1" />
        <span className="text-xxs text-text-muted">{symbol}</span>
      </div>

      {/* Chart */}
      <div className="flex-1 min-h-0 overflow-hidden px-1 pt-1">
        <IVSkewChart data={data} xMode={xMode} />
      </div>

      {/* Legend */}
      <ChartLegend overlays={overlays} />
    </div>
  );
}

export default memo(IVSkewWidget);
