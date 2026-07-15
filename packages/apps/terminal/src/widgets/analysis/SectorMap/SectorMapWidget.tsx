/**
 * SectorMapWidget
 *
 * Adapted from: openalgo-chart/src/components/SectorHeatmap/SectorHeatmapModal.tsx
 * Treemap algorithm: FlintTrade's own squarified implementation (see ./treemapLayout.ts)
 * Color helpers:    openalgo-chart/src/components/SectorHeatmap/utils/heatmapHelpers.ts
 * Constants:        openalgo-chart/src/components/SectorHeatmap/constants/heatmapConstants.ts
 * RRG view:         adapted from sector-rotation-map reference repo
 *
 * Adaptations for FlintTrade:
 * - CSS Modules → Tailwind CSS v4
 * - Modal shell removed; rendered inline as a dockview widget
 * - External market data services → placeholder (no live sector API in OpenAlgo)
 * - shadcn Select for view mode, shadcn Badge for stats
 * - Jotai atom for sector data cache
 * - Positions feed from usePositions() for real holding symbols
 * - RRG canvas view added as third mode (useRRGData hook → ftApi → screener/rrg.py)
 *
 * Modules:
 *   types.ts              — shared types
 *   treemapLayout.ts      — squarified treemap algorithm
 *   RRGCanvas.tsx         — canvas-based RRG scatter plot
 *   SectorRenderModes.tsx — TreemapView, GridView, SectorTableView, EmptyView
 */

import { useMemo, useState, useRef, useCallback, useEffect, memo } from "react";
import { LayoutGrid, Grid3X3, BarChart3, TrendingUp, TrendingDown, Target } from "lucide-react";
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
import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { resolveAccountReadsEnabled } from "@/hooks/useAccountReadsEnabled";
import { useRRGData } from "@/hooks/useRRGData";
import { useModeStore } from "@/stores/modeStore";
import type { Position } from "@/types/api";
import type { WidgetProps } from "@/types/widgets";
import { divergingColourScale } from "@/lib/colourScale";

import { calculateTreemapLayout } from "./treemapLayout";
import { RRGCanvas } from "./RRGCanvas";
import { PortfolioRRGTab } from "./PortfolioRRGTab";
import { TreemapView, GridView, SectorTableView, EmptyView } from "./SectorRenderModes";
import type {
  ActiveMode,
  SizingMode,
  StockData,
  SectorItem,
  TreemapSectorLayout,
  ContainerSize,
  TreemapLayoutItem,
} from "./types";

// ---------------------------------------------------------------------------
// Color helper
// ---------------------------------------------------------------------------

const getChangeColor = divergingColourScale;

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
  { id: "portfolio", label: "Portfolio", icon: Target },
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
  const mode = useModeStore((state) => state.mode);
  const isBrokerConnected = useBrokerConnected();
  const accountReadsEnabled = resolveAccountReadsEnabled(mode, isBrokerConnected);

  const { data: positionsData } = usePositions({ enabled: accountReadsEnabled });
  const isSampleSectorData = mode === "explore";

  // Memoized callback ref for treemap container (adapted from source)
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
    if (isSampleSectorData) {
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

    return ((positionsData ?? []) as Position[]).map((p) => {
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
  }, [isSampleSectorData, positionsData]);

  // Sync atom
  useEffect(() => {
    setSectorData(stockData);
  }, [stockData, setSectorData]);

  const filteredStockData = useMemo<StockData[]>(() => {
    if (!selectedSector) return stockData;
    return stockData.filter((s) => s.sector === selectedSector);
  }, [stockData, selectedSector]);

  // Sector aggregation
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

  // Treemap layout
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

  const handleSectorClick = (sector: string) => {
    setSelectedSector(sector);
    setActiveMode("treemap");
  };

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
          {isSampleSectorData && (
            <Badge
              variant="outline"
              className="text-xxs px-1.5 py-0 border-warning/30 text-warning bg-warning/10"
            >
              Sample data
            </Badge>
          )}
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
        {activeMode === "portfolio"
          ? <PortfolioRRGTab />
          : activeMode === "rrg"
          ? rrgData.data ? <RRGCanvas data={rrgData.data} tailLength={8} /> : <EmptyView />
          : filteredStockData.length === 0
          ? <EmptyView />
          : activeMode === "treemap"
          ? (
            <TreemapView
              treemapLayout={treemapLayout}
              selectedSector={selectedSector}
              hoveredStock={hoveredStock}
              tooltipPos={tooltipPos}
              setHoveredStock={setHoveredStock}
              setTooltipPos={setTooltipPos}
              onSectorClick={handleSectorClick}
              containerRef={setTreemapRef}
            />
          )
          : activeMode === "grid"
          ? <GridView stocks={filteredStockData} />
          : <SectorTableView sectors={sectorData} onSectorClick={handleSectorClick} />}
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
          {(activeMode === "rrg" || activeMode === "portfolio") ? "RS-Ratio (x) vs RS-Momentum (y) · 100 = neutral" : activeMode === "treemap" ? "Tile = equal weight · Color = change %" : "Color = change %"}
        </span>
      </div>
    </div>
  );
}

export default memo(SectorMapWidget);
