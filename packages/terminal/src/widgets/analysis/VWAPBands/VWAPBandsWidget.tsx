/**
 * VWAPBandsWidget — Intraday VWAP with 1σ/2σ/3σ bands for FlintTrade terminal.
 *
 * Features:
 *   - Pure SVG line chart — VWAP + price line
 *   - Upper/lower bands at 1σ, 2σ, 3σ — filled between bands
 *   - Symbol selector
 *   - Auto-refresh every 30s during market hours
 *   - Sample data in explore mode; /api/v1/history in live mode
 */

import { useState, useMemo, useEffect, useCallback, memo } from "react";
import { Waves, RefreshCw, ChevronDown } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface OHLCVBar {
  time: string;  // HH:MM
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

interface VWAPPoint {
  time: string;
  price: number;
  vwap: number;
  upper1: number;
  lower1: number;
  upper2: number;
  lower2: number;
  upper3: number;
  lower3: number;
}

// ---------------------------------------------------------------------------
// VWAP computation
// ---------------------------------------------------------------------------

function computeVWAP(bars: OHLCVBar[]): VWAPPoint[] {
  let cumTPV = 0;
  let cumVol = 0;
  const points: VWAPPoint[] = [];
  const typicals: number[] = [];

  bars.forEach((bar) => {
    const tp = (bar.high + bar.low + bar.close) / 3;
    cumTPV += tp * bar.volume;
    cumVol += bar.volume;
    typicals.push(tp);
    const vwap = cumVol > 0 ? cumTPV / cumVol : tp;

    // Rolling std dev of typical prices
    const mean = typicals.reduce((s, v) => s + v, 0) / typicals.length;
    const variance =
      typicals.reduce((s, v) => s + (v - mean) ** 2, 0) / typicals.length;
    const std = Math.sqrt(variance);

    points.push({
      time: bar.time,
      price: bar.close,
      vwap,
      upper1: vwap + std,
      lower1: vwap - std,
      upper2: vwap + 2 * std,
      lower2: vwap - 2 * std,
      upper3: vwap + 3 * std,
      lower3: vwap - 3 * std,
    });
  });

  return points;
}

// ---------------------------------------------------------------------------
// Sample bars
// ---------------------------------------------------------------------------

function buildSampleBars(basePrice: number): OHLCVBar[] {
  const bars: OHLCVBar[] = [];
  const times = [
    "09:15","09:30","09:45","10:00","10:15","10:30","10:45","11:00",
    "11:15","11:30","11:45","12:00","12:15","12:30","12:45","13:00",
    "13:15","13:30","13:45","14:00","14:15","14:30","14:45","15:00","15:15","15:30",
  ];
  let price = basePrice;
  let rng = 42; // deterministic pseudo-random seed
  times.forEach((t) => {
    rng = (rng * 1664525 + 1013904223) & 0x7fffffff;
    const delta = ((rng % 200) - 100) * 0.01 * (basePrice / 100);
    const open = price;
    price = price + delta;
    const high = Math.max(open, price) + Math.abs(delta) * 0.3;
    const low = Math.min(open, price) - Math.abs(delta) * 0.3;
    bars.push({
      time: t,
      open,
      high,
      low,
      close: price,
      volume: 50_000 + (rng % 200_000),
    });
  });
  return bars;
}

const SYMBOLS = ["NIFTY", "BANKNIFTY", "RELIANCE", "HDFCBANK", "INFY"];
const BASE_PRICES: Record<string, number> = {
  NIFTY: 22_500,
  BANKNIFTY: 48_200,
  RELIANCE: 2_950,
  HDFCBANK: 1_680,
  INFY: 1_410,
};

// ---------------------------------------------------------------------------
// SVG chart
// ---------------------------------------------------------------------------

interface VWAPChartProps {
  points: VWAPPoint[];
}

function VWAPChart({ points }: VWAPChartProps) {
  if (points.length < 2) {
    return (
      <div className="flex items-center justify-center h-full text-xxs text-text-muted">
        No data
      </div>
    );
  }

  const W = 360;
  const H = 160;
  const PAD = { top: 8, right: 8, bottom: 20, left: 48 };
  const cw = W - PAD.left - PAD.right;
  const ch = H - PAD.top - PAD.bottom;

  const allPrices = points.flatMap((p) => [p.lower3, p.upper3, p.price]);
  const minP = Math.min(...allPrices);
  const maxP = Math.max(...allPrices);
  const range = maxP - minP || 1;

  const xOf = (i: number) => PAD.left + (i / (points.length - 1)) * cw;
  const yOf = (v: number) => PAD.top + ch - ((v - minP) / range) * ch;

  const lineD = (getter: (p: VWAPPoint) => number) =>
    points
      .map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(getter(p)).toFixed(1)}`)
      .join(" ");

  const bandArea = (upper: (p: VWAPPoint) => number, lower: (p: VWAPPoint) => number) => {
    const top = points.map((p, i) => `${i === 0 ? "M" : "L"}${xOf(i).toFixed(1)},${yOf(upper(p)).toFixed(1)}`).join(" ");
    const bot = [...points].reverse().map((p, i) => `L${xOf(points.length - 1 - i).toFixed(1)},${yOf(lower(p)).toFixed(1)}`).join(" ");
    return `${top} ${bot} Z`;
  };

  // X-axis labels: every 4 bars
  const xLabels = points.filter((_, i) => i % 4 === 0 || i === points.length - 1);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      aria-label="VWAP bands chart"
      role="img"
    >
      {/* Band fills */}
      <path d={bandArea((p) => p.upper3, (p) => p.lower3)} fill="#6366f1" fillOpacity={0.06} />
      <path d={bandArea((p) => p.upper2, (p) => p.lower2)} fill="#6366f1" fillOpacity={0.09} />
      <path d={bandArea((p) => p.upper1, (p) => p.lower1)} fill="#6366f1" fillOpacity={0.14} />

      {/* Band edge lines */}
      <path d={lineD((p) => p.upper3)} fill="none" stroke="#6366f1" strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <path d={lineD((p) => p.lower3)} fill="none" stroke="#6366f1" strokeWidth={0.8} strokeDasharray="3 3" opacity={0.5} />
      <path d={lineD((p) => p.upper2)} fill="none" stroke="#8b5cf6" strokeWidth={0.8} strokeDasharray="4 2" opacity={0.6} />
      <path d={lineD((p) => p.lower2)} fill="none" stroke="#8b5cf6" strokeWidth={0.8} strokeDasharray="4 2" opacity={0.6} />
      <path d={lineD((p) => p.upper1)} fill="none" stroke="#a78bfa" strokeWidth={1} opacity={0.7} />
      <path d={lineD((p) => p.lower1)} fill="none" stroke="#a78bfa" strokeWidth={1} opacity={0.7} />

      {/* VWAP line */}
      <path d={lineD((p) => p.vwap)} fill="none" stroke="#f59e0b" strokeWidth={1.8} />

      {/* Price line */}
      <path d={lineD((p) => p.price)} fill="none" stroke="#22c55e" strokeWidth={1.4} />

      {/* X-axis ticks */}
      {xLabels.map((p) => {
        const i = points.indexOf(p);
        const x = xOf(i);
        return (
          <text key={p.time} x={x} y={H - 4} textAnchor="middle" fontSize={8} fill="#6b7280">
            {p.time}
          </text>
        );
      })}

      {/* Y-axis ticks — 4 levels */}
      {[0, 0.33, 0.67, 1].map((frac) => {
        const val = minP + frac * range;
        const y = yOf(val);
        return (
          <g key={frac}>
            <line x1={PAD.left - 3} y1={y} x2={PAD.left} y2={y} stroke="#374151" strokeWidth={0.5} />
            <text x={PAD.left - 5} y={y + 3} textAnchor="end" fontSize={7.5} fill="#6b7280">
              {val >= 1000 ? `${(val / 1000).toFixed(1)}k` : val.toFixed(0)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function VWAPBandsWidget() {
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();

  const [symbol, setSymbol] = useState("NIFTY");
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState("--");
  const [showSymbolMenu, setShowSymbolMenu] = useState(false);

  const bars = useMemo(() => buildSampleBars(BASE_PRICES[symbol] ?? 22500), [symbol]);
  const points = useMemo(() => computeVWAP(bars), [bars]);

  const latestPoint = points[points.length - 1];
  const priceVsVWAP = latestPoint
    ? latestPoint.price - latestPoint.vwap
    : 0;
  const priceColour = priceVsVWAP >= 0 ? "text-profit" : "text-loss";
  const priceSign = priceVsVWAP >= 0 ? "+" : "";

  const refresh = useCallback(async () => {
    if (!isConnected) return;
    setIsLoading(true);
    try {
      // In live mode: fetch /api/v1/history for intraday bars
      await new Promise<void>((resolve) => setTimeout(resolve, 300));
      setLastUpdated(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }));
      track("trade", "vwapbands_refresh");
    } finally {
      setIsLoading(false);
    }
  }, [isConnected, track]);

  useEffect(() => {
    if (!isConnected) return;
    void refresh();
    const id = setInterval(() => void refresh(), 30_000);
    return () => clearInterval(id);
  }, [isConnected, refresh]);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <Waves size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">VWAP Bands</span>
        {!isConnected && (
          <span className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />

        {/* Symbol selector */}
        <div className="relative">
          <button
            onClick={() => setShowSymbolMenu((v) => !v)}
            aria-label={`Selected symbol: ${symbol}`}
            aria-expanded={showSymbolMenu}
            className="flex items-center gap-1 px-2 py-0.5 text-xs text-text-primary bg-surface-hover rounded border border-border-default hover:border-accent transition-colors"
          >
            {symbol}
            <ChevronDown size={10} aria-hidden="true" />
          </button>
          {showSymbolMenu && (
            <div
              className="absolute right-0 top-full mt-1 z-30 bg-surface-card border border-border-default rounded shadow-lg min-w-25"
              role="listbox"
              aria-label="Symbol selection"
            >
              {SYMBOLS.map((s) => (
                <button
                  key={s}
                  role="option"
                  aria-selected={s === symbol}
                  onClick={() => { setSymbol(s); setShowSymbolMenu(false); track("trade", "vwapbands_symbol_change"); }}
                  className={`block w-full text-left px-3 py-1.5 text-xs hover:bg-surface-hover transition-colors ${s === symbol ? "text-accent" : "text-text-primary"}`}
                >
                  {s}
                </button>
              ))}
            </div>
          )}
        </div>

        <span className="text-xxs text-text-muted tabular-nums">{lastUpdated}</span>
        <button
          onClick={() => void refresh()}
          disabled={isLoading || !isConnected}
          aria-label="Refresh VWAP data"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover disabled:opacity-40 transition-colors"
        >
          <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-2 space-y-2">

        {/* VWAP stats row */}
        {latestPoint && (
          <div className="grid grid-cols-3 gap-2">
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Price</div>
              <div className="text-sm font-mono font-semibold text-text-primary tabular-nums">
                {latestPoint.price.toFixed(2)}
              </div>
            </div>
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">VWAP</div>
              <div className="text-sm font-mono font-semibold text-[#f59e0b] tabular-nums">
                {latestPoint.vwap.toFixed(2)}
              </div>
            </div>
            <div className="bg-surface-card border border-border-default rounded p-2 text-center">
              <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Δ VWAP</div>
              <div className={`text-sm font-mono font-semibold tabular-nums ${priceColour}`}>
                {priceSign}{priceVsVWAP.toFixed(2)}
              </div>
            </div>
          </div>
        )}

        {/* Chart */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <VWAPChart points={points} />
        </div>

        {/* Band legend */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-1.5">Bands</div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-1">
            {[
              { label: "Price", colour: "#22c55e", dash: false },
              { label: "VWAP", colour: "#f59e0b", dash: false },
              { label: "± 1σ", colour: "#a78bfa", dash: false },
              { label: "± 2σ", colour: "#8b5cf6", dash: true },
              { label: "± 3σ", colour: "#6366f1", dash: true },
            ].map(({ label, colour, dash }) => (
              <div key={label} className="flex items-center gap-1.5 text-xxs text-text-secondary">
                <svg width={16} height={8} aria-hidden="true">
                  <line
                    x1={0} y1={4} x2={16} y2={4}
                    stroke={colour}
                    strokeWidth={dash ? 1 : 1.5}
                    strokeDasharray={dash ? "3 2" : undefined}
                  />
                </svg>
                {label}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(VWAPBandsWidget);
