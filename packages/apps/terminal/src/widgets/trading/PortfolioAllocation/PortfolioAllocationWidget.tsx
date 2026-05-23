/**
 * PortfolioAllocationWidget — Portfolio allocation donut chart for FlintTrade.
 *
 * Two views:
 *   - Asset class breakdown (Equity, F&O, Commodity, Currency, Cash)
 *   - Sector breakdown (Banking, IT, Energy, etc.)
 *
 * Pure SVG donut — no chart library dependency.
 * Live data from positions + holdings API; sample data in explore mode.
 */

import { useState, useMemo, useEffect, memo } from "react";
import { PieChart } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTrackBehavior } from "@/hooks/useTrackBehavior";
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { useQuery } from "@tanstack/react-query";
import { getPositionbook, getHoldings } from "@/services/api";
import {
  SAMPLE_ASSET_ALLOCATION,
  SAMPLE_SECTOR_ALLOCATION,
} from "./sampleData";
import type { AllocationSlice } from "./sampleData";
import type { Position, Holding } from "@/types/api";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

type ViewMode = "asset" | "sector";

const SECTOR_MAP: Record<string, string> = {
  HDFCBANK: "Banking", ICICIBANK: "Banking", SBIN: "Banking", KOTAKBANK: "Banking",
  AXISBANK: "Banking", BANKBARODA: "Banking",
  TCS: "IT", INFY: "IT", WIPRO: "IT", TECHM: "IT", HCLTECH: "IT",
  RELIANCE: "Energy", ONGC: "Energy", BPCL: "Energy", IOC: "Energy",
  MARUTI: "Auto", TATAMOTORS: "Auto", M_M: "Auto", BAJAJ_AUTO: "Auto",
  SUNPHARMA: "Pharma", DRREDDY: "Pharma", CIPLA: "Pharma",
  HINDUNILVR: "FMCG", ITC: "FMCG", NESTLEIND: "FMCG",
  TATASTEEL: "Metals", HINDALCO: "Metals", JSWSTEEL: "Metals",
  LT: "Infra", NTPC: "Infra", POWERGRID: "Infra",
};

function getSector(symbol: string): string {
  return SECTOR_MAP[symbol.toUpperCase().replace("-", "_")] ?? "Other";
}

function getAssetClass(exchange: string, product: string): string {
  if (exchange.includes("MCX") || exchange.includes("NCDEX")) return "Commodity";
  if (exchange.includes("CDS") || exchange === "BCD") return "Currency";
  if (product === "NRML" || exchange === "NFO" || exchange === "BFO") return "F&O";
  return "Equity";
}

const ASSET_COLOURS: Record<string, string> = {
  Equity: "#6366f1", "F&O": "#f59e0b", Commodity: "#22c55e",
  Currency: "#06b6d4", Cash: "#94a3b8",
};

const SECTOR_COLOURS = [
  "#6366f1", "#8b5cf6", "#f59e0b", "#22c55e", "#10b981",
  "#06b6d4", "#f97316", "#94a3b8",
];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fmt(v: number): string {
  if (v >= 1e7) return `₹${(v / 1e7).toFixed(2)}Cr`;
  if (v >= 1e5) return `₹${(v / 1e5).toFixed(2)}L`;
  if (v >= 1e3) return `₹${(v / 1e3).toFixed(1)}K`;
  return `₹${v.toFixed(0)}`;
}

function buildSlices(
  data: AllocationSlice[],
  total: number,
): Array<AllocationSlice & { pct: number; startAngle: number; endAngle: number }> {
  let cumAngle = -Math.PI / 2; // Start at top (12 o'clock)
  return data.map((s) => {
    const pct = total > 0 ? s.value / total : 0;
    const arc = pct * 2 * Math.PI;
    const start = cumAngle;
    cumAngle += arc;
    return { ...s, pct, startAngle: start, endAngle: cumAngle };
  });
}

// ---------------------------------------------------------------------------
// SVG donut
// ---------------------------------------------------------------------------

interface DonutProps {
  slices: Array<AllocationSlice & { pct: number; startAngle: number; endAngle: number }>;
  total: number;
  size?: number;
  thickness?: number;
  hovered: string | null;
  onHover: (label: string | null) => void;
}

function Donut({ slices, total, size = 160, thickness = 36, hovered, onHover }: DonutProps) {
  const cx = size / 2;
  const cy = size / 2;
  const outerR = size / 2 - 4;
  const innerR = outerR - thickness;

  function describePath(start: number, end: number, outer: number, inner: number): string {
    const gap = 0.02;
    const s = start + gap;
    const e = end - gap;
    if (e <= s) return "";

    const ox1 = cx + outer * Math.cos(s);
    const oy1 = cy + outer * Math.sin(s);
    const ox2 = cx + outer * Math.cos(e);
    const oy2 = cy + outer * Math.sin(e);
    const ix1 = cx + inner * Math.cos(e);
    const iy1 = cy + inner * Math.sin(e);
    const ix2 = cx + inner * Math.cos(s);
    const iy2 = cy + inner * Math.sin(s);
    const large = e - s > Math.PI ? 1 : 0;

    return [
      `M ${ox1} ${oy1}`,
      `A ${outer} ${outer} 0 ${large} 1 ${ox2} ${oy2}`,
      `L ${ix1} ${iy1}`,
      `A ${inner} ${inner} 0 ${large} 0 ${ix2} ${iy2}`,
      "Z",
    ].join(" ");
  }

  return (
    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      role="img"
      aria-label="Portfolio allocation donut chart"
    >
      {slices.map((s) => (
        <path
          key={s.label}
          d={describePath(s.startAngle, s.endAngle, outerR, innerR)}
          fill={s.colour}
          opacity={hovered === null || hovered === s.label ? 1 : 0.35}
          className="cursor-pointer transition-opacity duration-150"
          onMouseEnter={() => onHover(s.label)}
          onMouseLeave={() => onHover(null)}
          role="button"
          aria-label={`${s.label}: ${fmt(s.value)} (${(s.pct * 100).toFixed(1)}%)`}
          tabIndex={0}
          onFocus={() => onHover(s.label)}
          onBlur={() => onHover(null)}
        />
      ))}
      {/* Centre text */}
      <text
        x={cx}
        y={cy - 8}
        textAnchor="middle"
        className="fill-text-primary"
        style={{ fontSize: 11, fontFamily: "JetBrains Mono, monospace", fontWeight: 600 }}
      >
        {hovered
          ? fmt(slices.find((s) => s.label === hovered)?.value ?? 0)
          : fmt(total)
        }
      </text>
      <text
        x={cx}
        y={cy + 8}
        textAnchor="middle"
        className="fill-text-muted"
        style={{ fontSize: 9, fontFamily: "Inter, sans-serif" }}
      >
        {hovered ?? "Total"}
      </text>
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Main widget
// ---------------------------------------------------------------------------

function PortfolioAllocationWidget() {
  const track = useTrackBehavior();
  const isConnected = useBrokerConnected();

  const [view, setView] = useState<ViewMode>("asset");
  const [hovered, setHovered] = useState<string | null>(null);

  useEffect(() => {
    track("trade", "widget_view_portfolio_allocation");
  }, [track]);

  const { data: positions } = useQuery({
    queryKey: ["positionbook"],
    queryFn: getPositionbook,
    enabled: isConnected,
    staleTime: 30_000,
  });

  const { data: holdings } = useQuery({
    queryKey: ["holdings"],
    queryFn: getHoldings,
    enabled: isConnected,
    staleTime: 5 * 60_000,
  });

  const liveAssetSlices = useMemo<AllocationSlice[]>(() => {
    if (!isConnected) return SAMPLE_ASSET_ALLOCATION;
    const map = new Map<string, number>();
    for (const p of (positions ?? []) as Position[]) {
      if (p.quantity === 0) continue;
      const ac = getAssetClass(p.exchange, p.product);
      map.set(ac, (map.get(ac) ?? 0) + Math.abs(p.quantity * p.ltp));
    }
    for (const h of (holdings ?? []) as Holding[]) {
      if (h.quantity === 0) continue;
      map.set("Equity", (map.get("Equity") ?? 0) + h.quantity * h.ltp);
    }
    if (map.size === 0) return SAMPLE_ASSET_ALLOCATION;
    return [...map.entries()].map(([label, value], i) => ({
      label,
      value,
      colour: ASSET_COLOURS[label] ?? SECTOR_COLOURS[i % SECTOR_COLOURS.length],
    }));
  }, [positions, holdings, isConnected]);

  const liveSectorSlices = useMemo<AllocationSlice[]>(() => {
    if (!isConnected) return SAMPLE_SECTOR_ALLOCATION;
    const map = new Map<string, number>();
    for (const h of (holdings ?? []) as Holding[]) {
      if (h.quantity === 0) continue;
      const sector = getSector(h.symbol);
      map.set(sector, (map.get(sector) ?? 0) + h.quantity * h.ltp);
    }
    if (map.size === 0) return SAMPLE_SECTOR_ALLOCATION;
    return [...map.entries()].map(([label, value], i) => ({
      label,
      value,
      colour: SECTOR_COLOURS[i % SECTOR_COLOURS.length],
    }));
  }, [holdings, isConnected]);

  const rawSlices = view === "asset" ? liveAssetSlices : liveSectorSlices;
  const total = rawSlices.reduce((s, d) => s + d.value, 0);
  const slices = buildSlices(rawSlices, total);

  return (
    <div className="h-full flex flex-col bg-surface-base overflow-hidden">

      {/* Header */}
      <div className="flex-none flex items-center gap-2 px-3 py-2 bg-surface-card border-b border-border-default">
        <PieChart size={13} className="text-text-muted" aria-hidden="true" />
        <span className="text-xs font-medium text-text-primary">Portfolio Allocation</span>
        <div className="flex-1" />
        {!isConnected && (
          <span className="text-xxs text-text-muted border border-border-subtle rounded px-1.5 py-0.5">
            sample data
          </span>
        )}
      </div>

      {/* View toggle */}
      <div
        className="flex-none flex items-center gap-px px-3 py-1.5 bg-surface-elevated border-b border-border-subtle"
        role="tablist"
        aria-label="Allocation view"
      >
        {(["asset", "sector"] as ViewMode[]).map((v) => (
          <button
            key={v}
            role="tab"
            aria-selected={view === v}
            onClick={() => setView(v)}
            className={cn(
              "px-3 py-1 text-xxs font-medium rounded transition-colors capitalize",
              view === v
                ? "bg-accent/15 text-accent border border-accent/30"
                : "text-text-muted hover:text-text-primary hover:bg-surface-hover",
            )}
          >
            {v === "asset" ? "Asset Class" : "Sector"}
          </button>
        ))}
      </div>

      {/* Chart + legend */}
      <div className="flex-1 overflow-auto flex flex-col items-center py-3 gap-4">
        {/* Donut */}
        <Donut
          slices={slices}
          total={total}
          size={164}
          thickness={38}
          hovered={hovered}
          onHover={setHovered}
        />

        {/* Legend */}
        <div className="w-full px-4 space-y-1.5" role="list" aria-label="Allocation breakdown">
          {slices.map((s) => (
            <div
              key={s.label}
              role="listitem"
              className={cn(
                "flex items-center gap-2 px-2 py-1 rounded cursor-pointer transition-colors",
                hovered === s.label ? "bg-surface-hover" : "hover:bg-surface-hover",
              )}
              onMouseEnter={() => setHovered(s.label)}
              onMouseLeave={() => setHovered(null)}
              aria-label={`${s.label}: ${fmt(s.value)}, ${(s.pct * 100).toFixed(1)}%`}
            >
              <span
                className="w-2.5 h-2.5 rounded-sm shrink-0"
                style={{ backgroundColor: s.colour }}
                aria-hidden="true"
              />
              <span className="flex-1 text-xs text-text-primary truncate">{s.label}</span>
              <span className="text-xs font-mono tabular-nums text-text-secondary shrink-0">
                {fmt(s.value)}
              </span>
              <span className="w-10 text-right text-xs font-mono tabular-nums text-text-muted shrink-0">
                {(s.pct * 100).toFixed(1)}%
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default memo(PortfolioAllocationWidget);
