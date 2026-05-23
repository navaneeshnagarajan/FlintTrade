/**
 * MiniChartCard — NIFTY sparkline SVG with timeframe pills.
 *
 * Uses a simple inline SVG sparkline. Real chart data would come from
 * the history API via TanStack Query, but we render a static placeholder
 * until the data layer is wired in Phase 2.
 */

import { useState } from "react";
import { BentoCard } from "@/components/bento/BentoCard";
import { TrendingUp } from "lucide-react";

type Timeframe = "1D" | "1W" | "1M" | "3M";
const TIMEFRAMES: Timeframe[] = ["1D", "1W", "1M", "3M"];

/**
 * Normalise an array of values to fit within [0, height] for SVG rendering.
 */
function normalise(values: number[], height: number): number[] {
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;
  return values.map((v) => height - ((v - min) / range) * height);
}

/**
 * Build an SVG polyline points string from y-values.
 */
function buildPoints(ys: number[], width: number): string {
  const step = width / (ys.length - 1);
  return ys.map((y, i) => `${i * step},${y}`).join(" ");
}

// Placeholder sparkline data — will be replaced by real API data in Phase 2
const PLACEHOLDER: Record<Timeframe, number[]> = {
  "1D": [22100, 22150, 22090, 22200, 22180, 22250, 22230, 22300, 22280, 22350, 22320, 22400],
  "1W": [21800, 21950, 22100, 22050, 22200, 22150, 22300],
  "1M": [21000, 21200, 21500, 21300, 21700, 22000, 22200, 22400],
  "3M": [20000, 20500, 21000, 20800, 21500, 22000, 22400],
};

export function MiniChartCard() {
  const [timeframe, setTimeframe] = useState<Timeframe>("1D");

  const data = PLACEHOLDER[timeframe];
  const lastValue = data[data.length - 1];
  const firstValue = data[0];
  const change = lastValue - firstValue;
  const changePct = ((change / firstValue) * 100).toFixed(2);
  const positive = change >= 0;

  const svgWidth = 300;
  const svgHeight = 60;
  const ys = normalise(data, svgHeight - 4);
  const points = buildPoints(ys, svgWidth);
  const strokeColor = positive ? "var(--color-bullish-text)" : "var(--color-bearish-text)";

  return (
    <BentoCard size="wide" label="NIFTY Chart" data-testid="mini-chart-card">
      <div className="p-4 h-full flex flex-col gap-3">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <TrendingUp size={13} className="text-text-muted" aria-hidden="true" />
            <p className="text-[10px] font-medium uppercase tracking-widest text-text-muted">
              NIFTY 50
            </p>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-semibold text-text-primary">
              {lastValue.toLocaleString("en-IN")}
            </span>
            <span
              className="font-mono text-xs"
              style={{ color: positive ? "var(--color-bullish-text)" : "var(--color-bearish-text)" }}
            >
              {positive ? "+" : ""}{change.toFixed(0)} ({positive ? "+" : ""}{changePct}%)
            </span>
          </div>
        </div>

        {/* Sparkline */}
        <div className="flex-1 relative">
          <svg
            viewBox={`0 0 ${svgWidth} ${svgHeight}`}
            preserveAspectRatio="none"
            width="100%"
            height="100%"
            aria-label={`NIFTY 50 ${timeframe} sparkline`}
            role="img"
          >
            <polyline
              points={points}
              fill="none"
              stroke={strokeColor}
              strokeWidth="1.5"
              strokeLinecap="round"
              strokeLinejoin="round"
              opacity="0.9"
            />
            {/* Area fill */}
            <polyline
              points={`0,${svgHeight} ${points} ${svgWidth},${svgHeight}`}
              fill={strokeColor}
              opacity="0.06"
            />
          </svg>
        </div>

        {/* Timeframe pills */}
        <div className="flex items-center gap-1">
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              type="button"
              onClick={() => setTimeframe(tf)}
              aria-pressed={timeframe === tf}
              className="px-2 py-0.5 rounded-md text-[10px] font-medium transition-colors"
              style={{
                background: timeframe === tf
                  ? "var(--color-surface-active)"
                  : "transparent",
                color: timeframe === tf ? "var(--color-text-primary)" : "var(--color-text-muted)",
                border: "1px solid",
                borderColor: timeframe === tf
                  ? "var(--color-border-default)"
                  : "transparent",
              }}
            >
              {tf}
            </button>
          ))}
        </div>
      </div>
    </BentoCard>
  );
}
