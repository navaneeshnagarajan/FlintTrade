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
import { FlintMiniSparkline } from "@flinttrade/design-system";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { BreadthHistoryResponseSchema, BreadthResponseSchema } from "@/lib/schemas/ftApi";

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
// Mini line chart
// ---------------------------------------------------------------------------

interface SparklineProps {
  points: number[];
  tone: "profit" | "loss" | "accent";
  ariaLabel: string;
}

function Sparkline({ points, tone, ariaLabel }: SparklineProps) {
  if (points.length < 2) return null;
  const toneClass = tone === "profit" ? "text-profit" : tone === "loss" ? "text-loss" : "text-accent";

  return (
    <FlintMiniSparkline
      points={points}
      positive={tone !== "loss"}
      ariaLabel={ariaLabel}
      className={`h-8 w-full ${toneClass}`}
    />
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
  // The backend tells us whether the snapshot is real or its own sample fallback.
  const [isSample, setIsSample] = useState(true);
  // REAL accumulated daily breadth from /breadth/history — null until the
  // backend has at least two live computations to chart. NEVER a fake series.
  const [liveSeries, setLiveSeries] = useState<BreadthPoint[] | null>(null);

  const fetchHistory = useMemo(
    () => async () => {
      try {
        const res = await fetch("/ft-api/v1/breadth/history?days=30");
        if (!res.ok) return;
        const parsed = BreadthHistoryResponseSchema.safeParse(await res.json());
        if (!parsed.success) {
          console.error("[MarketBreadthWidget] /breadth/history shape mismatch:", parsed.error.issues);
          return;
        }
        // Adopt the series ONLY when the backend says it is real accumulated
        // data; a sample history is never charted next to a live current value.
        if (parsed.data.is_sample_data === false && parsed.data.data.length >= 2) {
          setLiveSeries(
            parsed.data.data.map((p) => ({
              time: p.date,
              advances: p.advances,
              declines: p.declines,
              unchanged: p.unchanged,
            })),
          );
        }
      } catch {
        // keep whatever series state we had
      }
    },
    [],
  );

  const fetchLive = useMemo(
    () => async () => {
      setIsLoading(true);
      try {
        // Registered route is /v1/breadth/current (served at /ft-api/v1/breadth/current);
        // the bare /breadth path 404'd and silently fell back to sample data.
        const res = await fetch("/ft-api/v1/breadth/current");
        if (!res.ok) throw new Error("Failed to fetch breadth data");
        const raw: unknown = await res.json();
        const parsed = BreadthResponseSchema.safeParse(raw);
        if (!parsed.success) {
          console.error("[MarketBreadthWidget] /breadth/current shape mismatch:", parsed.error.issues);
          // Keep previous data on parse failure
        } else {
          // Map snake_case backend fields → camelCase widget fields
          const d = parsed.data.data;
          setIsSample(parsed.data.is_sample_data ?? false);
          setData((prev) => ({
            series: prev.series,
            newHighs: d.new_highs ?? 0,
            newLows: d.new_lows ?? 0,
            mcclellanOscillator: d.mcclellan_oscillator ?? 0,
            breadthThrust: d.breadth_thrust ?? 0,
            totalAdvances: d.advances,
            totalDeclines: d.declines,
            totalUnchanged: d.unchanged,
          }));
        }
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
      setLiveSeries(null);
      return;
    }
    void fetchLive();
    void fetchHistory();
    const id = setInterval(() => {
      void fetchLive();
      void fetchHistory();
    }, 60_000);
    return () => clearInterval(id);
  }, [isConnected, fetchLive, fetchHistory]);

  const ratio = adRatio(data.totalAdvances, data.totalDeclines);
  const ratioColour =
    ratio >= 2 ? "text-profit" : ratio >= 1 ? "text-warning" : "text-loss";
  const RatioIcon = ratio >= 1.5 ? TrendingUp : ratio >= 0.8 ? Minus : TrendingDown;

  // Chart REAL accumulated daily breadth when available; else the sample
  // intraday series (explicitly captioned sample below).
  const series = liveSeries ?? data.series;
  const advanceSeries = series.map((p) => p.advances);
  const declineSeries = series.map((p) => p.declines);
  const netSeries = series.map((p) => p.advances - p.declines);

  const mccColour =
    data.mcclellanOscillator > 0 ? "text-profit" : "text-loss";

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-2 py-1.5 bg-surface-card border-b border-border-default">
        <BarChart4 size={13} className="text-accent shrink-0" aria-hidden="true" />
        <span className="text-xs font-semibold text-text-primary">Market Breadth</span>
        {(!isConnected || isSample) && (
          <span
            className="ml-1 px-1.5 py-0.5 text-xxs bg-warning/10 text-warning border border-warning/30 rounded"
            title="Showing sample breadth data — no live breadth source is reporting yet."
          >
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
            {liveSeries ? (
              <>A/D Line (accumulated live days)</>
            ) : (
              <>
                A/D Line (sample series)
                {isConnected && !isSample && (
                  <span className="normal-case tracking-normal text-warning">
                    {" "}— live history accumulates while connected
                  </span>
                )}
              </>
            )}
          </div>
          <div className="flex gap-3 items-end" aria-label="Advance/Decline line chart">
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-profit">
                <span className="inline-block w-3 h-px bg-profit" />
                Advances
              </div>
              <Sparkline
                points={advanceSeries}
                tone="profit"
                ariaLabel="Market breadth advances sparkline"
              />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-loss">
                <span className="inline-block w-3 h-px bg-loss" />
                Declines
              </div>
              <Sparkline
                points={declineSeries}
                tone="loss"
                ariaLabel="Market breadth declines sparkline"
              />
            </div>
            <div className="flex-1 space-y-1">
              <div className="flex items-center gap-1 text-xxs text-accent">
                <span className="inline-block w-3 h-px bg-accent" />
                Net
              </div>
              <Sparkline
                points={netSeries}
                tone="accent"
                ariaLabel="Market breadth net sparkline"
              />
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
