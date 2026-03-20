/**
 * MTMMonitorWidget
 *
 * Absorbed from: openalgo/frontend/src/pages/PnLTracker.tsx
 *
 * Key logic absorbed:
 * - createChart / AreaSeries setup (Lightweight Charts v5)
 * - IST tick-mark formatter
 * - Max/min MTM tracking and drawdown calculation
 * - ResizeObserver-based chart resize
 * - Ref-stable formatCurrency pattern
 *
 * Adaptations:
 * - Data source: usePositions() + useFunds() instead of OpenAlgo-internal API
 * - MTM built by summing position.pnl at each refresh tick
 * - Target / stoploss price lines on chart from settingsStore.riskLimits
 * - shadcn Card for stat display, Badge for status indicators
 * - Tailwind CSS v4, no external html2canvas
 * - Chart height fixed to container, no fixed 500px
 */

import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type IPriceLine,
  type UTCTimestamp,
} from "lightweight-charts";
import { TrendingUp, TrendingDown, AlertTriangle, Target } from "lucide-react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { usePositions } from "@/hooks/usePositions";
import { useFunds } from "@/hooks/useFunds";
import { useSettingsStore } from "@/stores/settingsStore";
import type { Position } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";

// ---------------------------------------------------------------------------
// IST time formatter (absorbed from PnLTracker.tsx)
// ---------------------------------------------------------------------------
function istTickFormatter(time: number): string {
  const utcMs = time * 1000;
  const istOffset = 5.5 * 60 * 60 * 1000;
  const d = new Date(utcMs + istOffset);
  const hh = d.getUTCHours().toString().padStart(2, "0");
  const mm = d.getUTCMinutes().toString().padStart(2, "0");
  return `${hh}:${mm}`;
}

// ---------------------------------------------------------------------------
// Currency formatter
// ---------------------------------------------------------------------------
const INR_FMT = new Intl.NumberFormat("en-IN", {
  style: "currency",
  currency: "INR",
  maximumFractionDigits: 0,
});
function formatINR(n: number): string {
  return INR_FMT.format(n);
}

// ---------------------------------------------------------------------------
// MTM Series point
// ---------------------------------------------------------------------------
interface MtmPoint {
  time: UTCTimestamp;
  value: number;
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------
function StatCard({
  label,
  value,
  sub,
  color,
  icon,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
  icon: React.ReactNode;
}) {
  return (
    <Card className="bg-surface-card border-border-default flex-1 min-w-0">
      <CardContent className="p-2">
        <div className="flex items-center gap-1 mb-0.5">
          <span className="text-text-disabled">{icon}</span>
          <span className="text-xxs text-text-muted uppercase tracking-wider">{label}</span>
        </div>
        <div className={`font-mono tabular-nums font-bold text-sm leading-tight ${color}`}>{value}</div>
        {sub && <div className="text-xxs text-text-muted mt-0.5 font-mono tabular-nums">{sub}</div>}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------
export default function MTMMonitorWidget(_props: WidgetProps) {
  const { data: positions } = usePositions();
  const { data: _funds } = useFunds(); // keeps store updated
  const riskLimits = useSettingsStore((s) => s.riskLimits);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const pnlSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const drawdownSeriesRef = useRef<ISeriesApi<"Area"> | null>(null);
  const targetLineRef = useRef<IPriceLine | null>(null);
  const slLineRef = useRef<IPriceLine | null>(null);
  const seriesDataRef = useRef<MtmPoint[]>([]);

  // Track metrics
  const [currentMtm, setCurrentMtm] = useState(0);
  const [maxMtm, setMaxMtm] = useState(0);
  const [maxMtmTime, setMaxMtmTime] = useState("--:--");
  const [minMtm, setMinMtm] = useState(0);
  const [minMtmTime, setMinMtmTime] = useState("--:--");
  const [maxDrawdown, setMaxDrawdown] = useState(0);

  // Stable ref for risk limits (pattern from PnLTracker)
  const riskLimitsRef = useRef(riskLimits);
  useEffect(() => { riskLimitsRef.current = riskLimits; }, [riskLimits]);

  // Build chart (absorbed from PnLTracker.initChart)
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return;

    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const container = chartContainerRef.current;
    const chart = createChart(container, {
      width: container.offsetWidth,
      height: container.offsetHeight,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: "rgba(255,255,255,0.4)",
      },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: {
        borderColor: "rgba(255,255,255,0.08)",
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
      timeScale: {
        borderColor: "rgba(255,255,255,0.08)",
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: istTickFormatter,
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: "rgba(255,255,255,0.3)", style: 2, width: 1, labelVisible: false },
        horzLine: {
          color: "rgba(255,255,255,0.3)",
          style: 2,
          width: 1,
          labelBackgroundColor: "#1e1e2e",
        },
      },
    });

    // MTM PnL area series (absorbed colour from PnLTracker)
    const pnlSeries = chart.addSeries(AreaSeries, {
      lineColor: "#7C3AED",
      topColor: "rgba(124,58,237,0.35)",
      bottomColor: "rgba(124,58,237,0.02)",
      lineWidth: 2,
      priceScaleId: "right",
      priceFormat: {
        type: "custom",
        formatter: (price: number) => formatINR(price),
      },
    });

    // Drawdown area series
    const drawdownSeries = chart.addSeries(AreaSeries, {
      lineColor: "#EF4444",
      topColor: "rgba(239,68,68,0.0)",
      bottomColor: "rgba(239,68,68,0.25)",
      lineWidth: 1,
      priceScaleId: "right",
      priceFormat: {
        type: "custom",
        formatter: (price: number) => formatINR(price),
      },
    });

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

    // Populate with existing series data if any
    if (seriesDataRef.current.length > 0) {
      pnlSeries.setData(seriesDataRef.current);
      chart.timeScale().fitContent();
    }

    // Resize observer (absorbed from PnLTracker handleResize)
    const ro = new ResizeObserver(() => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({
          width: container.offsetWidth,
          height: container.offsetHeight,
        });
      }
    });
    ro.observe(container);

    return () => {
      ro.disconnect();
    };
  }, []);

  // Init chart once on mount
  useEffect(() => {
    const cleanup = initChart();
    return () => {
      cleanup?.();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [initChart]);

  // Update price lines when risk limits change
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

  // Tick MTM from positions (runs on every positions refresh)
  useEffect(() => {
    if (!positions) return;

    const rawPnl = (positions as Position[]).reduce((sum, p) => {
      return sum + (p.pnl ?? 0);
    }, 0);

    const nowSec = Math.floor(Date.now() / 1000) as UTCTimestamp;
    const point: MtmPoint = { time: nowSec, value: rawPnl };

    // Deduplicate by time — keep latest
    const existing = seriesDataRef.current;
    const last = existing[existing.length - 1];
    if (last && last.time === nowSec) {
      existing[existing.length - 1] = point;
    } else {
      existing.push(point);
    }

    // Update chart
    if (pnlSeriesRef.current) {
      pnlSeriesRef.current.setData([...existing]);
    }

    // Compute drawdown series (peak-to-trough from current running max)
    let peak = -Infinity;
    const ddPoints: MtmPoint[] = existing.map((pt) => {
      if (pt.value > peak) peak = pt.value;
      const dd = peak > 0 ? -(peak - pt.value) : 0;
      return { time: pt.time, value: dd };
    });

    if (drawdownSeriesRef.current) {
      drawdownSeriesRef.current.setData(ddPoints);
    }

    if (chartRef.current && existing.length === 1) {
      chartRef.current.timeScale().fitContent();
    }

    // Update metrics
    setCurrentMtm(rawPnl);
    setMaxMtm((prev) => {
      if (rawPnl > prev) {
        setMaxMtmTime(istTickFormatter(nowSec));
        return rawPnl;
      }
      return prev;
    });
    setMinMtm((prev) => {
      if (rawPnl < prev) {
        setMinMtmTime(istTickFormatter(nowSec));
        return rawPnl;
      }
      return prev;
    });
    setMaxDrawdown((prev) => {
      const latestDD = ddPoints[ddPoints.length - 1]?.value ?? 0;
      return latestDD < prev ? latestDD : prev;
    });
  }, [positions]);

  // Derived status badge
  const status = useMemo(() => {
    if (currentMtm >= riskLimits.mtmTarget) return { label: "Target Hit", color: "bg-bullish-bg text-profit border-bullish-border" };
    if (currentMtm <= -Math.abs(riskLimits.mtmStoploss)) return { label: "SL Hit", color: "bg-bearish-bg text-loss border-bearish-border" };
    if (currentMtm < 0 && Math.abs(currentMtm) >= Math.abs(riskLimits.mtmStoploss) * 0.8)
      return { label: "Near SL", color: "bg-atm-bg text-warning border-atm-border" };
    return { label: "Active", color: "bg-surface-hover text-text-muted border-border-default" };
  }, [currentMtm, riskLimits]);

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-border-default shrink-0">
        <span className="text-xxs uppercase tracking-wider text-text-muted font-heading font-semibold">MTM Monitor</span>
        <div className="flex items-center gap-2">
          <span className="text-xxs text-text-muted font-mono tabular-nums">
            Target {formatINR(riskLimits.mtmTarget)} / SL {formatINR(riskLimits.mtmStoploss)}
          </span>
          <Badge className={`text-xxs px-1.5 py-0 border ${status.color}`}>
            {status.label}
          </Badge>
        </div>
      </div>

      {/* Stat row */}
      <div className="flex gap-1 px-2 py-1.5 shrink-0">
        <StatCard
          label="Current MTM"
          value={formatINR(currentMtm)}
          color={currentMtm >= 0 ? "text-profit" : "text-loss"}
          icon={<TrendingUp size={10} />}
        />
        <StatCard
          label="Max MTM"
          value={formatINR(maxMtm)}
          sub={`at ${maxMtmTime}`}
          color="text-profit"
          icon={<Target size={10} />}
        />
        <StatCard
          label="Min MTM"
          value={formatINR(minMtm)}
          sub={`at ${minMtmTime}`}
          color="text-loss"
          icon={<TrendingDown size={10} />}
        />
        <StatCard
          label="Max DD"
          value={formatINR(Math.abs(maxDrawdown))}
          color="text-warning"
          icon={<AlertTriangle size={10} />}
        />
      </div>

      {/* Chart */}
      <div className="flex-1 px-2 pb-1 overflow-hidden">
        <div ref={chartContainerRef} className="w-full h-full relative" />
      </div>

      {/* Legend */}
      <div className="flex items-center gap-3 px-3 pb-1 shrink-0">
        <span className="flex items-center gap-1 text-xxs text-text-muted">
          <span className="inline-block w-2.5 h-0.5 bg-purple-600 rounded" />
          MTM PnL
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
