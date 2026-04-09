/**
 * PayoffChart — SVG-based options strategy payoff curve.
 *
 * Renders a responsive P&L payoff diagram for a multi-leg option strategy.
 * No external chart library — pure SVG with Tailwind wrapper classes.
 *
 * Features:
 *   - Green/red split curve (above/below zero)
 *   - Gradient fills in profit and loss regions
 *   - Horizontal dashed zero line
 *   - Dashed vertical lines at each unique strike price
 *   - Dotted vertical lines at breakeven crossings
 *   - Solid vertical line at current spot price
 *   - Horizontal dashed lines at max profit / max loss levels
 *   - Hover tooltip showing exact P&L at cursor X position
 */

import { useCallback, useMemo, useRef, useState } from "react";
import type { OptionLeg } from "./LegBuilder";
import { NUM0 } from "./formatters";

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface PayoffChartProps {
  legs: OptionLeg[];
  spotPrice: number;
  lotSize: number;
  maxProfit: number | null; // null = unlimited
  maxLoss: number | null;
  breakevens: number[];
}

// ---------------------------------------------------------------------------
// Chart geometry constants
// ---------------------------------------------------------------------------

const VIEWBOX_W = 600;
const VIEWBOX_H = 220;

const PAD_LEFT   = 54; // space for Y-axis labels
const PAD_RIGHT  = 16;
const PAD_TOP    = 16;
const PAD_BOTTOM = 28; // space for X-axis labels

const PLOT_W = VIEWBOX_W - PAD_LEFT - PAD_RIGHT;
const PLOT_H = VIEWBOX_H - PAD_TOP  - PAD_BOTTOM;

// Number of sample points used to trace the payoff curve
const SAMPLES = 300;

// ---------------------------------------------------------------------------
// Pure helpers — payoff maths (mirrors LegBuilder's legPayoff, no import)
// ---------------------------------------------------------------------------

function singleLegPayoff(leg: OptionLeg, spot: number, lotSize: number): number {
  const intrinsic =
    leg.optionType === "CE"
      ? Math.max(0, spot - leg.strike)
      : Math.max(0, leg.strike - spot);
  const prem = leg.premium ?? 0;
  const sign = leg.side === "BUY" ? 1 : -1;
  return sign * (intrinsic - prem) * leg.lots * lotSize;
}

function totalPayoff(legs: OptionLeg[], spot: number, lotSize: number): number {
  return legs.reduce((sum, leg) => sum + singleLegPayoff(leg, spot, lotSize), 0);
}

// ---------------------------------------------------------------------------
// Coordinate mapping helpers
// ---------------------------------------------------------------------------

/** Map a spot-price value → SVG x coordinate inside the plot area */
function toX(spot: number, xMin: number, xMax: number): number {
  return PAD_LEFT + ((spot - xMin) / (xMax - xMin)) * PLOT_W;
}

/** Map a P&L value → SVG y coordinate inside the plot area */
function toY(pnl: number, yMin: number, yMax: number): number {
  return PAD_TOP + (1 - (pnl - yMin) / (yMax - yMin)) * PLOT_H;
}

// ---------------------------------------------------------------------------
// Tooltip state
// ---------------------------------------------------------------------------

interface TooltipState {
  x: number;       // SVG coordinate
  y: number;       // SVG coordinate
  spot: number;    // underlying price at cursor
  pnl: number;     // P&L at that spot
  visible: boolean;
}

// ---------------------------------------------------------------------------
// Compact rupee formatter for axis labels
// ---------------------------------------------------------------------------

function fmtAxisPnl(v: number): string {
  const abs = Math.abs(v);
  const sign = v < 0 ? "-" : "";
  if (abs >= 1_00_00_000) return `${sign}${(abs / 1_00_00_000).toFixed(1)}Cr`;
  if (abs >= 1_00_000)    return `${sign}${(abs / 1_00_000).toFixed(1)}L`;
  if (abs >= 1_000)       return `${sign}${(abs / 1_000).toFixed(0)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

function fmtAxisSpot(v: number): string {
  if (v >= 1_00_000) return `${(v / 1_000).toFixed(0)}K`;
  return NUM0.format(v);
}

// ---------------------------------------------------------------------------
// PayoffChart component
// ---------------------------------------------------------------------------

export default function PayoffChart({
  legs,
  spotPrice,
  lotSize,
  maxProfit,
  maxLoss,
  breakevens,
}: PayoffChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({
    x: 0, y: 0, spot: 0, pnl: 0, visible: false,
  });

  // ── Derived spot price range ─────────────────────────────────────────────

  const { xMin, xMax, strikes } = useMemo(() => {
    const strikePrices = legs.map((l) => l.strike);
    if (strikePrices.length === 0) {
      const fallback = spotPrice > 0 ? spotPrice : 1000;
      return {
        xMin: fallback * 0.85,
        xMax: fallback * 1.15,
        strikes: [] as number[],
      };
    }
    const minK = Math.min(...strikePrices);
    const maxK = Math.max(...strikePrices);
    return {
      xMin: minK * 0.85,
      xMax: maxK * 1.15,
      strikes: [...new Set(strikePrices)].sort((a, b) => a - b),
    };
  }, [legs, spotPrice]);

  // ── Payoff curve sample points ────────────────────────────────────────────

  const points = useMemo<Array<{ spot: number; pnl: number }>>(() => {
    const step = (xMax - xMin) / SAMPLES;
    return Array.from({ length: SAMPLES + 1 }, (_, i) => {
      const spot = xMin + i * step;
      return { spot, pnl: totalPayoff(legs, spot, lotSize) };
    });
  }, [legs, lotSize, xMin, xMax]);

  // ── Y-axis domain with headroom ───────────────────────────────────────────

  const { yMin, yMax } = useMemo(() => {
    const pnlValues = points.map((p) => p.pnl);
    const rawMin = Math.min(...pnlValues);
    const rawMax = Math.max(...pnlValues);
    const range  = rawMax - rawMin || 1;
    const pad    = range * 0.12;
    return {
      yMin: rawMin - pad,
      yMax: rawMax + pad,
    };
  }, [points]);

  // ── Build the SVG path string for the payoff curve ────────────────────────

  const pathD = useMemo(() => {
    if (points.length === 0) return "";
    const cmds: string[] = [];
    points.forEach((pt, i) => {
      const x = toX(pt.spot, xMin, xMax);
      const y = toY(pt.pnl, yMin, yMax);
      cmds.push(i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`);
    });
    return cmds.join(" ");
  }, [points, xMin, xMax, yMin, yMax]);

  // ── Clip-path rectangle for profit / loss halves ─────────────────────────

  const zeroY = toY(0, yMin, yMax);

  // Area path for profit fill (above zero line)
  const profitFillD = useMemo(() => {
    if (points.length === 0) return "";
    const clampedY = Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H, zeroY));
    const leftX  = toX(points[0].spot,  xMin, xMax);
    const rightX = toX(points[points.length - 1].spot, xMin, xMax);
    return `${pathD} L ${rightX} ${clampedY} L ${leftX} ${clampedY} Z`;
  }, [pathD, points, xMin, xMax, zeroY]);

  const lossFillD = useMemo(() => {
    if (points.length === 0) return "";
    const clampedY = Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H, zeroY));
    const leftX  = toX(points[0].spot,  xMin, xMax);
    const rightX = toX(points[points.length - 1].spot, xMin, xMax);
    return `${pathD} L ${rightX} ${clampedY} L ${leftX} ${clampedY} Z`;
  }, [pathD, points, xMin, xMax, zeroY]);

  // ── Split curve into profit and loss segments ─────────────────────────────

  /**
   * Split the ordered points into continuous segments that are either
   * entirely above zero or entirely below zero.  Inserts an interpolated
   * zero-crossing point at each sign change so the coloured segments
   * meet exactly on the zero line.
   */
  const segments = useMemo(() => {
    if (points.length === 0) return [];

    type Segment = { above: boolean; pts: Array<{ spot: number; pnl: number }> };
    const segs: Segment[] = [];
    let current: Segment = { above: points[0].pnl >= 0, pts: [points[0]] };

    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1];
      const curr = points[i];
      const prevAbove = prev.pnl >= 0;
      const currAbove = curr.pnl >= 0;

      if (prevAbove !== currAbove) {
        // Zero crossing — interpolate
        const t = -prev.pnl / (curr.pnl - prev.pnl);
        const crossSpot = prev.spot + t * (curr.spot - prev.spot);
        const crossPt   = { spot: crossSpot, pnl: 0 };

        current.pts.push(crossPt);
        segs.push(current);
        current = { above: currAbove, pts: [crossPt, curr] };
      } else {
        current.pts.push(curr);
      }
    }
    segs.push(current);
    return segs;
  }, [points]);

  // ── Axis tick helpers ─────────────────────────────────────────────────────

  const yTicks = useMemo<number[]>(() => {
    const range = yMax - yMin;
    const magnitude = Math.pow(10, Math.floor(Math.log10(range)));
    const step = magnitude >= range / 3
      ? magnitude / 5
      : magnitude >= range / 6
      ? magnitude / 2
      : magnitude;
    const ticks: number[] = [];
    const startTick = Math.ceil(yMin / step) * step;
    for (let v = startTick; v <= yMax + step * 0.01; v += step) {
      ticks.push(parseFloat(v.toFixed(10)));
    }
    return ticks.slice(0, 8); // cap to avoid clutter
  }, [yMin, yMax]);

  const xTicks = useMemo<number[]>(() => {
    const range = xMax - xMin;
    const magnitude = Math.pow(10, Math.floor(Math.log10(range)));
    const step = magnitude >= range / 3
      ? magnitude / 2
      : magnitude >= range / 5
      ? magnitude
      : magnitude * 2;
    const ticks: number[] = [];
    const startTick = Math.ceil(xMin / step) * step;
    for (let v = startTick; v <= xMax + step * 0.01; v += step) {
      ticks.push(parseFloat(v.toFixed(10)));
    }
    return ticks.slice(0, 8);
  }, [xMin, xMax]);

  // ── Mouse interaction ─────────────────────────────────────────────────────

  const handleMouseMove = useCallback(
    (e: React.MouseEvent<SVGSVGElement>) => {
      const svg = svgRef.current;
      if (!svg) return;

      const rect   = svg.getBoundingClientRect();
      const scaleX = VIEWBOX_W / rect.width;
      const svgX   = (e.clientX - rect.left) * scaleX;

      // Clamp to plot area
      if (svgX < PAD_LEFT || svgX > PAD_LEFT + PLOT_W) {
        setTooltip((t) => ({ ...t, visible: false }));
        return;
      }

      const spot = xMin + ((svgX - PAD_LEFT) / PLOT_W) * (xMax - xMin);
      const pnl  = totalPayoff(legs, spot, lotSize);
      const y    = toY(pnl, yMin, yMax);

      setTooltip({ x: svgX, y, spot, pnl, visible: true });
    },
    [legs, lotSize, xMin, xMax, yMin, yMax],
  );

  const handleMouseLeave = useCallback(() => {
    setTooltip((t) => ({ ...t, visible: false }));
  }, []);

  // ── Helpers for spot / max level lines ────────────────────────────────────

  const spotX = spotPrice > 0
    ? toX(Math.max(xMin, Math.min(xMax, spotPrice)), xMin, xMax)
    : null;

  const maxProfitY = maxProfit != null ? toY(maxProfit, yMin, yMax) : null;
  const maxLossY   = maxLoss   != null ? toY(maxLoss,   yMin, yMax) : null;

  // ── Tooltip box placement ─────────────────────────────────────────────────

  const ttWidth  = 96;
  const ttHeight = 32;
  const ttX = tooltip.x + ttWidth + 8 > VIEWBOX_W
    ? tooltip.x - ttWidth - 4
    : tooltip.x + 4;
  const ttY = tooltip.y - ttHeight / 2;

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <div
      className="w-full px-2 pb-2 pt-1"
      aria-label="Options payoff chart"
      role="img"
    >
      <svg
        ref={svgRef}
        viewBox={`0 0 ${VIEWBOX_W} ${VIEWBOX_H}`}
        className="w-full h-auto select-none"
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
        aria-hidden="true"
      >
        <defs>
          {/* Profit gradient — green fading to transparent at zero */}
          <linearGradient id="pc-profit-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor="var(--color-profit, #22c55e)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--color-profit, #22c55e)" stopOpacity="0.04" />
          </linearGradient>

          {/* Loss gradient — red fading to transparent at zero */}
          <linearGradient id="pc-loss-fill" x1="0" y1="1" x2="0" y2="0">
            <stop offset="0%"   stopColor="var(--color-loss, #ef4444)" stopOpacity="0.25" />
            <stop offset="100%" stopColor="var(--color-loss, #ef4444)" stopOpacity="0.04" />
          </linearGradient>

          {/* Clip above zero line for the profit fill */}
          <clipPath id="pc-clip-profit">
            <rect
              x={PAD_LEFT}
              y={PAD_TOP}
              width={PLOT_W}
              height={Math.max(0, zeroY - PAD_TOP)}
            />
          </clipPath>

          {/* Clip below zero line for the loss fill */}
          <clipPath id="pc-clip-loss">
            <rect
              x={PAD_LEFT}
              y={zeroY}
              width={PLOT_W}
              height={Math.max(0, PAD_TOP + PLOT_H - zeroY)}
            />
          </clipPath>
        </defs>

        {/* ── Plot area background ──────────────────────────────────────── */}
        <rect
          x={PAD_LEFT}
          y={PAD_TOP}
          width={PLOT_W}
          height={PLOT_H}
          fill="transparent"
        />

        {/* ── Y-axis grid lines ─────────────────────────────────────────── */}
        {yTicks.map((v) => {
          const y = toY(v, yMin, yMax);
          if (y < PAD_TOP || y > PAD_TOP + PLOT_H) return null;
          return (
            <g key={`ytick-${v}`}>
              <line
                x1={PAD_LEFT}
                y1={y}
                x2={PAD_LEFT + PLOT_W}
                y2={y}
                stroke="var(--color-border-default, #2a2a3a)"
                strokeWidth="0.5"
                strokeOpacity="0.5"
              />
              <text
                x={PAD_LEFT - 4}
                y={y + 3.5}
                textAnchor="end"
                fontSize="8"
                fontFamily="'JetBrains Mono', monospace"
                fill="var(--color-text-muted, #888)"
              >
                {fmtAxisPnl(v)}
              </text>
            </g>
          );
        })}

        {/* ── X-axis tick labels ────────────────────────────────────────── */}
        {xTicks.map((v) => {
          const x = toX(v, xMin, xMax);
          if (x < PAD_LEFT || x > PAD_LEFT + PLOT_W) return null;
          return (
            <text
              key={`xtick-${v}`}
              x={x}
              y={PAD_TOP + PLOT_H + 11}
              textAnchor="middle"
              fontSize="7.5"
              fontFamily="'JetBrains Mono', monospace"
              fill="var(--color-text-muted, #888)"
            >
              {fmtAxisSpot(v)}
            </text>
          );
        })}

        {/* ── Max profit dashed horizontal line ────────────────────────── */}
        {maxProfitY != null && maxProfit != null && maxProfitY >= PAD_TOP && maxProfitY <= PAD_TOP + PLOT_H && (
          <g>
            <line
              x1={PAD_LEFT}
              y1={maxProfitY}
              x2={PAD_LEFT + PLOT_W}
              y2={maxProfitY}
              stroke="var(--color-profit, #22c55e)"
              strokeWidth="0.75"
              strokeDasharray="4 3"
              strokeOpacity="0.6"
            />
            <text
              x={PAD_LEFT + PLOT_W - 2}
              y={maxProfitY - 3}
              textAnchor="end"
              fontSize="7.5"
              fontFamily="'JetBrains Mono', monospace"
              fill="var(--color-profit, #22c55e)"
              fillOpacity="0.85"
            >
              {fmtAxisPnl(maxProfit)}
            </text>
          </g>
        )}

        {/* ── Max loss dashed horizontal line ──────────────────────────── */}
        {maxLossY != null && maxLoss != null && maxLossY >= PAD_TOP && maxLossY <= PAD_TOP + PLOT_H && (
          <g>
            <line
              x1={PAD_LEFT}
              y1={maxLossY}
              x2={PAD_LEFT + PLOT_W}
              y2={maxLossY}
              stroke="var(--color-loss, #ef4444)"
              strokeWidth="0.75"
              strokeDasharray="4 3"
              strokeOpacity="0.6"
            />
            <text
              x={PAD_LEFT + PLOT_W - 2}
              y={maxLossY + 9}
              textAnchor="end"
              fontSize="7.5"
              fontFamily="'JetBrains Mono', monospace"
              fill="var(--color-loss, #ef4444)"
              fillOpacity="0.85"
            >
              {fmtAxisPnl(maxLoss)}
            </text>
          </g>
        )}

        {/* ── Strike price vertical dashed lines ───────────────────────── */}
        {strikes.map((k) => {
          const x = toX(k, xMin, xMax);
          return (
            <g key={`strike-${k}`}>
              <line
                x1={x}
                y1={PAD_TOP}
                x2={x}
                y2={PAD_TOP + PLOT_H}
                stroke="var(--color-border-default, #2a2a3a)"
                strokeWidth="0.75"
                strokeDasharray="3 3"
                strokeOpacity="0.7"
              />
              <text
                x={x}
                y={PAD_TOP - 3}
                textAnchor="middle"
                fontSize="7"
                fontFamily="'JetBrains Mono', monospace"
                fill="var(--color-text-muted, #888)"
                fillOpacity="0.8"
                aria-label={`Strike ${k}`}
              >
                {fmtAxisSpot(k)}
              </text>
            </g>
          );
        })}

        {/* ── Breakeven vertical dotted lines ──────────────────────────── */}
        {breakevens.map((bk) => {
          const x = toX(bk, xMin, xMax);
          if (x < PAD_LEFT || x > PAD_LEFT + PLOT_W) return null;
          return (
            <g key={`bk-${bk}`}>
              <line
                x1={x}
                y1={PAD_TOP}
                x2={x}
                y2={PAD_TOP + PLOT_H}
                stroke="var(--color-atm-text, #e8c97a)"
                strokeWidth="0.8"
                strokeDasharray="1.5 2.5"
                strokeOpacity="0.75"
              />
              <text
                x={x + 2}
                y={PAD_TOP + PLOT_H / 2}
                fontSize="7"
                fontFamily="'JetBrains Mono', monospace"
                fill="var(--color-atm-text, #e8c97a)"
                fillOpacity="0.85"
                aria-label={`Breakeven ${bk}`}
              >
                {fmtAxisSpot(bk)}
              </text>
            </g>
          );
        })}

        {/* ── Zero line (horizontal dashed) ────────────────────────────── */}
        {zeroY >= PAD_TOP && zeroY <= PAD_TOP + PLOT_H && (
          <line
            x1={PAD_LEFT}
            y1={zeroY}
            x2={PAD_LEFT + PLOT_W}
            y2={zeroY}
            stroke="var(--color-border-default, #2a2a3a)"
            strokeWidth="1"
            strokeDasharray="5 3"
            strokeOpacity="0.9"
            data-testid="zero-line"
          />
        )}

        {/* ── Profit fill (above zero) ──────────────────────────────────── */}
        <path
          d={profitFillD}
          fill="url(#pc-profit-fill)"
          clipPath="url(#pc-clip-profit)"
        />

        {/* ── Loss fill (below zero) ────────────────────────────────────── */}
        <path
          d={lossFillD}
          fill="url(#pc-loss-fill)"
          clipPath="url(#pc-clip-loss)"
        />

        {/* ── Payoff curve — coloured segments ─────────────────────────── */}
        {segments.map((seg, i) => {
          if (seg.pts.length < 2) return null;
          const cmds: string[] = [];
          seg.pts.forEach((pt, j) => {
            const x = toX(pt.spot, xMin, xMax);
            const y = toY(pt.pnl, yMin, yMax);
            cmds.push(j === 0 ? `M ${x} ${y}` : `L ${x} ${y}`);
          });
          return (
            <path
              key={`seg-${i}`}
              d={cmds.join(" ")}
              fill="none"
              stroke={seg.above
                ? "var(--color-profit, #22c55e)"
                : "var(--color-loss, #ef4444)"}
              strokeWidth="1.5"
              strokeLinejoin="round"
              strokeLinecap="round"
            />
          );
        })}

        {/* ── Current spot price vertical solid line ───────────────────── */}
        {spotX != null && (
          <g>
            <line
              x1={spotX}
              y1={PAD_TOP}
              x2={spotX}
              y2={PAD_TOP + PLOT_H}
              stroke="var(--color-accent, #7c6af7)"
              strokeWidth="1"
              strokeOpacity="0.8"
            />
            <text
              x={spotX + 2}
              y={PAD_TOP + 10}
              fontSize="7"
              fontFamily="'JetBrains Mono', monospace"
              fill="var(--color-accent, #7c6af7)"
              fillOpacity="0.9"
            >
              {fmtAxisSpot(spotPrice)}
            </text>
          </g>
        )}

        {/* ── Hover crosshair + dot ─────────────────────────────────────── */}
        {tooltip.visible && (
          <g>
            {/* Vertical crosshair */}
            <line
              x1={tooltip.x}
              y1={PAD_TOP}
              x2={tooltip.x}
              y2={PAD_TOP + PLOT_H}
              stroke="var(--color-text-muted, #888)"
              strokeWidth="0.5"
              strokeDasharray="2 2"
              strokeOpacity="0.5"
            />
            {/* Dot on curve */}
            <circle
              cx={tooltip.x}
              cy={Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H, tooltip.y))}
              r={3}
              fill={tooltip.pnl >= 0
                ? "var(--color-profit, #22c55e)"
                : "var(--color-loss, #ef4444)"}
              stroke="var(--color-surface-card, #16161f)"
              strokeWidth="1.5"
            />
          </g>
        )}

        {/* ── Tooltip box ───────────────────────────────────────────────── */}
        {tooltip.visible && (
          <g>
            <rect
              x={ttX}
              y={Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H - ttHeight, ttY))}
              width={ttWidth}
              height={ttHeight}
              rx="3"
              fill="var(--color-surface-card, #16161f)"
              stroke="var(--color-border-default, #2a2a3a)"
              strokeWidth="0.75"
              opacity="0.95"
            />
            <text
              x={ttX + 6}
              y={Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H - ttHeight, ttY)) + 11}
              fontSize="7.5"
              fontFamily="'JetBrains Mono', monospace"
              fill="var(--color-text-muted, #888)"
            >
              {fmtAxisSpot(tooltip.spot)}
            </text>
            <text
              x={ttX + 6}
              y={Math.max(PAD_TOP, Math.min(PAD_TOP + PLOT_H - ttHeight, ttY)) + 23}
              fontSize="8"
              fontFamily="'JetBrains Mono', monospace"
              fontWeight="600"
              fill={tooltip.pnl >= 0
                ? "var(--color-profit, #22c55e)"
                : "var(--color-loss, #ef4444)"}
            >
              {tooltip.pnl >= 0 ? "+" : ""}
              {fmtAxisPnl(tooltip.pnl)}
            </text>
          </g>
        )}

        {/* ── Plot border ───────────────────────────────────────────────── */}
        <rect
          x={PAD_LEFT}
          y={PAD_TOP}
          width={PLOT_W}
          height={PLOT_H}
          fill="none"
          stroke="var(--color-border-default, #2a2a3a)"
          strokeWidth="0.5"
          strokeOpacity="0.4"
        />
      </svg>
    </div>
  );
}
