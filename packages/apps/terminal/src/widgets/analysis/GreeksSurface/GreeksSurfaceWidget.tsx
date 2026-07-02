/**
 * GreeksSurfaceWidget — 3D Implied Volatility Surface for FlintTrade terminal.
 *
 * Renders a CSS-perspective isometric grid showing IV (or Delta / Gamma / Theta)
 * across option moneyness (X) and expiry (Y depth).  No Three.js / WebGL —
 * pure CSS transforms: perspective + rotateX + rotateY.
 *
 * Features:
 *   - X-axis: moneyness buckets (-5% → ATM → +5%)
 *   - Y-axis (depth): front week → front month → back month
 *   - Z-axis (height): IV% (or delta / gamma / theta)
 *   - Cell colour: blue (low) → green → yellow → red (extreme)
 *   - Hover tooltip: IV, strike, expiry, delta at that cell
 *   - Controls: rotate X/Y perspective, toggle metric view
 *   - FeatureTeaser over sample data in explore/disconnected mode
 *   - Auto-refresh every 30s during market hours when connected
 */

import { useState, useMemo, useCallback, memo } from "react";
import {
  RefreshCw,
  AlertCircle,
  Loader2,
  RotateCcw,
  ChevronUp,
  ChevronDown,
} from "lucide-react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Input } from "@/components/ui/input";
import { useGreeksSurface } from "./useGreeksSurface";
import { SAMPLE_GREEKS_SURFACE_DATA } from "./sampleData";
import type { GreeksSurfaceExpiry, GreeksSurfacePoint } from "./sampleData";
import { FeatureTeaser } from "@/components/teasers";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { APP_VERSION_TAG } from "@/lib/appVersion";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const SYMBOLS = ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX"];
const SYMBOL_EXCHANGE: Record<string, string> = {
  NIFTY: "NFO",
  BANKNIFTY: "NFO",
  FINNIFTY: "NFO",
  MIDCPNIFTY: "NFO",
  SENSEX: "BFO",
};

type MetricKey = "iv" | "delta" | "gamma" | "theta";

const METRIC_LABELS: Record<MetricKey, string> = {
  iv: "IV %",
  delta: "Delta",
  gamma: "Gamma",
  theta: "Theta",
};

/** Default perspective angles (degrees). */
const DEFAULT_ROT_X = 52;
const DEFAULT_ROT_Y = -18;

// ---------------------------------------------------------------------------
// Colour scale: value 0→1 → CSS hsl colour (blue=low, green=mid, yellow=high, red=extreme)
// ---------------------------------------------------------------------------

function valueToHsl(norm: number): string {
  // hue: 240 (blue) → 120 (green) → 60 (yellow) → 0 (red)
  const hue = Math.round(240 - norm * 240);
  const sat = 70;
  const lit = 35 + norm * 15; // slightly brighter at extremes
  return `hsl(${hue},${sat}%,${lit}%)`;
}

function getMetricValue(pt: GreeksSurfacePoint, metric: MetricKey): number {
  switch (metric) {
    case "iv":    return pt.iv;
    case "delta": return pt.delta;
    case "gamma": return pt.gamma;
    case "theta": return Math.abs(pt.theta); // display magnitude
  }
}

function formatMetric(val: number, metric: MetricKey): string {
  switch (metric) {
    case "iv":    return `${val.toFixed(1)}%`;
    case "delta": return val.toFixed(3);
    case "gamma": return val.toFixed(5);
    case "theta": return `−${val.toFixed(1)}`;
  }
}

// ---------------------------------------------------------------------------
// Tooltip
// ---------------------------------------------------------------------------

interface TooltipData {
  pt: GreeksSurfacePoint;
  expiry: string;
  dte: number;
  x: number;
  y: number;
}

interface CellTooltipProps {
  data: TooltipData;
}

function CellTooltip({ data }: CellTooltipProps) {
  const { pt, expiry, dte, x, y } = data;
  return (
    <div
      className="fixed z-50 pointer-events-none bg-surface-card border border-border-default rounded px-2.5 py-2 shadow-lg text-xs min-w-40"
      style={{ left: x + 12, top: y - 10 }}
      role="tooltip"
    >
      <div className="font-semibold text-text-primary mb-1">
        {pt.moneyness} · {pt.strike}
      </div>
      <div className="space-y-0.5 text-text-secondary">
        <div className="flex justify-between gap-4">
          <span>Expiry</span>
          <span className="font-mono text-text-primary">{expiry} ({dte}d)</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>IV</span>
          <span className="font-mono text-text-primary">{pt.iv.toFixed(1)}%</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Delta</span>
          <span className="font-mono text-text-primary">{pt.delta.toFixed(3)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Gamma</span>
          <span className="font-mono text-text-primary">{pt.gamma.toFixed(5)}</span>
        </div>
        <div className="flex justify-between gap-4">
          <span>Theta</span>
          <span className="font-mono text-text-primary">−{Math.abs(pt.theta).toFixed(1)}/d</span>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// 3D surface grid
// ---------------------------------------------------------------------------

interface SurfaceGridProps {
  expiries: GreeksSurfaceExpiry[];
  metric: MetricKey;
  rotX: number;
  rotY: number;
}

function SurfaceGrid({ expiries, metric, rotX, rotY }: SurfaceGridProps) {
  const [tooltip, setTooltip] = useState<TooltipData | null>(null);

  // Compute normalised value range across all cells
  const { minVal, maxVal } = useMemo(() => {
    let min = Infinity;
    let max = -Infinity;
    for (const exp of expiries) {
      for (const pt of exp.points) {
        const v = getMetricValue(pt, metric);
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    return { minVal: min, maxVal: max };
  }, [expiries, metric]);

  const range = maxVal - minVal || 1;

  const colCount = expiries[0]?.points.length ?? 0;
  const rowCount = expiries.length;

  // Cell dimensions in px (isometric perspective tiles)
  const cellW = 46;
  const cellH = 32;

  // Total canvas size (unrotated)
  const canvasW = colCount * cellW;
  const canvasH = rowCount * cellH;

  const handleMouseEnter = useCallback(
    (e: React.MouseEvent, pt: GreeksSurfacePoint, expiry: GreeksSurfaceExpiry) => {
      setTooltip({
        pt,
        expiry: expiry.expiry,
        dte: expiry.dte,
        x: e.clientX,
        y: e.clientY,
      });
    },
    [],
  );

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    setTooltip((prev) =>
      prev ? { ...prev, x: e.clientX, y: e.clientY } : prev,
    );
  }, []);

  const handleMouseLeave = useCallback(() => setTooltip(null), []);

  return (
    <>
      {/* 3D perspective container */}
      <div
        className="relative select-none"
        style={{
          width: canvasW,
          height: canvasH,
          transform: `perspective(900px) rotateX(${rotX}deg) rotateY(${rotY}deg)`,
          transformStyle: "preserve-3d",
          transformOrigin: "center center",
        }}
        aria-label="Greeks surface 3D grid"
      >
        {expiries.map((exp, rowIdx) =>
          exp.points.map((pt, colIdx) => {
            const val = getMetricValue(pt, metric);
            const norm = (val - minVal) / range;
            const barHeight = Math.max(4, Math.round(norm * 60));
            const bg = valueToHsl(norm);
            const isATM = pt.moneyness === "ATM";

            return (
              <div
                key={`${exp.expiry}-${pt.moneyness}`}
                className="absolute flex flex-col items-center justify-end cursor-default"
                style={{
                  left: colIdx * cellW,
                  top: rowIdx * cellH,
                  width: cellW - 2,
                  height: cellH - 2,
                }}
                onMouseEnter={(e) => handleMouseEnter(e, pt, exp)}
                onMouseMove={handleMouseMove}
                onMouseLeave={handleMouseLeave}
                role="gridcell"
                aria-label={`${exp.label} ${pt.moneyness} ${METRIC_LABELS[metric]}: ${formatMetric(val, metric)}`}
              >
                {/* Bar — height encodes metric value */}
                <div
                  className="w-full rounded-t-sm transition-all duration-300"
                  style={{
                    height: barHeight,
                    background: bg,
                    boxShadow: isATM
                      ? `0 0 6px 1px ${bg}`
                      : undefined,
                    opacity: 0.88,
                    border: isATM ? "1px solid rgba(255,255,255,0.3)" : undefined,
                  }}
                />
                {/* Base floor tile */}
                <div
                  className="w-full border border-border-subtle"
                  style={{
                    height: 3,
                    background: "var(--color-surface-hover)",
                    opacity: 0.6,
                  }}
                />
              </div>
            );
          }),
        )}
      </div>

      {/* Tooltip rendered outside the 3D container so it is never clipped */}
      {tooltip && <CellTooltip data={tooltip} />}
    </>
  );
}

// ---------------------------------------------------------------------------
// Axis labels (rendered outside the 3D transform for readability)
// ---------------------------------------------------------------------------

interface AxisLabelsProps {
  expiries: GreeksSurfaceExpiry[];
}

function AxisLabels({ expiries }: AxisLabelsProps) {
  const moneynessLabels = expiries[0]?.points.map((p) => p.moneyness) ?? [];
  return (
    <div className="flex items-start gap-6 px-3 pb-1 flex-wrap">
      <div>
        <span className="text-xxs text-text-muted uppercase tracking-wide">Moneyness →</span>
        <div className="flex gap-0.5 mt-0.5 flex-wrap">
          {moneynessLabels.map((lbl) => (
            <span
              key={lbl}
              className={`text-xxs font-mono px-1 rounded ${
                lbl === "ATM"
                  ? "bg-accent/15 text-accent font-semibold"
                  : "text-text-muted"
              }`}
            >
              {lbl}
            </span>
          ))}
        </div>
      </div>
      <div>
        <span className="text-xxs text-text-muted uppercase tracking-wide">Expiry →</span>
        <div className="flex gap-1 mt-0.5">
          {expiries.map((exp) => (
            <span key={exp.expiry} className="text-xxs text-text-secondary font-mono">
              {exp.label}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Colour legend
// ---------------------------------------------------------------------------

interface LegendProps {
  label: string;
  minVal: number;
  maxVal: number;
  metric: MetricKey;
}

function ColourLegend({ label, minVal, maxVal, metric }: LegendProps) {
  return (
    <div className="flex items-center gap-2 px-3 pb-1">
      <span className="text-xxs text-text-muted">{label}</span>
      <div
        className="h-2 w-24 rounded"
        style={{
          background: "linear-gradient(to right, hsl(240,70%,35%), hsl(120,70%,40%), hsl(60,70%,45%), hsl(0,70%,40%))",
        }}
        aria-label="Colour scale from low (blue) to high (red)"
      />
      <span className="text-xxs font-mono text-text-muted">
        {formatMetric(minVal, metric)} – {formatMetric(maxVal, metric)}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function GreeksSurfaceWidget() {
  const [symbol, setSymbol] = useState("NIFTY");
  const [expiriesInput, setExpiriesInput] = useState("");
  const [metric, setMetric] = useState<MetricKey>("iv");
  const [rotX, setRotX] = useState(DEFAULT_ROT_X);
  const [rotY, setRotY] = useState(DEFAULT_ROT_Y);

  const isConnected = useBrokerConnected();
  const exchange = SYMBOL_EXCHANGE[symbol] ?? "NFO";

  const expiryDates = useMemo(
    () =>
      expiriesInput
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean)
        .slice(0, 3),
    [expiriesInput],
  );

  const {
    data: liveData,
    isLoading,
    isError,
    error,
    refetch,
    isFetching,
  } = useGreeksSurface(
    symbol,
    exchange,
    expiryDates.length > 0 ? expiryDates : undefined,
    isConnected,
  );

  const data = isConnected ? liveData : SAMPLE_GREEKS_SURFACE_DATA;

  // Range for legend
  const { minVal, maxVal } = useMemo(() => {
    if (!data?.length) return { minVal: 0, maxVal: 0 };
    let min = Infinity;
    let max = -Infinity;
    for (const exp of data) {
      for (const pt of exp.points) {
        const v = getMetricValue(pt, metric);
        if (v < min) min = v;
        if (v > max) max = v;
      }
    }
    return { minVal: min, maxVal: max };
  }, [data, metric]);

  const handleResetView = useCallback(() => {
    setRotX(DEFAULT_ROT_X);
    setRotY(DEFAULT_ROT_Y);
  }, []);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Controls */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default flex-wrap">
        {/* Honest disclosure — when disconnected the surface is
            SAMPLE_GREEKS_SURFACE_DATA (data = isConnected ? liveData : SAMPLE).
            Permanent (non-dismissible) badge, unlike the dismissible PreviewBanner. */}
        {!isConnected && (
          <span
            className="inline-flex items-center rounded border border-amber-500/40 bg-amber-500/10 px-1.5 py-0.5 text-[10px] font-medium text-amber-400"
            role="status"
            aria-label="Showing sample data; connect a broker for a live greeks surface"
            title="Not connected — showing a sample greeks surface so the widget is usable in explore mode."
          >
            Sample data
          </span>
        )}
        <Select value={symbol} onValueChange={setSymbol}>
          <SelectTrigger
            className="w-32 h-7 text-xs bg-surface-hover border-border-default text-text-primary focus:ring-accent/40"
            aria-label="Select symbol"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent className="bg-surface-card border-border-default">
            {SYMBOLS.map((s) => (
              <SelectItem key={s} value={s} className="text-xs text-text-primary focus:bg-surface-hover">
                {s}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Input
          value={expiriesInput}
          onChange={(e) => setExpiriesInput(e.target.value)}
          placeholder="Expiries (comma-sep)"
          className="flex-1 min-w-32 h-7 text-xs"
          aria-label="Expiry dates, comma-separated"
        />

        {/* Metric toggle */}
        <div className="flex items-center bg-surface-base rounded border border-border-default overflow-hidden">
          {(["iv", "delta", "gamma", "theta"] as MetricKey[]).map((m) => (
            <button
              key={m}
              onClick={() => setMetric(m)}
              className={`px-2 py-0.5 text-xs font-medium capitalize transition-colors ${
                m === metric
                  ? "bg-accent/15 text-accent"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-hover"
              }`}
            >
              {METRIC_LABELS[m]}
            </button>
          ))}
        </div>

        {/* Rotation controls */}
        <div className="flex items-center gap-1">
          <div className="flex flex-col">
            <button
              onClick={() => setRotX((v) => Math.min(80, v + 5))}
              className="p-0.5 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
              title="Rotate up"
              aria-label="Rotate view up"
            >
              <ChevronUp size={12} />
            </button>
            <button
              onClick={() => setRotX((v) => Math.max(10, v - 5))}
              className="p-0.5 text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
              title="Rotate down"
              aria-label="Rotate view down"
            >
              <ChevronDown size={12} />
            </button>
          </div>
          <div className="flex gap-0.5">
            <button
              onClick={() => setRotY((v) => v - 5)}
              className="px-1.5 py-0.5 text-xxs text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
              title="Rotate left"
              aria-label="Rotate view left"
            >
              ←
            </button>
            <button
              onClick={() => setRotY((v) => v + 5)}
              className="px-1.5 py-0.5 text-xxs text-text-muted hover:text-text-primary hover:bg-surface-hover rounded transition-colors"
              title="Rotate right"
              aria-label="Rotate view right"
            >
              →
            </button>
          </div>
          <button
            onClick={handleResetView}
            className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors"
            title="Reset view"
            aria-label="Reset 3D view"
          >
            <RotateCcw size={11} />
          </button>
        </div>

        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover transition-colors disabled:opacity-40"
          title="Refresh"
          aria-label="Refresh Greeks surface"
        >
          <RefreshCw size={11} className={isFetching ? "animate-spin" : ""} />
        </button>
      </div>

      {/* Error banner */}
      {isError && (
        <div className="flex-none flex items-center gap-2 px-2 py-1 bg-loss/10 border-b border-loss/20 text-loss text-xs">
          <AlertCircle size={11} aria-hidden="true" />
          <span>{(error as Error)?.message ?? "Failed to load Greeks surface data"}</span>
        </div>
      )}

      {/* Loading state */}
      {isConnected && isLoading && (
        <div className="flex-1 flex items-center justify-center gap-2 text-text-muted text-sm">
          <Loader2 size={16} className="animate-spin" aria-hidden="true" />
          Loading Greeks surface...
        </div>
      )}

      {/* Empty state */}
      {isConnected && !isLoading && !liveData && !isError && (
        <div className="flex-1 flex items-center justify-center text-text-muted text-sm">
          Select symbol to view Greeks surface
        </div>
      )}

      {/* Surface */}
      {data && data.length > 0 && (() => {
        const surfaceContent = (
          <div className="flex-1 flex flex-col min-h-0 overflow-auto">
            {/* Colour legend */}
            <ColourLegend
              label={METRIC_LABELS[metric]}
              minVal={minVal}
              maxVal={maxVal}
              metric={metric}
            />

            {/* 3D surface grid — centred with overflow scroll */}
            <div className="flex-1 flex items-start justify-center pt-4 px-4 pb-8 overflow-auto">
              <SurfaceGrid
                expiries={data}
                metric={metric}
                rotX={rotX}
                rotY={rotY}
              />
            </div>

            {/* Axis labels */}
            <AxisLabels expiries={data} />
          </div>
        );

        return isConnected ? (
          surfaceContent
        ) : (
          <FeatureTeaser
            status="preview"
            featureName="Greeks Surface"
            version={APP_VERSION_TAG}
          >
            {surfaceContent}
          </FeatureTeaser>
        );
      })()}
    </div>
  );
}

export default memo(GreeksSurfaceWidget);
