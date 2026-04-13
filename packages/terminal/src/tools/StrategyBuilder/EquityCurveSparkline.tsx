// Equity curve sparkline rendered as inline SVG — no charting library needed
// Extracted from StrategyBuilderTool.tsx

import type { EquityPoint } from "./types";

interface Props {
  curve: EquityPoint[];
}

export function EquityCurveSparkline({ curve }: Props) {
  const W = 600;
  const H = 40;
  const pad = 2;

  const minE = Math.min(...curve.map((p) => p.equity));
  const maxE = Math.max(...curve.map((p) => p.equity));
  const rangeE = maxE - minE || 1;
  const minB = curve[0].bar;
  const maxB = curve[curve.length - 1].bar || 1;
  const rangeB = maxB - minB || 1;

  const toX = (b: number) => pad + ((b - minB) / rangeB) * (W - pad * 2);
  const toY = (e: number) => H - pad - ((e - minE) / rangeE) * (H - pad * 2);

  const pathD = curve
    .map((p, i) => `${i === 0 ? "M" : "L"}${toX(p.bar).toFixed(1)},${toY(p.equity).toFixed(1)}`)
    .join(" ");

  const isPositive = curve[curve.length - 1].equity >= 10000;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      className="w-full h-10"
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      {/* Zero baseline at 10000 */}
      <line
        x1={pad}
        y1={toY(10000).toFixed(1)}
        x2={W - pad}
        y2={toY(10000).toFixed(1)}
        stroke="#2a2a3a"
        strokeWidth="0.5"
      />
      <path
        d={pathD}
        fill="none"
        stroke={isPositive ? "#22c55e" : "#ef4444"}
        strokeWidth="1.5"
      />
    </svg>
  );
}
