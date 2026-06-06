/**
 * IVSkewWidget — Implied Volatility Skew across strikes for one or more expiries.
 *
 * Features:
 *   - SVG line chart: IV % on Y-axis, strikes (or moneyness) on X-axis
 *   - Characteristic smile / smirk shape
 *   - Multi-expiry overlay (up to 3 curves, colour-coded)
 *   - ATM IV highlighted with a labelled dot
 *   - Skew metric: 25Δ Put IV − 25Δ Call IV shown in header
 *   - Multi-expiry overlay (up to 3 nearest expiries) when live
 *
 * DATA HONESTY: when a broker is connected, the widget fetches the live IV
 * smile (`getFtIVSmile` — the same screener source the IVSmile and GreeksSurface
 * widgets use) and maps it to skew curves (`ivSkewTransform`), showing a "Live"
 * badge. Per-strike IV is NOT in the OpenAlgo option-chain feed, so it must come
 * from the dedicated IV-smile endpoint. When disconnected — or no usable curve
 * comes back — it falls back to deterministic sample curves with an amber
 * "Sample data" badge so the figures are never mistaken for live market data.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { Activity } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { FlintBandedLineChart } from "@flinttrade/design-system";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getFtIVSmile } from "@/services/ftApi.analysis";
import { SYMBOLS as OPTION_SYMBOLS } from "@/widgets/analysis/OptionChain/types";
import { mapIVSmileToSkew } from "./ivSkewTransform";
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
// Core chart adapter
// ---------------------------------------------------------------------------

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

function buildIVSkewChart(overlays: CurveOverlay[], xMode: XMode) {
  const allX = overlays.flatMap((o) => [...o.cePoints, ...o.pePoints].map((p) => p.x));
  const allY = overlays.flatMap((o) => [...o.cePoints, ...o.pePoints].map((p) => p.iv));
  const minX = allX.length > 0 ? Math.min(...allX) : 0;
  const maxX = allX.length > 0 ? Math.max(...allX) : 1;
  const minY = Math.min(0, ...(allY.length > 0 ? allY : [0]));
  const maxY = Math.max(...(allY.length > 0 ? allY : [1])) * 1.08;
  const safeMaxY = maxY > minY ? maxY : minY + 1;
  const firstOverlay = overlays[0];

  const series = overlays.flatMap((overlay) => [
    {
      id: `${overlay.label}-ce`,
      label: `${overlay.label} CE`,
      color: overlay.color,
      strokeWidth: 1.5,
      points: overlay.cePoints.map((point) => ({
        x: point.x,
        y: point.iv,
        label: `${overlay.label} CE ${point.iv.toFixed(1)}%`,
      })),
    },
    {
      id: `${overlay.label}-pe`,
      label: `${overlay.label} PE`,
      color: overlay.color,
      dash: "4,2",
      strokeWidth: 1.5,
      points: overlay.pePoints.map((point) => ({
        x: point.x,
        y: point.iv,
        label: `${overlay.label} PE ${point.iv.toFixed(1)}%`,
      })),
    },
  ]);
  const markers = overlays.map((overlay) => ({
    id: `${overlay.label}-atm`,
    label: `${overlay.label} ATM ${overlay.atmIV.toFixed(1)}%`,
    x: overlay.atmX,
    y: overlay.atmIV,
    color: overlay.color,
    radius: 3,
  }));
  const yStep = Math.ceil((safeMaxY - minY) / 4) || 1;
  const yTicks: number[] = [];
  for (let value = Math.ceil(minY / yStep) * yStep; value <= safeMaxY; value += yStep) {
    yTicks.push(value);
  }

  return {
    series,
    markers,
    xDomain: [minX, maxX > minX ? maxX : minX + 1] as const,
    yDomain: [minY, safeMaxY] as const,
    yTicks,
    referenceLines: firstOverlay
      ? [{ axis: "x" as const, value: firstOverlay.atmX, color: "#6366f1", dash: "3,2" }]
      : [],
    xAxisLabel: xMode === "Moneyness" ? "Moneyness" : "Strike",
  };
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
        <span className="inline-block w-3 border-t border-[#888]" aria-hidden="true" style={{ borderTopWidth: 1.5 }} />
        CE
      </span>
      <span className="flex items-center gap-1">
        <span className="inline-block w-3 border-t border-dashed border-[#888]" aria-hidden="true" style={{ borderTopWidth: 1.5 }} />
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

  // Resolve the option exchange (NFO/BFO/…) for the selected underlying.
  const symDef = useMemo(
    () => OPTION_SYMBOLS.find((s) => s.label === symbol) ?? { label: symbol, exchange: "NFO" },
    [symbol],
  );

  // Live IV-skew — fetch the screener IV smile (the dedicated IV source) and
  // map it to skew curves. Only runs once a broker is connected.
  const { data: liveData } = useQuery({
    queryKey: ["ivskew", symbol, symDef.exchange],
    queryFn: async () => {
      const smile = await getFtIVSmile(symDef.label, symDef.exchange);
      return mapIVSmileToSkew(smile, new Date().toISOString());
    },
    enabled: isConnected,
    staleTime: 30_000,
    refetchInterval: isConnected ? 30_000 : false,
    retry: false,
  });

  const isLive = isConnected && liveData != null && liveData.curves.length > 0;
  const data = isLive && liveData ? liveData : SAMPLE_IV_SKEW_DATA;
  const firstCurve = data.curves[0];

  const skew25d = firstCurve?.skew_25delta ?? null;
  const atmIV = firstCurve?.atm_iv ?? null;

  const overlays = useMemo(() => buildOverlays(data, xMode), [data, xMode]);
  const skewChart = useMemo(() => buildIVSkewChart(overlays, xMode), [overlays, xMode]);

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
        {/* Data-source badge — flips to "Live" only when a broker is connected
            AND the chain yielded a usable skew curve. Otherwise it stays on the
            honest amber "Sample data" affordance so the curves are never
            mistaken for live market data. */}
        {isLive ? (
          <span
            className="inline-flex items-center rounded border border-profit/40 bg-profit/10 px-1.5 py-0.5 text-[10px] font-medium text-profit"
            role="status"
            aria-label="Showing the live IV smile from the connected broker"
            title="Live IV skew from the connected broker's IV-smile feed."
          >
            Live
          </span>
        ) : (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; no live backend endpoint yet"
            title="No live data wired yet — showing sample IV skew curves so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}

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
        <FlintBandedLineChart
          ariaLabel="IV Skew chart"
          bands={[]}
          series={skewChart.series}
          markers={skewChart.markers}
          xDomain={skewChart.xDomain}
          yDomain={skewChart.yDomain}
          yTicks={skewChart.yTicks}
          yFormatter={(value) => `${value.toFixed(0)}%`}
          xAxisLabel={skewChart.xAxisLabel}
          referenceLines={skewChart.referenceLines}
          width={320}
          height={160}
        />
      </div>

      {/* Legend */}
      <ChartLegend overlays={overlays} />
    </div>
  );
}

export default memo(IVSkewWidget);
