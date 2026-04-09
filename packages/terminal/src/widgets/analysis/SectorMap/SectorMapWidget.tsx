/**
 * SectorMapWidget
 *
 * Absorbed from: openalgo-chart/src/components/SectorHeatmap/SectorHeatmapModal.tsx
 * Treemap algorithm: openalgo-chart/src/components/SectorHeatmap/utils/treemapLayout.ts
 * Color helpers:    openalgo-chart/src/components/SectorHeatmap/utils/heatmapHelpers.ts
 * Constants:        openalgo-chart/src/components/SectorHeatmap/constants/heatmapConstants.ts
 * RRG view:         absorbed from sector-rotation-map reference repo
 *
 * Adaptations for FlintTrade:
 * - CSS Modules → Tailwind CSS v4
 * - Modal shell removed; rendered inline as a dockview widget
 * - External market data services → placeholder (no live sector API in OpenAlgo)
 * - shadcn Select for view mode, shadcn Badge for stats
 * - Jotai atom for sector data cache
 * - Positions feed from usePositions() for real holding symbols
 * - RRG canvas view added as third mode (useRRGData hook → ftApi → screener/rrg.py)
 */

import { useMemo, useState, useRef, useCallback, useEffect, memo } from "react";
import type { MouseEvent } from "react";
import { LayoutGrid, Grid3X3, BarChart3, TrendingUp, TrendingDown } from "lucide-react";
import { atom, useAtom } from "jotai";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { usePositions } from "@/hooks/usePositions";
import { useRRGData } from "@/hooks/useRRGData";
import type { Position } from "@/types/api";
import type { RRGResponse, SectorRRG, RRGQuadrant } from "@/services/ftApi";
import type { WidgetProps } from "@/types/widgets";
import { divergingColourScale } from "@/lib/colourScale";

// ---------------------------------------------------------------------------
// Treemap layout algorithm (absorbed verbatim from treemapLayout.ts)
// ---------------------------------------------------------------------------
interface TreemapItem {
  value: number;
  [key: string]: unknown;
}

interface TreemapLayoutItem extends TreemapItem {
  x: number;
  y: number;
  width: number;
  height: number;
}

function calculateTreemapLayout(
  items: TreemapItem[],
  x: number,
  y: number,
  width: number,
  height: number,
): TreemapLayoutItem[] {
  if (items.length === 0 || width <= 0 || height <= 0) return [];
  const totalValue = items.reduce((sum, item) => sum + item.value, 0);
  if (totalValue <= 0) return [];

  const result: TreemapLayoutItem[] = [];
  let remaining = [...items];
  let currentX = x;
  let currentY = y;
  let currentWidth = width;
  let currentHeight = height;
  let remainingValue = totalValue;

  while (remaining.length > 0) {
    const isHorizontal = currentWidth >= currentHeight;
    const mainSide = isHorizontal ? currentHeight : currentWidth;
    let row = [remaining[0]];
    let rowValue = remaining[0].value;
    let worstRatio = Infinity;

    for (let i = 1; i < remaining.length; i++) {
      const testRow = [...row, remaining[i]];
      const testValue = rowValue + remaining[i].value;
      const rowThickness =
        (testValue / remainingValue) * (isHorizontal ? currentWidth : currentHeight);
      let testWorst = 0;
      testRow.forEach((item) => {
        const itemLength = (item.value / testValue) * mainSide;
        const ratio = Math.max(rowThickness / itemLength, itemLength / rowThickness);
        testWorst = Math.max(testWorst, ratio);
      });
      if (testWorst <= worstRatio) {
        row = testRow;
        rowValue = testValue;
        worstRatio = testWorst;
      } else {
        break;
      }
    }

    const rowFraction = rowValue / remainingValue;
    const rowSize = isHorizontal ? rowFraction * currentWidth : rowFraction * currentHeight;
    let offset = 0;

    row.forEach((item) => {
      const itemFraction = item.value / rowValue;
      const itemSize = itemFraction * mainSide;
      if (isHorizontal) {
        result.push({ ...item, x: currentX, y: currentY + offset, width: rowSize, height: itemSize });
      } else {
        result.push({ ...item, x: currentX + offset, y: currentY, width: itemSize, height: rowSize });
      }
      offset += itemSize;
    });

    remainingValue -= rowValue;
    remaining = remaining.slice(row.length);
    if (isHorizontal) {
      currentX += rowSize;
      currentWidth -= rowSize;
    } else {
      currentY += rowSize;
      currentHeight -= rowSize;
    }
  }

  return result;
}

// ---------------------------------------------------------------------------
// Color helpers — delegates to the shared divergingColourScale utility
// ---------------------------------------------------------------------------
const getChangeColor = divergingColourScale;

function getBarWidth(change: number, maxChange: number): number {
  return Math.min((Math.abs(change) / Math.max(maxChange, 1)) * 100, 100);
}

function formatPrice(price: number): string {
  if (price >= 1_000) return price.toFixed(0);
  if (price >= 100) return price.toFixed(1);
  return price.toFixed(2);
}

// ---------------------------------------------------------------------------
// Sector mapping (NSE sectors — simplified static map)
// ---------------------------------------------------------------------------
const SECTOR_MAP: Record<string, string> = {
  RELIANCE: "Energy", ONGC: "Energy", IOC: "Energy", BPCL: "Energy",
  TCS: "IT", INFY: "IT", WIPRO: "IT", HCLTECH: "IT", TECHM: "IT",
  HDFCBANK: "Banking", ICICIBANK: "Banking", SBIN: "Banking", KOTAKBANK: "Banking", AXISBANK: "Banking",
  HINDUNILVR: "FMCG", ITC: "FMCG", NESTLEIND: "FMCG", BRITANNIA: "FMCG",
  MARUTI: "Auto", TATAMOTORS: "Auto", M_M: "Auto", BAJAJ_AUTO: "Auto",
  SUNPHARMA: "Pharma", DRREDDY: "Pharma", CIPLA: "Pharma", DIVISLAB: "Pharma",
  LT: "Infra", POWERGRID: "Infra", NTPC: "Infra",
  BAJFINANCE: "NBFC", BAJAJFINSV: "NBFC", HDFCLIFE: "NBFC",
  TITAN: "Consumer", ASIANPAINT: "Consumer", ADANIPORTS: "Logistics",
};

function getSector(symbol: string): string {
  const clean = symbol.replace(/[-&.]/g, "_").toUpperCase();
  return SECTOR_MAP[clean] ?? "Others";
}

// ---------------------------------------------------------------------------
// RRG Canvas renderer
// ---------------------------------------------------------------------------

/** Quadrant fill colours (semi-transparent) and dot colours (opaque). */
const RRG_QUADRANT_COLOURS: Record<RRGQuadrant | "neutral", { fill: string; dot: string; label: string }> = {
  leading:   { fill: "rgba(0, 200, 83, 0.07)",   dot: "#00C853", label: "Leading" },
  weakening: { fill: "rgba(255, 193, 7, 0.07)",  dot: "#FFC107", label: "Weakening" },
  improving: { fill: "rgba(33, 150, 243, 0.07)", dot: "#2196F3", label: "Improving" },
  lagging:   { fill: "rgba(244, 67, 54, 0.07)",  dot: "#F44336", label: "Lagging" },
  neutral:   { fill: "rgba(120, 120, 120, 0.05)",dot: "#888888", label: "Neutral" },
};

/** Unique dot colour per sector index (12 sectors). */
const SECTOR_DOT_COLOURS: string[] = [
  "#29B6F6", // IT         — light blue
  "#66BB6A", // Banking    — green
  "#AB47BC", // Pharma     — purple
  "#FFA726", // FMCG       — orange
  "#EF5350", // Auto       — red
  "#26C6DA", // Metals     — cyan
  "#D4E157", // Realty     — lime
  "#FF7043", // Energy     — deep orange
  "#78909C", // Infra      — blue grey
  "#EC407A", // Media      — pink
  "#42A5F5", // FinServ    — blue
  "#26A69A", // Healthcare — teal
];

interface RRGCanvasProps {
  data: RRGResponse;
  tailLength: number;
}

/** Canvas-based RRG scatter plot.
 *
 * Layout:
 *   - x-axis: RS-Ratio  (centre = 100)
 *   - y-axis: RS-Momentum (centre = 100, y-up convention)
 *   - Four coloured quadrant backgrounds
 *   - Sector trails (fading dots) with current position as filled circle
 *   - Axis labels and quadrant labels
 */
const RRGCanvas = memo(function RRGCanvas({ data, tailLength }: RRGCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const [hoveredSector, setHoveredSector] = useState<string | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });

  // Precompute axis bounds: cover ±3 around 100 with some padding
  const AXIS_MIN = 96.5;
  const AXIS_MAX = 103.5;

  // Convert RRG coordinate → canvas pixel
  const toCanvasX = useCallback((rsRatio: number, canvasW: number, pad: number): number => {
    return pad + ((rsRatio - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasW - 2 * pad);
  }, []);

  const toCanvasY = useCallback((rsMomentum: number, canvasH: number, pad: number): number => {
    // Canvas y increases downward, but we want momentum-up = up on screen
    return (canvasH - pad) - ((rsMomentum - AXIS_MIN) / (AXIS_MAX - AXIS_MIN)) * (canvasH - 2 * pad);
  }, []);

  const draw = useCallback(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;
    const PAD = 32;
    const cx = toCanvasX(100, W, PAD);
    const cy = toCanvasY(100, H, PAD);

    ctx.clearRect(0, 0, W, H);

    // --- Quadrant fills ---
    // Leading: top-right (RS-Ratio > 100, RS-Mom > 100) → green
    ctx.fillStyle = RRG_QUADRANT_COLOURS.leading.fill;
    ctx.fillRect(cx, PAD, W - cx - PAD, cy - PAD);

    // Weakening: bottom-right (RS-Ratio > 100, RS-Mom < 100) → yellow
    ctx.fillStyle = RRG_QUADRANT_COLOURS.weakening.fill;
    ctx.fillRect(cx, cy, W - cx - PAD, H - cy - PAD);

    // Improving: top-left (RS-Ratio < 100, RS-Mom > 100) → blue
    ctx.fillStyle = RRG_QUADRANT_COLOURS.improving.fill;
    ctx.fillRect(PAD, PAD, cx - PAD, cy - PAD);

    // Lagging: bottom-left (RS-Ratio < 100, RS-Mom < 100) → red
    ctx.fillStyle = RRG_QUADRANT_COLOURS.lagging.fill;
    ctx.fillRect(PAD, cy, cx - PAD, H - cy - PAD);

    // --- Grid lines at centre ---
    ctx.strokeStyle = "rgba(255,255,255,0.12)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.beginPath();
    ctx.moveTo(cx, PAD);
    ctx.lineTo(cx, H - PAD);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(PAD, cy);
    ctx.lineTo(W - PAD, cy);
    ctx.stroke();
    ctx.setLineDash([]);

    // --- Axis labels ---
    ctx.font = "9px Inter, sans-serif";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.textAlign = "center";
    ctx.fillText("100", cx, H - PAD + 12);
    ctx.textAlign = "left";
    ctx.fillText("RS-Ratio →", W - PAD - 36, H - PAD + 12);

    // Y-axis
    ctx.save();
    ctx.translate(12, cy);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.fillText("RS-Momentum ↑", 0, 0);
    ctx.restore();

    // --- Quadrant corner labels ---
    const labelSize = 8;
    ctx.font = `bold ${labelSize}px Inter, sans-serif`;
    ctx.fillStyle = RRG_QUADRANT_COLOURS.leading.dot;
    ctx.textAlign = "right";
    ctx.fillText("LEADING", W - PAD - 2, PAD + 10);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.weakening.dot;
    ctx.fillText("WEAKENING", W - PAD - 2, H - PAD - 4);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.improving.dot;
    ctx.textAlign = "left";
    ctx.fillText("IMPROVING", PAD + 2, PAD + 10);

    ctx.fillStyle = RRG_QUADRANT_COLOURS.lagging.dot;
    ctx.fillText("LAGGING", PAD + 2, H - PAD - 4);

    // --- Sector trails and dots ---
    data.sectors.forEach((sector, idx) => {
      const dotColour = SECTOR_DOT_COLOURS[idx % SECTOR_DOT_COLOURS.length];
      const tail = sector.tail;
      if (tail.length === 0) return;

      const isHovered = hoveredSector === sector.symbol;

      // Draw trail (fading line from oldest to newest)
      if (tail.length >= 2) {
        for (let i = 1; i < tail.length; i++) {
          const prev = tail[i - 1];
          const curr = tail[i];
          const alpha = (i / (tail.length - 1)) * 0.6 + 0.1;
          ctx.strokeStyle = dotColour.replace(")", `,${alpha})`).replace("rgb", "rgba");
          ctx.lineWidth = isHovered ? 2 : 1;
          ctx.beginPath();
          ctx.moveTo(toCanvasX(prev.rs_ratio, W, PAD), toCanvasY(prev.rs_momentum, H, PAD));
          ctx.lineTo(toCanvasX(curr.rs_ratio, W, PAD), toCanvasY(curr.rs_momentum, H, PAD));
          ctx.stroke();
        }
      }

      // Trail ghost dots (small, fading)
      tail.slice(0, -1).forEach((pt, i) => {
        const alpha = ((i + 1) / tail.length) * 0.45;
        const r = isHovered ? 3 : 2;
        ctx.beginPath();
        ctx.arc(toCanvasX(pt.rs_ratio, W, PAD), toCanvasY(pt.rs_momentum, H, PAD), r, 0, Math.PI * 2);
        ctx.fillStyle = dotColour.replace(")", `,${alpha})`).replace("rgb", "rgba");
        ctx.fill();
      });

      // Current position dot (last point — full opacity, larger)
      const last = tail[tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dotR = isHovered ? 7 : 5;

      ctx.beginPath();
      ctx.arc(lx, ly, dotR, 0, Math.PI * 2);
      ctx.fillStyle = dotColour;
      ctx.fill();
      if (isHovered) {
        ctx.strokeStyle = "rgba(255,255,255,0.8)";
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }

      // Sector name label next to the dot
      const shortName = sector.name.replace("NIFTY ", "").replace(" INDEX", "");
      ctx.font = isHovered ? "bold 9px Inter, sans-serif" : "9px Inter, sans-serif";
      ctx.fillStyle = isHovered ? "rgba(255,255,255,0.95)" : "rgba(255,255,255,0.6)";
      ctx.textAlign = lx > W / 2 ? "right" : "left";
      const lxLabel = lx > W / 2 ? lx - dotR - 2 : lx + dotR + 2;
      ctx.fillText(shortName, lxLabel, ly + 3);
    });
  }, [data, hoveredSector, toCanvasX, toCanvasY]);

  // Redraw when data/size/hover changes
  useEffect(() => {
    draw();
  }, [draw]);

  // Resize observer to keep canvas sharp
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        const canvas = canvasRef.current;
        if (!canvas) return;
        const { width, height } = entry.contentRect;
        const dpr = window.devicePixelRatio || 1;
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
        canvas.style.width = `${width}px`;
        canvas.style.height = `${height}px`;
        const ctx = canvas.getContext("2d");
        if (ctx) ctx.scale(dpr, dpr);
        draw();
      }
    });
    observer.observe(container);
    return () => observer.disconnect();
  }, [draw]);

  // Hit-test on mouse move to find nearest sector dot
  const handleMouseMove = useCallback((e: MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const W = canvas.getBoundingClientRect().width;
    const H = canvas.getBoundingClientRect().height;
    const PAD = 32;

    let closestSym: string | null = null;
    let minDist = Infinity;

    data.sectors.forEach((sector) => {
      if (sector.tail.length === 0) return;
      const last = sector.tail[sector.tail.length - 1];
      const lx = toCanvasX(last.rs_ratio, W, PAD);
      const ly = toCanvasY(last.rs_momentum, H, PAD);
      const dist = Math.hypot(mx - lx, my - ly);
      if (dist < minDist) {
        minDist = dist;
        closestSym = sector.symbol;
      }
    });

    if (minDist < 20) {
      setHoveredSector(closestSym);
      setTooltipPos({ x: e.clientX, y: e.clientY });
    } else {
      setHoveredSector(null);
    }
  }, [data.sectors, toCanvasX, toCanvasY]);

  const hoveredData: SectorRRG | undefined = hoveredSector
    ? data.sectors.find((s) => s.symbol === hoveredSector)
    : undefined;

  return (
    <div ref={containerRef} className="relative w-full h-full">
      <canvas
        ref={canvasRef}
        className="block w-full h-full cursor-crosshair"
        onMouseMove={handleMouseMove}
        onMouseLeave={() => setHoveredSector(null)}
      />

      {/* Sample data indicator */}
      {data.is_sample_data && (
        <div className="absolute top-1 right-1 text-xxs text-text-disabled bg-surface-card/80 px-1 py-0.5 rounded border border-border-default">
          sample data
        </div>
      )}

      {/* Hover tooltip */}
      {hoveredData && (
        <div
          className="fixed z-50 pointer-events-none rounded border border-border-default bg-surface-card text-xs shadow-lg min-w-40"
          style={{ left: tooltipPos.x + 12, top: tooltipPos.y - 8 }}
        >
          <div className="flex items-center justify-between px-2 py-1 border-b border-border-default gap-3">
            <span className="font-mono font-bold text-text-primary">{hoveredData.name}</span>
            <span
              className="font-bold text-xs uppercase"
              style={{ color: RRG_QUADRANT_COLOURS[hoveredData.current_quadrant].dot }}
            >
              {RRG_QUADRANT_COLOURS[hoveredData.current_quadrant].label}
            </span>
          </div>
          {hoveredData.tail.length > 0 && (() => {
            const last = hoveredData.tail[hoveredData.tail.length - 1];
            return (
              <div className="px-2 py-1 space-y-0.5">
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">RS-Ratio</span>
                  <span className="font-mono tabular-nums text-text-primary">{last.rs_ratio.toFixed(2)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">RS-Momentum</span>
                  <span className="font-mono tabular-nums text-text-primary">{last.rs_momentum.toFixed(2)}</span>
                </div>
                <div className="flex justify-between gap-4">
                  <span className="text-text-muted">Date</span>
                  <span className="font-mono text-text-secondary">{last.date}</span>
                </div>
              </div>
            );
          })()}
        </div>
      )}

      {/* Tail length label */}
      <div className="absolute bottom-1 left-1 text-xxs text-text-disabled">
        tail: {tailLength}w · benchmark: {data.benchmark}
      </div>
    </div>
  );
});

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
type ActiveMode = "treemap" | "grid" | "sector" | "rrg";
type SizingMode = "equal" | "value";

interface StockData {
  symbol: string;
  ltp: number;
  change: number;
  sector: string;
}

interface SectorItem {
  sector: string;
  stockCount: number;
  avgChange: number;
  stocks: StockData[];
}

interface TreemapSectorLayout extends SectorItem {
  x: number;
  y: number;
  width: number;
  height: number;
  value: number;
  stockLayout: Array<StockData & TreemapLayoutItem>;
}

interface ContainerSize {
  width: number;
  height: number;
}

// ---------------------------------------------------------------------------
// Jotai atom for sector data (allows cross-widget sharing later)
// ---------------------------------------------------------------------------
export const sectorDataAtom = atom<StockData[]>([]);

// ---------------------------------------------------------------------------
// Widget
// ---------------------------------------------------------------------------
const HEATMAP_MODES: { id: ActiveMode; label: string; icon: typeof LayoutGrid }[] = [
  { id: "treemap", label: "Treemap", icon: LayoutGrid },
  { id: "grid", label: "Grid", icon: Grid3X3 },
  { id: "sector", label: "Sectors", icon: BarChart3 },
  { id: "rrg", label: "RRG", icon: TrendingUp },
];

function SectorMapWidget(_props: WidgetProps) {
  const [activeMode, setActiveMode] = useState<ActiveMode>("treemap");
  const [sizingMode, setSizingMode] = useState<SizingMode>("equal");
  const rrgData = useRRGData(8);
  const [selectedSector, setSelectedSector] = useState<string | null>(null);
  const [hoveredStock, setHoveredStock] = useState<StockData | null>(null);
  const [tooltipPos, setTooltipPos] = useState({ x: 0, y: 0 });
  const [containerSize, setContainerSize] = useState<ContainerSize>({ width: 0, height: 0 });
  const resizeObserverRef = useRef<ResizeObserver | null>(null);
  const [, setSectorData] = useAtom(sectorDataAtom);

  // Pull positions as the data source — real symbols from live portfolio
  const { data: positionsData } = usePositions();

  // Memoized callback ref for treemap container (absorbed from source)
  const setTreemapRef = useCallback((node: HTMLDivElement | null): void => {
    if (resizeObserverRef.current) {
      resizeObserverRef.current.disconnect();
      resizeObserverRef.current = null;
    }
    if (node) {
      const rect = node.getBoundingClientRect();
      setContainerSize({ width: rect.width, height: rect.height });
      resizeObserverRef.current = new ResizeObserver((entries) => {
        for (const entry of entries) {
          setContainerSize({
            width: entry.contentRect.width,
            height: entry.contentRect.height,
          });
        }
      });
      resizeObserverRef.current.observe(node);
    }
  }, []);

  useEffect(() => {
    return () => {
      if (resizeObserverRef.current) resizeObserverRef.current.disconnect();
    };
  }, []);

  // Build stock data from positions
  const stockData = useMemo<StockData[]>(() => {
    if (!positionsData || positionsData.length === 0) {
      // Demo data when no positions (makes widget useful out-of-session)
      return [
        { symbol: "RELIANCE", ltp: 2890, change: 1.2, sector: "Energy" },
        { symbol: "TCS", ltp: 3950, change: -0.4, sector: "IT" },
        { symbol: "INFY", ltp: 1730, change: 0.8, sector: "IT" },
        { symbol: "HDFCBANK", ltp: 1680, change: -1.1, sector: "Banking" },
        { symbol: "ICICIBANK", ltp: 1290, change: 2.3, sector: "Banking" },
        { symbol: "SBIN", ltp: 820, change: -0.6, sector: "Banking" },
        { symbol: "HINDUNILVR", ltp: 2430, change: 0.3, sector: "FMCG" },
        { symbol: "ITC", ltp: 470, change: 1.8, sector: "FMCG" },
        { symbol: "MARUTI", ltp: 12500, change: -2.1, sector: "Auto" },
        { symbol: "TATAMOTORS", ltp: 890, change: 3.4, sector: "Auto" },
        { symbol: "SUNPHARMA", ltp: 1650, change: -0.9, sector: "Pharma" },
        { symbol: "LT", ltp: 3700, change: 0.5, sector: "Infra" },
        { symbol: "BAJFINANCE", ltp: 6800, change: -1.7, sector: "NBFC" },
        { symbol: "TITAN", ltp: 3500, change: 1.1, sector: "Consumer" },
        { symbol: "WIPRO", ltp: 470, change: -0.2, sector: "IT" },
        { symbol: "KOTAKBANK", ltp: 1820, change: 0.7, sector: "Banking" },
      ];
    }

    return (positionsData as Position[]).map((p) => {
      const ltp = p.ltp ?? 0;
      const avgPrice = p.averagePrice ?? 0;
      const change = avgPrice > 0 ? ((ltp - avgPrice) / avgPrice) * 100 : 0;
      return {
        symbol: p.symbol,
        ltp,
        change,
        sector: getSector(p.symbol),
      };
    });
  }, [positionsData]);

  // Sync atom
  useEffect(() => {
    setSectorData(stockData);
  }, [stockData, setSectorData]);

  const filteredStockData = useMemo<StockData[]>(() => {
    if (!selectedSector) return stockData;
    return stockData.filter((s) => s.sector === selectedSector);
  }, [stockData, selectedSector]);

  // Sector aggregation (absorbed from SectorHeatmapModal)
  const sectorData = useMemo<SectorItem[]>(() => {
    const groups: Record<string, { stocks: StockData[]; totalChange: number }> = {};
    filteredStockData.forEach((item) => {
      if (!groups[item.sector]) groups[item.sector] = { stocks: [], totalChange: 0 };
      groups[item.sector].stocks.push(item);
      groups[item.sector].totalChange += item.change;
    });
    return Object.entries(groups)
      .map(([sector, g]) => ({
        sector,
        stockCount: g.stocks.length,
        avgChange: g.stocks.length > 0 ? g.totalChange / g.stocks.length : 0,
        stocks: g.stocks,
      }))
      .filter((s) => s.stockCount > 0)
      .sort((a, b) => b.stockCount - a.stockCount);
  }, [filteredStockData]);

  // Market stats
  const stats = useMemo(() => {
    const gainers = filteredStockData.filter((s) => s.change > 0.1).length;
    const losers = filteredStockData.filter((s) => s.change < -0.1).length;
    const avgChange =
      filteredStockData.length > 0
        ? filteredStockData.reduce((sum, s) => sum + s.change, 0) / filteredStockData.length
        : 0;
    return { gainers, losers, avgChange };
  }, [filteredStockData]);

  // Treemap layout (absorbed from SectorHeatmapModal treemapLayout logic)
  const treemapLayout = useMemo<TreemapSectorLayout[]>(() => {
    if (containerSize.width === 0 || containerSize.height === 0) return [];
    const sectorItems = sectorData
      .map((s) => ({ ...s, value: sizingMode === "equal" ? s.stocks.length : s.stockCount * 100 }))
      .sort((a, b) => b.value - a.value);

    const sectorLayout = calculateTreemapLayout(
      sectorItems,
      0, 0,
      containerSize.width,
      containerSize.height,
    ) as Array<SectorItem & TreemapLayoutItem>;

    return sectorLayout.map((sector) => {
      const stockItems = sector.stocks.map((stock) => ({ ...stock, value: 1 }));
      const padding = selectedSector ? 0 : 1;
      const headerHeight = selectedSector ? 0 : 18;
      const stockLayout = calculateTreemapLayout(
        stockItems,
        padding,
        headerHeight,
        Math.max(sector.width - padding * 2, 0),
        Math.max(sector.height - headerHeight - padding, 0),
      ) as Array<StockData & TreemapLayoutItem>;
      return { ...sector, stockLayout };
    });
  }, [sectorData, containerSize, selectedSector, sizingMode]);

  // Handlers
  const handleSectorClick = (sector: string) => {
    setSelectedSector(sector);
    setActiveMode("treemap");
  };

  const handleStockMouseEnter = (stock: StockData, e: MouseEvent<HTMLDivElement>) => {
    setHoveredStock(stock);
    setTooltipPos({ x: e.clientX, y: e.clientY });
  };

  const handleStockMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    setTooltipPos({ x: e.clientX, y: e.clientY });
  };

  // ---------------------------------------------------------------------------
  // Render modes
  // ---------------------------------------------------------------------------
  const renderTreemap = () => (
    <div className="relative w-full h-full" ref={setTreemapRef}>
      {treemapLayout.map((sector) => (
        <div
          key={sector.sector}
          className="absolute"
          style={{
            left: sector.x,
            top: sector.y,
            width: sector.width,
            height: sector.height,
            backgroundColor: "rgba(0,0,0,0.15)",
            border: selectedSector ? "none" : "1px solid rgba(255,255,255,0.05)",
          }}
          onClick={() => !selectedSector && handleSectorClick(sector.sector)}
          role={!selectedSector ? "button" : "presentation"}
          title={!selectedSector ? "Click to zoom into sector" : ""}
        >
          {!selectedSector && sector.width > 35 && (
            <div
              className="flex items-center justify-between px-1 overflow-hidden"
              style={{
                height: 18,
                fontSize: Math.max(Math.min(sector.width / 10, 9), 7),
                borderBottom: `1px solid ${getChangeColor(sector.avgChange)}30`,
              }}
            >
              <span className="font-bold uppercase tracking-wide text-text-primary truncate">
                {sector.sector}
              </span>
              {sector.width > 80 && (
                <span
                  className="font-bold shrink-0 ml-1"
                  style={{ color: getChangeColor(sector.avgChange), fontSize: 8 }}
                >
                  {sector.avgChange >= 0 ? "+" : ""}{sector.avgChange.toFixed(2)}%
                </span>
              )}
            </div>
          )}

          {sector.stockLayout.map((stock) => {
            const showContent = stock.width > 28 && stock.height > 24;
            const showPrice = stock.height > 72 && stock.width > 72;
            return (
              <div
                key={stock.symbol}
                className="absolute flex flex-col items-center justify-center overflow-hidden cursor-pointer"
                style={{
                  left: stock.x,
                  top: stock.y,
                  width: stock.width,
                  height: stock.height,
                  backgroundColor: getChangeColor(stock.change),
                  border: "1px solid rgba(0,0,0,0.1)",
                }}
                onClick={(e) => e.stopPropagation()}
                onMouseEnter={(e) => handleStockMouseEnter(stock, e)}
                onMouseMove={handleStockMouseMove}
                onMouseLeave={() => setHoveredStock(null)}
              >
                {showContent && (
                  <div className="text-center w-full px-0.5">
                    <span
                      className="block font-bold text-text-primary truncate leading-tight"
                      style={{ fontSize: Math.min(stock.width / 5, 12) }}
                    >
                      {stock.symbol}
                    </span>
                    <span
                      className="block font-semibold text-text-primary/90"
                      style={{ fontSize: Math.min(stock.width / 6, 10) }}
                    >
                      {stock.change >= 0 ? "+" : ""}{stock.change.toFixed(2)}%
                    </span>
                    {showPrice && (
                      <span className="block text-text-secondary" style={{ fontSize: 9 }}>
                        {"\u20B9"}{formatPrice(stock.ltp)}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ))}

      {/* Tooltip (absorbed from SectorHeatmapModal) */}
      {hoveredStock && (
        <div
          className="fixed z-50 pointer-events-none rounded border border-border-default bg-surface-card text-xs shadow-lg"
          style={{
            left: tooltipPos.x,
            top: tooltipPos.y + 16,
            transform: "translateX(-50%)",
            minWidth: 140,
          }}
        >
          <div className="flex items-center justify-between px-2 py-1 border-b border-border-default">
            <span className="font-mono font-bold text-text-primary">{hoveredStock.symbol}</span>
            <span
              className="font-mono font-bold ml-2"
              style={{ color: getChangeColor(hoveredStock.change) }}
            >
              {hoveredStock.change >= 0 ? "+" : ""}{hoveredStock.change.toFixed(2)}%
            </span>
          </div>
          <div className="px-2 py-1 space-y-0.5 text-xs">
            <div className="flex justify-between gap-4">
              <span className="text-text-muted">LTP</span>
              <span className="font-mono text-text-primary">{"\u20B9"}{formatPrice(hoveredStock.ltp)}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-text-muted">Sector</span>
              <span className="text-text-primary">{hoveredStock.sector}</span>
            </div>
          </div>
        </div>
      )}
    </div>
  );

  const renderGrid = () => {
    const sorted = [...filteredStockData].sort((a, b) => b.change - a.change);
    return (
      <div className="grid gap-1 p-1 overflow-auto h-full" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(80px, 1fr))" }}>
        {sorted.map((stock) => (
          <div
            key={stock.symbol}
            className="flex flex-col items-center justify-center rounded p-1 cursor-pointer min-h-15"
            style={{ backgroundColor: getChangeColor(stock.change) }}
          >
            <span className="font-mono font-bold text-text-primary text-xs text-center leading-tight truncate w-full">
              {stock.symbol}
            </span>
            <span className="font-semibold text-text-primary/90 text-xs">
              {stock.change >= 0 ? "+" : ""}{stock.change.toFixed(2)}%
            </span>
            <span className="text-text-secondary text-xxs font-mono tabular-nums">{"\u20B9"}{formatPrice(stock.ltp)}</span>
          </div>
        ))}
      </div>
    );
  };

  const renderSectorTable = () => {
    const maxChange = Math.max(...sectorData.map((s) => Math.abs(s.avgChange)), 1);
    return (
      <div className="overflow-auto h-full">
        <table className="w-full text-xs">
          <thead className="sticky top-0 bg-surface-card">
            <tr>
              <th className="text-left px-2 py-1 text-text-muted font-medium text-xxs uppercase tracking-wider">Sector</th>
              <th className="text-right px-2 py-1 text-text-muted font-medium text-xxs uppercase tracking-wider">Stocks</th>
              <th className="text-right px-2 py-1 text-text-muted font-medium text-xxs uppercase tracking-wider">Avg Chg</th>
              <th className="px-2 py-1 text-text-muted font-medium text-xxs uppercase tracking-wider">Bar</th>
            </tr>
          </thead>
          <tbody>
            {sectorData.map((item) => (
              <tr
                key={item.sector}
                className="border-t border-border-default hover:bg-surface-hover cursor-pointer"
                onClick={() => handleSectorClick(item.sector)}
              >
                <td className="px-2 py-1">
                  <div className="flex items-center gap-1.5">
                    <div
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: getChangeColor(item.avgChange) }}
                    />
                    <span className="text-text-primary">{item.sector}</span>
                  </div>
                </td>
                <td className="px-2 py-1 text-right font-mono tabular-nums text-text-secondary">{item.stockCount}</td>
                <td
                  className="px-2 py-1 text-right font-mono font-medium"
                  style={{ color: getChangeColor(item.avgChange) }}
                >
                  {item.avgChange >= 0 ? "+" : ""}{item.avgChange.toFixed(2)}%
                </td>
                <td className="px-2 py-1">
                  <div className="h-1.5 rounded-full bg-surface-hover overflow-hidden w-full">
                    <div
                      className="h-full rounded-full transition-[width]"
                      style={{
                        width: `${getBarWidth(item.avgChange, maxChange)}%`,
                        backgroundColor: getChangeColor(item.avgChange),
                      }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderEmpty = () => (
    <div className="flex flex-col items-center justify-center h-full text-text-muted gap-2">
      <Grid3X3 size={36} strokeWidth={1} className="text-text-disabled" />
      <p className="text-sm text-text-muted">No stock data available</p>
    </div>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-surface-base">
      {/* Header toolbar */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-border-default shrink-0 gap-2">
        <div className="flex items-center gap-2">
          {selectedSector && (
            <button
              className="text-text-muted hover:text-text-primary transition-colors"
              onClick={() => setSelectedSector(null)}
              title="Back to all sectors"
            >
              <LayoutGrid size={13} />
            </button>
          )}
          <span className="font-heading font-semibold text-sm text-text-secondary uppercase tracking-wider">
            {selectedSector ? selectedSector : "Sector Map"}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {/* Stats badges */}
          <Badge variant="outline" className="text-xs px-1 py-0 border-profit/30 text-profit gap-0.5">
            <TrendingUp size={9} />
            {stats.gainers}
          </Badge>
          <Badge variant="outline" className="text-xs px-1 py-0 border-loss/30 text-loss gap-0.5">
            <TrendingDown size={9} />
            {stats.losers}
          </Badge>
          <span
            className="font-mono text-xs font-semibold"
            style={{ color: getChangeColor(stats.avgChange) }}
          >
            {stats.avgChange >= 0 ? "+" : ""}{stats.avgChange.toFixed(2)}%
          </span>

          {/* Sizing mode (treemap only) */}
          {activeMode === "treemap" && (
            <Select
              value={sizingMode}
              onValueChange={(v) => setSizingMode(v as SizingMode)}
            >
              <SelectTrigger className="h-7 text-xs px-1.5 border-border-default bg-surface-card text-text-secondary w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-surface-card border-border-default text-xs">
                <SelectItem value="equal">Equal</SelectItem>
                <SelectItem value="value">Value</SelectItem>
              </SelectContent>
            </Select>
          )}

          {/* Mode tabs */}
          <div className="flex items-center border border-border-default rounded overflow-hidden">
            {HEATMAP_MODES.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                title={label}
                className={`flex items-center justify-center w-6 h-7 transition-colors ${
                  activeMode === id
                    ? "bg-surface-elevated text-text-primary"
                    : "text-text-muted hover:text-text-secondary"
                }`}
                onClick={() => setActiveMode(id)}
              >
                <Icon size={11} />
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden relative">
        {activeMode === "rrg"
          ? rrgData.data ? <RRGCanvas data={rrgData.data} tailLength={8} /> : renderEmpty()
          : filteredStockData.length === 0
          ? renderEmpty()
          : activeMode === "treemap"
          ? renderTreemap()
          : activeMode === "grid"
          ? renderGrid()
          : renderSectorTable()}
      </div>

      {/* Legend footer */}
      <div className="flex items-center justify-between px-2 py-0.5 border-t border-border-default shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <div className="h-1.5 w-6 rounded" style={{ background: "linear-gradient(to right,#8B3030,#3D8B80,#00C853)" }} />
            <span className="text-xxs text-text-disabled">-4% → +4%</span>
          </div>
        </div>
        <span className="text-xxs text-text-disabled">
          {activeMode === "rrg" ? "RS-Ratio (x) vs RS-Momentum (y) · 100 = neutral" : activeMode === "treemap" ? "Tile = equal weight · Color = change %" : "Color = change %"}
        </span>
      </div>
    </div>
  );
}

export default memo(SectorMapWidget);
