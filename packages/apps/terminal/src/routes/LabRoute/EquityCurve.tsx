import { useEffect, useMemo, useRef } from "react";
import { motion } from "framer-motion";
import type { Time } from "lightweight-charts";
import { createFlintAreaChart } from "@flinttrade/design-system";
import { useLightweightChartTheme } from "@/hooks/useChartTheme";
import { lightweightAreaRuntime } from "@/lib/lightweightChartRuntime";
import { motionConfig } from "@/lib/motion";

export interface EquityCurveProps {
  curve: Array<{ timestamp: string; equity: number }>;
  initialEquity: number;
}

export function EquityCurve({ curve, initialEquity }: EquityCurveProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartTheme = useLightweightChartTheme();

  const sampled = useMemo(() => {
    const step = Math.max(1, Math.floor(curve.length / 120));
    return curve
      .filter((_, i) => i % step === 0)
      .map((p) => ({
        time: Math.floor(new Date(p.timestamp).getTime() / 1000) as unknown as Time,
        value: p.equity,
      }))
      .filter((p) => Number.isFinite(p.time as number));
  }, [curve]);

  const lastEquity = sampled[sampled.length - 1]?.value ?? initialEquity;
  const isPositive = lastEquity >= initialEquity;
  const lineColor = isPositive ? "#34d399" : "#f87171";
  const topColor = isPositive ? "rgba(52,211,153,0.32)" : "rgba(248,113,113,0.28)";
  const bottomColor = isPositive ? "rgba(52,211,153,0.03)" : "rgba(248,113,113,0.03)";

  useEffect(() => {
    if (!containerRef.current || sampled.length === 0) return;

    const flintChart = createFlintAreaChart(
      lightweightAreaRuntime,
      containerRef.current,
      chartTheme,
      {
        ariaLabel: "Backtest equity curve chart",
        height: 144,
        crosshair: { vertLine: { visible: true }, horzLine: { visible: true } },
        handleScroll: false,
        handleScale: false,
        series: [
          {
            id: "equity",
            options: {
              lineColor,
              topColor,
              bottomColor,
              lineWidth: 2,
              priceFormat: { type: "price", precision: 0, minMove: 1 },
              priceScaleId: "right",
            },
          },
        ],
      },
    );

    flintChart.seriesById.equity.setData(sampled);
    flintChart.chart.timeScale().fitContent();

    return () => {
      flintChart.remove();
    };
  }, [bottomColor, chartTheme, lineColor, sampled, topColor]);

  if (curve.length === 0) return null;

  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={motionConfig.transitions.fade}
    >
      <div
        ref={containerRef}
        className="h-36 min-h-36 w-full overflow-hidden rounded-md border border-border-default bg-surface-card"
        style={{ height: 144 }}
      />
    </motion.div>
  );
}
