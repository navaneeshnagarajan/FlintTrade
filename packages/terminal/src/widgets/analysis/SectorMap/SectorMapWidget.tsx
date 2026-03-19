/**
 * SectorMapWidget
 *
 * Absorbed from: openalgo-chart/src/components/SectorHeatmap/SectorHeatmapModal.tsx
 * Treemap algorithm: openalgo-chart/src/components/SectorHeatmap/utils/treemapLayout.ts
 * Color helpers:    openalgo-chart/src/components/SectorHeatmap/utils/heatmapHelpers.ts
 * Constants:        openalgo-chart/src/components/SectorHeatmap/constants/heatmapConstants.ts
 *
 * Adaptations for FlintTrade:
 * - CSS Modules → Tailwind CSS v4
 * - Modal shell removed; rendered inline as a dockview widget
 * - External market data services → placeholder (no live sector API in OpenAlgo)
 * - shadcn Select for view mode, shadcn Badge for stats
 * - Jotai atom for sector data cache
 * - Positions feed from usePositions() for real holding symbols
 */

import { useMemo, useState, useRef, useCallback, useEffect } from "react";
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
import type { WidgetProps } from "@/types/widgets";

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
// Color helpers (absorbed from heatmapHelpers.ts)
// ---------------------------------------------------------------------------
function getChangeColor(change: number): string {
  const abs = Math.abs(change);
  if (change >= 0) {
    if (abs > 4) return "#00C853";
    if (abs > 3) return "#00B248";
    if (abs > 2) return "#00A63E";
    if (abs > 1.5) return "#009A38";
    if (abs > 1) return "#00897B";
    if (abs > 0.5) return "#0D9668";
    if (abs > 0.2) return "#26A69A";
    return "#3D8B80";
  } else {
    if (abs > 4) return "#FF1744";
    if (abs > 3) return "#F5153D";
    if (abs > 2) return "#E91235";
    if (abs > 1.5) return "#D8102F";
    if (abs > 1) return "#C62828";
    if (abs > 0.5) return "#B71C1C";
    if (abs > 0.2) return "#A52727";
    return "#8B3030";
  }
}

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
// Types
// ---------------------------------------------------------------------------
type ActiveMode = "treemap" | "grid" | "sector";
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
];

export default function SectorMapWidget(_props: WidgetProps) {
  const [activeMode, setActiveMode] = useState<ActiveMode>("treemap");
  const [sizingMode, setSizingMode] = useState<SizingMode>("equal");
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

    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    return (positionsData as any[]).map((p) => {
      const ltp = parseFloat(String(p.ltp ?? 0));
      const avgPrice = parseFloat(String(p.averagePrice ?? p.average_price ?? 0));
      const change = avgPrice > 0 ? ((ltp - avgPrice) / avgPrice) * 100 : 0;
      return {
        symbol: String(p.symbol),
        ltp,
        change,
        sector: getSector(String(p.symbol)),
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
              <span className="font-bold uppercase tracking-wide text-white/80 truncate">
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
                      className="block font-bold text-white truncate leading-tight"
                      style={{ fontSize: Math.min(stock.width / 5, 12) }}
                    >
                      {stock.symbol}
                    </span>
                    <span
                      className="block font-semibold text-white/90"
                      style={{ fontSize: Math.min(stock.width / 6, 10) }}
                    >
                      {stock.change >= 0 ? "+" : ""}{stock.change.toFixed(2)}%
                    </span>
                    {showPrice && (
                      <span className="block text-white/70" style={{ fontSize: 9 }}>
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
          className="fixed z-50 pointer-events-none rounded border border-[#1e1e2e] bg-[#12121a] text-xs shadow-lg"
          style={{
            left: tooltipPos.x,
            top: tooltipPos.y + 16,
            transform: "translateX(-50%)",
            minWidth: 140,
          }}
        >
          <div className="flex items-center justify-between px-2 py-1 border-b border-[#1e1e2e]">
            <span className="font-mono font-bold text-white">{hoveredStock.symbol}</span>
            <span
              className="font-mono font-bold ml-2"
              style={{ color: getChangeColor(hoveredStock.change) }}
            >
              {hoveredStock.change >= 0 ? "+" : ""}{hoveredStock.change.toFixed(2)}%
            </span>
          </div>
          <div className="px-2 py-1 space-y-0.5 text-[11px]">
            <div className="flex justify-between gap-4">
              <span className="text-white/50">LTP</span>
              <span className="font-mono text-white">{"\u20B9"}{formatPrice(hoveredStock.ltp)}</span>
            </div>
            <div className="flex justify-between gap-4">
              <span className="text-white/50">Sector</span>
              <span className="text-white">{hoveredStock.sector}</span>
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
            className="flex flex-col items-center justify-center rounded p-1 cursor-pointer min-h-[60px]"
            style={{ backgroundColor: getChangeColor(stock.change) }}
          >
            <span className="font-mono font-bold text-white text-[11px] text-center leading-tight truncate w-full">
              {stock.symbol}
            </span>
            <span className="font-semibold text-white/90 text-[10px]">
              {stock.change >= 0 ? "+" : ""}{stock.change.toFixed(2)}%
            </span>
            <span className="text-white/70 text-[9px] font-mono">{"\u20B9"}{formatPrice(stock.ltp)}</span>
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
          <thead className="sticky top-0 bg-[#12121a]">
            <tr>
              <th className="text-left px-2 py-1 text-white/40 font-medium uppercase tracking-wider">Sector</th>
              <th className="text-right px-2 py-1 text-white/40 font-medium uppercase tracking-wider">Stocks</th>
              <th className="text-right px-2 py-1 text-white/40 font-medium uppercase tracking-wider">Avg Chg</th>
              <th className="px-2 py-1 text-white/40 font-medium uppercase tracking-wider">Bar</th>
            </tr>
          </thead>
          <tbody>
            {sectorData.map((item) => (
              <tr
                key={item.sector}
                className="border-t border-[#1e1e2e] hover:bg-white/5 cursor-pointer"
                onClick={() => handleSectorClick(item.sector)}
              >
                <td className="px-2 py-1">
                  <div className="flex items-center gap-1.5">
                    <div
                      className="w-2 h-2 rounded-full shrink-0"
                      style={{ backgroundColor: getChangeColor(item.avgChange) }}
                    />
                    <span className="text-white/80">{item.sector}</span>
                  </div>
                </td>
                <td className="px-2 py-1 text-right font-mono text-white/60">{item.stockCount}</td>
                <td
                  className="px-2 py-1 text-right font-mono font-medium"
                  style={{ color: getChangeColor(item.avgChange) }}
                >
                  {item.avgChange >= 0 ? "+" : ""}{item.avgChange.toFixed(2)}%
                </td>
                <td className="px-2 py-1">
                  <div className="h-1.5 rounded-full bg-white/10 overflow-hidden w-full">
                    <div
                      className="h-full rounded-full transition-all"
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
    <div className="flex flex-col items-center justify-center h-full text-white/30 gap-2">
      <Grid3X3 size={36} strokeWidth={1} />
      <p className="text-sm">No stock data available</p>
    </div>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden text-xs bg-[#0a0a0f]">
      {/* Header toolbar */}
      <div className="flex items-center justify-between px-2 py-1 border-b border-[#1e1e2e] shrink-0 gap-2">
        <div className="flex items-center gap-2">
          {selectedSector && (
            <button
              className="text-white/50 hover:text-white transition-colors"
              onClick={() => setSelectedSector(null)}
              title="Back to all sectors"
            >
              <LayoutGrid size={13} />
            </button>
          )}
          <span className="text-white/60 uppercase tracking-wider text-[10px]">
            {selectedSector ? selectedSector : "Sector Map"}
          </span>
        </div>

        <div className="flex items-center gap-1.5">
          {/* Stats badges */}
          <Badge variant="outline" className="text-[10px] px-1 py-0 border-green-800 text-green-400 gap-0.5">
            <TrendingUp size={9} />
            {stats.gainers}
          </Badge>
          <Badge variant="outline" className="text-[10px] px-1 py-0 border-red-900 text-red-400 gap-0.5">
            <TrendingDown size={9} />
            {stats.losers}
          </Badge>
          <span
            className="font-mono text-[10px] font-semibold"
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
              <SelectTrigger className="h-5 text-[10px] px-1.5 border-[#1e1e2e] bg-[#12121a] text-white/60 w-16">
                <SelectValue />
              </SelectTrigger>
              <SelectContent className="bg-[#12121a] border-[#1e1e2e] text-xs">
                <SelectItem value="equal">Equal</SelectItem>
                <SelectItem value="value">Value</SelectItem>
              </SelectContent>
            </Select>
          )}

          {/* Mode tabs */}
          <div className="flex items-center border border-[#1e1e2e] rounded overflow-hidden">
            {HEATMAP_MODES.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                title={label}
                className={`flex items-center justify-center w-6 h-5 transition-colors ${
                  activeMode === id
                    ? "bg-[#1e1e2e] text-white"
                    : "text-white/40 hover:text-white/70"
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
        {filteredStockData.length === 0
          ? renderEmpty()
          : activeMode === "treemap"
          ? renderTreemap()
          : activeMode === "grid"
          ? renderGrid()
          : renderSectorTable()}
      </div>

      {/* Legend footer */}
      <div className="flex items-center justify-between px-2 py-0.5 border-t border-[#1e1e2e] shrink-0">
        <div className="flex items-center gap-2">
          <div className="flex items-center gap-1">
            <div className="h-1.5 w-6 rounded" style={{ background: "linear-gradient(to right,#8B3030,#3D8B80,#00C853)" }} />
            <span className="text-[9px] text-white/30">-4% → +4%</span>
          </div>
        </div>
        <span className="text-[9px] text-white/20">
          {activeMode === "treemap" ? "Tile = equal weight · Color = change %" : "Color = change %"}
        </span>
      </div>
    </div>
  );
}
