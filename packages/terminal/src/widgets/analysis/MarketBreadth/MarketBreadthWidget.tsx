/**
 * MarketBreadthWidget — Market breadth analysis for FlintTrade terminal.
 *
 * Features:
 *   - Advance/Decline line chart over time
 *   - Advance/Decline ratio with colour indicator
 *   - New highs vs new lows bar chart (pure SVG)
 *   - McClellan Oscillator value
 *   - Breadth thrust indicator
 *   - Sample data in explore mode; /ft-api/v1/breadth in live mode
 */

import { useState, useMemo, useEffect, memo } from "react";
import { BarChart4, RefreshCw, TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface BreadthPoint {
  time: string;
  advances: number;
  declines: number;
  unchanged: number;
}

interface BreadthData {
  series: BreadthPoint[];
  newHighs: number;
  newLows: number;
  mcclellanOscillator: number;
  breadthThrust: number;
  totalAdvances: number;
  totalDeclines: number;
  totalUnchanged: number;
}

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

const SAMPLE_SERIES: BreadthPoint[] = [
  { time: "09:30", advances: 820, declines: 430, unchanged: 50 },
  { time: "10:00", advances: 900, declines: 370, unchanged: 30 },
  { time: "10:30", advances: 780, declines: 490, unchanged: 30 },
  { time: "11:00", advances: 850, declines: 420, unchanged: 30 },
  { time: "11:30", advances: 920, declines: 350, unchanged: 30 },
  { time: "12:00", advances: 860, declines: 410, unchanged: 30 },
  { time: "12:30", advances: 790, declines: 480, unchanged: 30 },
  { time: "13:00", advances: 830, declines: 440, unchanged: 30 },
  { time: "13:30", advances: 880, declines: 390, unchanged: 30 },
  { time: "14:00", advances: 910, declines: 360, unchanged: 30 },
  { time: "14:30", advances: 870, declines: 400, unchanged: 30 },
  { time: "15:00", advances: 940, declines: 330, unchanged: 30 },
  { time: "15:30", advances: 960, declines: 310, unchanged: 30 },
];

const SAMPLE_DATA: BreadthData = {
  series: SAMPLE_SERIES,
  newHighs: 127,
  newLows: 43,
  mcclellanOscillator: 42.7,
  breadthThrust: 0.618,
  totalAdvances: 960,
  totalDeclines: 310,
  totalUnchanged: 30,
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function adRatio(advances: number, declines: number): number {
  if (declines === 0) return 99;
  return advances / declines;
}

function breadthThrustLabel(value: number): string {
  if (value >= 0.615) return "Strong Bull";
  if (value >= 0.5) return "Bullish";
  if (value >= 0.4) return "Neutral";
  return "Bearish";
}

// ---------------------------------------------------------------------------
// Mini SVG line chart
// ---------------------------------------------------------------------------

interface SparklineProps {
  points: number[];
  width: number;
  height: number;
  colour: string;
}

function Sparkline({ points, width, height, colour }: SparklineProps) {
  if (points.length < 2) return null;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const range = max - min || 1;
  const xs = points.map((_, i) => (i / (points.length - 1)) * width);
  const ys = points.map((v) => height - ((v - min) / range) * height);
  const d = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  return (
    <svg width={width} height={height} aria-hidden="true" className="overflow-visible">
      <path d={d} fill="none" stroke={colour} strokeWidth={1.5} />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// New Highs/Lows SVG bar chart
// ---------------------------------------------------------------------------

interface HighsLowsBarProps {
  highs: number;
  lows: number;
}

function HighsLowsBar({ highs, lows }: HighsLowsBarProps) {
  const total = highs + lows || 1;
  const highPct = (highs / total) * 100;
  const lowPct = (lows / total) * 100;
  return (
    <div className="space-y-1.5" aria-label={`New highs ${highs}, new lows ${lows}`}>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-text-muted w-20 shrink-0">New Highs</span>
        <div className="flex-1 h-3 bg-surface-hover rounded-full overflow-hidden">
          <div
            className="h-full bg-profit rounded-full transition-all"
            style={{ width: `${highPct}%` }}
          />
        </div>
        <span className="text-profit font-mono tabular-nums w-8 text-right">{highs}</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        <span className="text-text-muted w-20 shrink-0">New Lows</span>
        <div className="flex-1 h-3 bg-surface-hover rounded-full overflow-hidden">
          <div
            className="h-full bg-loss rounded-full transition-all"
            style={{ width: `${lowPct}%` }}
          />
        </div>
        <span className="text-loss font-mono tabular-nums w-8 text-right">{lows}</span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function MarketBreadthWidget() {
  const isConnected = useBrokerConnected();
  const track = useTrackBehavior();
  const [data, setData] = useState<BreadthData>(SAMPLE_DATA);
  const [isLoading, setIsLoading] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<string>("--");

  const fetchLive = useMemo(
    () => async () => {
      setIsLoading(true);
      try {
        const res = await fetch("/ft-api/v1/breadth");
        if (!res.ok) throw new Error("Failed to fetch breadth data");
        const json = (await res.json()) as BreadthData;
        setData(json);
        setLastUpdated(new Date().toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata" }));
        track("trade", "market_breadth_refresh");
      } catch {
        // Keep previous data on error
      } finally {
        setIsLoading(false);
      }
    },
    [track],
  );

  useEffect(() => {
    if (!isConnected) {
      setData(SAMPLE_DATA);
      return;
    }
    void fetchLive();
    const id = setInterval(() => void fetchLive(), 60_000);
    return () => clearInterval(id);
  }, [isConnected, fetchLive]);

  const ratio = adRatio(data.totalAdvances, data.totalDeclines);
  const ratioColour =
    ratio >= 2 ? "text-profit" : ratio >= 1 ? "text-warning" : "text-loss";
  const RatioIcon = ratio >= 1.5 ? TrendingUp : ratio >= 0.8 ? Minus : TrendingDown;

  const advanceSeries = data.series.map((p) => p.advances);
  const declineSeries = data.series.map((p) => p.declines);
  const netSeries = data.series.map((p) => p.advances - p.declines);

  const mccColour =
    data.mcclellanOscillator > 0 ? "text-profit" : "text-loss";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <BarChart4 size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Breadth</span>
        {!isConnected && (
          <span className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded">
            Sample
          </span>
        )}
        <div className="flex-1" />
        <span className="text-xxs text-text-muted tabular-nums">{lastUpdated}</span>
        <button
          onClick={() => void fetchLive()}
          disabled={isLoading || !isConnected}
          aria-label="Refresh market breadth"
          className="p-1 rounded text-text-muted hover:text-text-primary hover:bg-surface-hover disabled:opacity-40 transition-colors"
        >
          <RefreshCw size={11} className={isLoading ? "animate-spin" : ""} aria-hidden="true" />
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto space-y-3 p-2">

        {/* A/D Ratio badge row */}
        <div className="grid grid-cols-3 gap-2">
          <div className="bg-surface-card border border-border-default rounded p-2 text-center">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Advances</div>
            <div className="text-sm font-mono font-semibold text-profit tabular-nums">
              {data.totalAdvances.toLocaleString("en-IN")}
            </div>
          </div>
          <div className="bg-surface-card border border-border-default rounded p-2 text-center">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">A/D Ratio</div>
            <div className={`flex items-center justify-center gap-1 text-sm font-mono font-semibold tabular-nums ${ratioColour}`}>
              <RatioIcon size={12} aria-hidden="true" />
              {ratio.toFixed(2)}
            </div>
          </div>
          <div className="bg-surface-card border border-border-default rounded p-2 text-center">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-0.5">Declines</div>
            <div className="text-sm font-mono font-semibold text-loss tabular-nums">
              {data.totalDeclines.toLocaleString("en-IN")}
            </div>
          </div>
        </div>

        {/* Advance/Decline sparklines */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-2">
            A/D Line (intraday)
          </div>
          <div className="flex gap-3 items-end" aria-label="Advance/Decline line chart">
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-profit">
                <span className="inline-block w-3 h-px bg-profit" />
                Advances
              </div>
              <Sparkline points={advanceSeries} width={120} height={32} colour="#22c55e" />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-loss">
                <span className="inline-block w-3 h-px bg-loss" />
                Declines
              </div>
              <Sparkline points={declineSeries} width={120} height={32} colour="#ef4444" />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-accent">
                <span className="inline-block w-3 h-px bg-accent" />
                Net
              </div>
              <Sparkline points={netSeries} width={120} height={32} colour="#6366f1" />
            </div>
          </div>
        </div>

        {/* New Highs / Lows */}
        <div className="bg-surface-card border border-border-default rounded p-2">
          <div className="text-xxs text-text-muted uppercase tracking-wide mb-2">
            52-Week Highs vs Lows
          </div>
          <HighsLowsBar highs={data.newHighs} lows={data.newLows} />
        </div>

        {/* McClellan + Breadth Thrust */}
        <div className="grid grid-cols-2 gap-2">
          <div className="bg-surface-card border border-border-default rounded p-2">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-1">
              McClellan Osc.
            </div>
            <div
              className={`text-base font-mono font-semibold tabular-nums ${mccColour}`}
              aria-label={`McClellan Oscillator ${data.mcclellanOscillator.toFixed(1)}`}
            >
              {data.mcclellanOscillator > 0 ? "+" : ""}
              {data.mcclellanOscillator.toFixed(1)}
            </div>
            <div className="text-xxs text-text-muted mt-0.5">
              {data.mcclellanOscillator > 20
                ? "Overbought"
                : data.mcclellanOscillator < -20
                ? "Oversold"
                : "Neutral range"}
            </div>
          </div>
          <div className="bg-surface-card border border-border-default rounded p-2">
            <div className="text-xxs text-text-muted uppercase tracking-wide mb-1">
              Breadth Thrust
            </div>
            <div
              className="text-base font-mono font-semibold tabular-nums text-accent"
              aria-label={`Breadth thrust ${data.breadthThrust.toFixed(3)}`}
            >
              {data.breadthThrust.toFixed(3)}
            </div>
            <div className="text-xxs text-text-muted mt-0.5">
              {breadthThrustLabel(data.breadthThrust)}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default memo(MarketBreadthWidget);
