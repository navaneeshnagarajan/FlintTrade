/**
 * LiveView — the P&L Monitor's home view (retired IntradayPnL + MTM Monitor).
 *
 * Shows the running net P&L headline, the realised/unrealised/peak/trough/
 * drawdown stat cards, the per-strategy breakdown, and the session equity
 * curve as a Lightweight Charts area pair (net P&L + drawdown shading) with
 * target/stop-loss price lines.
 *
 * The price lines render `settingsStore.riskLimits` — the SAME setting the
 * Risk widget renders as utilisation bars. One source, two projections; this
 * file must never grow its own copy of those limits.
 *
 * The chart plots the parent's corrected netPnL series. Before the merge the
 * MTM Monitor plotted `totalPositionMtm(positions)`, which omits realised P&L
 * booked by partial closes earlier in the session (only the tradebook can
 * restore that), so the chart and the Intraday P&L headline disagreed on the
 * same book. Now both read one figure.
 */

import { useCallback, useEffect, useMemo, useRef } from "react";
import {
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
} from "lightweight-charts";
import {
  FLINT_TRANSPARENT_CHART_LAYOUT,
  createFlintAreaChart,
} from "@flinttrade/design-system";
import { TrendingUp, TrendingDown, Minus } from "lucide-react";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightAreaRuntime } from "@/lib/lightweightChartRuntime";
import {
  fmtINR,
  fmtSigned,
  formatINRWhole,
  istTickFormatter,
  pnlColor,
  type MtmPoint,
  type StrategyPnL,
} from "./pnlMonitorShared";

// ---------------------------------------------------------------------------
// Theme helper — reads CSS custom properties at call time so charts re-read
// on each init and respect the active theme.
// ---------------------------------------------------------------------------
function getThemeColor(varName: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(varName).trim() || fallback;
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

interface StatCardProps {
  label: string;
  value: string;
  sub?: string;
  colorCls?: string;
}

function StatCard({ label, value, sub, colorCls = "text-text-primary" }: StatCardProps) {
  return (
    <div className="flex flex-col items-center gap-0.5 bg-surface-card border border-border-default rounded px-2 py-1 min-w-0 flex-1">
      <span className="text-xxs text-text-muted uppercase tracking-wider whitespace-nowrap">{label}</span>
      <span className={`text-xs font-mono tabular-nums font-semibold ${colorCls}`}>{value}</span>
      {sub && <span className="text-xxs text-text-muted font-mono tabular-nums">{sub}</span>}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Live view
// ---------------------------------------------------------------------------

export interface LiveViewProps {
  netPnL: number;
  realisedPnL: number;
  unrealisedPnL: number;
  peakPnL: number;
  peakTime: string;
  minPnL: number;
  minTime: string;
  maxDrawdown: number;
  byStrategy: StrategyPnL[];
  series: MtmPoint[];
  loading: boolean;
  riskLimits: { mtmTarget: number; mtmStoploss: number };
}

export function LiveView({
  netPnL,
  realisedPnL,
  unrealisedPnL,
  peakPnL,
  peakTime,
  minPnL,
  minTime,
  maxDrawdown,
  byStrategy,
  series,
  loading,
  riskLimits,
}: LiveViewProps) {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const pnlSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const drawdownSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const targetLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);
  const chartTheme = useLightweightChartTheme();

  // Refs so the chart init never closes over stale props. The series data
  // lives in the PARENT (it must keep accumulating while the operator looks
  // at Summary/Drawdown); this view only projects it.
  const seriesRef = useRef<MtmPoint[]>(series);
  const riskLimitsRef = useRef(riskLimits);
  useEffect(() => { riskLimitsRef.current = riskLimits; }, [riskLimits]);

  /**
   * Push the current series into both chart series.
   *
   * The drawdown series seeds its running peak at 0, matching the stat-card
   * tracker: the session starts flat, so a book that falls from ₹0 straight
   * into loss IS in drawdown. The retired MTM Monitor guarded `peak > 0` and
   * reported zero drawdown for exactly that case — a bug this merge fixes.
   */
  const renderSeries = useCallback((fitContent: boolean) => {
    const points = seriesRef.current;
    if (pnlSeriesRef.current) {
      pnlSeriesRef.current.setData([...points]);
    }
    let peak = 0;
    const ddPoints: MtmPoint[] = points.map((pt) => {
      if (pt.value > peak) peak = pt.value;
      return { time: pt.time, value: pt.value - peak };
    });
    if (drawdownSeriesRef.current) {
      drawdownSeriesRef.current.setData(ddPoints);
    }
    if (fitContent && chartRef.current && points.length > 0) {
      chartRef.current.timeScale().fitContent();
    }
  }, []);

  // Build chart (adapted from the retired MTM Monitor's initChart).
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const container = chartContainerRef.current;
    const flintChart = createFlintAreaChart(lightweightAreaRuntime, container, chartTheme, {
      ariaLabel: "P&L monitor mark-to-market chart",
      layout: FLINT_TRANSPARENT_CHART_LAYOUT,
      rightPriceScale: {
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
      timeScale: {
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: istTickFormatter,
      },
      crosshair: {
        mode: 0,
        vertLine: { color: getThemeColor("--color-text-muted", "#a0a0b0"), style: 2, width: 1, labelVisible: false },
        horzLine: {
          color: getThemeColor("--color-text-muted", "#a0a0b0"),
          style: 2,
          width: 1,
          labelBackgroundColor: getThemeColor("--color-card", "#16161f"),
        },
      },
      defaultSeriesOptions: {
        priceScaleId: "right",
        priceFormat: {
          type: "custom",
          formatter: (price: number) => formatINRWhole(price),
        },
      },
      series: [
        {
          id: "pnl",
          options: {
            lineColor: "#7C3AED",
            topColor: "rgba(124,58,237,0.35)",
            bottomColor: "rgba(124,58,237,0.02)",
            lineWidth: 2,
          },
        },
        {
          id: "drawdown",
          options: {
            lineColor: "#EF4444",
            topColor: "rgba(239,68,68,0.0)",
            bottomColor: "rgba(239,68,68,0.25)",
            lineWidth: 1,
          },
        },
      ],
    });
    const chart = flintChart.chart;
    const pnlSeries = flintChart.seriesById.pnl;
    const drawdownSeries = flintChart.seriesById.drawdown;

    // Target price line
    const targetLine = pnlSeries.createPriceLine({
      price: riskLimitsRef.current.mtmTarget,
      color: "#22C55E",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "Target",
    });

    // Stoploss price line
    const slLine = pnlSeries.createPriceLine({
      price: -Math.abs(riskLimitsRef.current.mtmStoploss),
      color: "#EF4444",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "SL",
    });

    chartRef.current = chart;
    pnlSeriesRef.current = pnlSeries;
    drawdownSeriesRef.current = drawdownSeries;
    targetLineRef.current = targetLine;
    slLineRef.current = slLine;

    // Repopulate on re-init (tab switches unmount this view; the parent's
    // series survives and the curve must come back intact).
    renderSeries(true);

    return () => flintChart.remove();
  }, [chartTheme, renderSeries]);

  // Init chart once on mount (and on theme change)
  useEffect(() => {
    const cleanup = initChart();
    return () => {
      cleanup?.();
      chartRef.current = null;
      pnlSeriesRef.current = null;
      drawdownSeriesRef.current = null;
      targetLineRef.current = null;
      slLineRef.current = null;
    };
  }, [initChart]);

  // Update price lines when the shared risk limits change
  useEffect(() => {
    if (!pnlSeriesRef.current) return;
    if (targetLineRef.current) {
      pnlSeriesRef.current.removePriceLine(targetLineRef.current);
    }
    if (slLineRef.current) {
      pnlSeriesRef.current.removePriceLine(slLineRef.current);
    }
    targetLineRef.current = pnlSeriesRef.current.createPriceLine({
      price: riskLimits.mtmTarget,
      color: "#22C55E",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "Target",
    });
    slLineRef.current = pnlSeriesRef.current.createPriceLine({
      price: -Math.abs(riskLimits.mtmStoploss),
      color: "#EF4444",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "SL",
    });
  }, [riskLimits.mtmTarget, riskLimits.mtmStoploss]);

  // Project the parent's accumulated series on every refresh. Fit the time
  // scale only while the curve is first forming.
  useEffect(() => {
    seriesRef.current = series;
    renderSeries(series.length <= 1);
  }, [series, renderSeries]);

  const netColor = pnlColor(netPnL);
  const NetIcon = netPnL > 0 ? TrendingUp : netPnL < 0 ? TrendingDown : Minus;

  // Show strategy breakdown only when there is more than one strategy
  const showStrategies = useMemo(
    () => byStrategy.length > 1 || (byStrategy.length === 1 && byStrategy[0].strategy !== "default"),
    [byStrategy],
  );

  return (
    <div className="h-full flex flex-col overflow-hidden">
      {/* Big P&L number */}
      <div className="flex items-center justify-center gap-2 py-2.5 shrink-0">
        <NetIcon size={18} className={netColor} />
        <span
          data-testid="net-pnl"
          className={`font-mono tabular-nums font-bold text-2xl ${netColor}`}
        >
          {fmtSigned(netPnL)}
        </span>
      </div>

      {/* Stats row */}
      <div className="flex gap-1.5 px-2 pb-2 shrink-0">
        <StatCard
          label="Realised"
          value={fmtSigned(realisedPnL)}
          colorCls={pnlColor(realisedPnL)}
        />
        <StatCard
          label="Unrealised"
          value={fmtSigned(unrealisedPnL)}
          colorCls={pnlColor(unrealisedPnL)}
        />
        <StatCard
          label="Peak P&L"
          value={fmtSigned(peakPnL)}
          sub={peakPnL !== 0 ? `at ${peakTime}` : undefined}
          colorCls={peakPnL > 0 ? "text-profit" : "text-text-muted"}
        />
        <StatCard
          label="Min P&L"
          value={fmtSigned(minPnL)}
          sub={minPnL !== 0 ? `at ${minTime}` : undefined}
          colorCls={minPnL < 0 ? "text-loss" : "text-text-muted"}
        />
        <StatCard
          label="Max DD"
          value={maxDrawdown > 0 ? `-${fmtINR(maxDrawdown)}` : "—"}
          colorCls={maxDrawdown > 0 ? "text-loss" : "text-text-muted"}
        />
      </div>

      {/* Per-strategy breakdown */}
      {showStrategies && (
        <div className="shrink-0 max-h-24 overflow-auto px-2 pb-2">
          <p className="text-xxs text-text-muted uppercase tracking-wider mb-1">By Strategy</p>
          <div className="space-y-0.5">
            {byStrategy.map(({ strategy, pnl }) => (
              <div
                key={strategy}
                className="flex items-center justify-between px-2 py-0.5 rounded bg-surface-card border border-border-subtle"
              >
                <span className="text-xs text-text-secondary font-mono truncate max-w-32">{strategy}</span>
                <span className={`text-xs font-mono tabular-nums font-medium ${pnlColor(pnl)}`}>
                  {fmtSigned(pnl)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Loading state */}
      {loading && series.length === 0 && (
        <div className="shrink-0 flex items-center justify-center py-1 text-text-muted text-xs">
          Loading positions…
        </div>
      )}

      {/* Chart */}
      <div className="flex-1 px-2 pb-1 overflow-hidden">
        <div ref={chartContainerRef} className="w-full h-full relative" />
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 px-3 pb-1 shrink-0">
        <span className="flex items-center gap-1 text-xxs text-text-muted">
          <span className="inline-block w-2.5 h-0.5 bg-purple-600 rounded" />
          Net P&amp;L
        </span>
        <span className="flex items-center gap-1 text-xxs text-text-muted">
          <span className="inline-block w-2.5 h-0.5 bg-loss rounded" />
          Drawdown
        </span>
        <span className="flex items-center gap-1 text-xxs text-text-muted">
          <span className="inline-block w-2.5 h-px border-t border-dashed border-profit" />
          Target
        </span>
        <span className="flex items-center gap-1 text-xxs text-text-muted">
          <span className="inline-block w-2.5 h-px border-t border-dashed border-loss" />
          SL
        </span>
      </div>
    </div>
  );
}
