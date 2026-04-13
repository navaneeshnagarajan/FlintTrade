/**
 * Sparkline — SVG mini price trend indicator for WatchlistWidget rows.
 */

import { TrendingUp, TrendingDown } from "lucide-react";

export interface SparklineProps {
  prices:   number[];
  positive: boolean | null;
}

export function Sparkline({ prices, positive }: SparklineProps) {
  if (!prices || prices.length < 2) {
    return (
      <div className="w-10 h-4 flex items-center justify-center">
        {positive === true  && <TrendingUp  size={10} className="text-profit" />}
        {positive === false && <TrendingDown size={10} className="text-loss"  />}
        {positive == null  && <span className="text-xxs text-text-muted">—</span>}
      </div>
    );
  }

  const W = 40;
  const H = 16;
  const min   = Math.min(...prices);
  const max   = Math.max(...prices);
  const range = max - min || 1;

  const pts = prices.map((p, i) => {
    const x = (i / (prices.length - 1)) * W;
    const y = H - ((p - min) / range) * H;
    return `${x},${y}`;
  });

  const color = positive === false ? "#ef4444" : "#22c55e";

  return (
    <svg
      width={W}
      height={H}
      className="shrink-0"
      role="img"
      aria-label={`Price trend: ${positive === false ? "falling" : "rising"}`}
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="1.2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
    </svg>
  );
}
