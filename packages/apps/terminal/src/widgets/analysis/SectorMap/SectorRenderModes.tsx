/**
 * SectorRenderModes — treemap, grid, and sector-table render modes for SectorMapWidget.
 */

import type { MouseEvent } from "react";
import { Grid3X3 } from "lucide-react";
import { divergingColourScale } from "@/lib/colourScale";
import type { StockData, SectorItem, TreemapSectorLayout } from "./types";

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const getChangeColor = divergingColourScale;

export function formatPrice(price: number): string {
  if (price >= 1_000) return price.toFixed(0);
  if (price >= 100) return price.toFixed(1);
  return price.toFixed(2);
}

export function getBarWidth(change: number, maxChange: number): number {
  return Math.min((Math.abs(change) / Math.max(maxChange, 1)) * 100, 100);
}

// ---------------------------------------------------------------------------
// TreemapView
// ---------------------------------------------------------------------------

interface TreemapViewProps {
  treemapLayout: TreemapSectorLayout[];
  selectedSector: string | null;
  hoveredStock: StockData | null;
  tooltipPos: { x: number; y: number };
  setHoveredStock: (stock: StockData | null) => void;
  setTooltipPos: (pos: { x: number; y: number }) => void;
  onSectorClick: (sector: string) => void;
  containerRef: (node: HTMLDivElement | null) => void;
}

export function TreemapView({
  treemapLayout,
  selectedSector,
  hoveredStock,
  tooltipPos,
  setHoveredStock,
  setTooltipPos,
  onSectorClick,
  containerRef,
}: TreemapViewProps) {
  const handleStockMouseEnter = (stock: StockData, e: MouseEvent<HTMLDivElement>) => {
    setHoveredStock(stock);
    setTooltipPos({ x: e.clientX, y: e.clientY });
  };

  const handleStockMouseMove = (e: MouseEvent<HTMLDivElement>) => {
    setTooltipPos({ x: e.clientX, y: e.clientY });
  };

  return (
    <div className="relative w-full h-full" ref={containerRef}>
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
          onClick={() => !selectedSector && onSectorClick(sector.sector)}
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

      {/* Tooltip */}
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
}

// ---------------------------------------------------------------------------
// GridView
// ---------------------------------------------------------------------------

interface GridViewProps {
  stocks: StockData[];
}

export function GridView({ stocks }: GridViewProps) {
  const sorted = [...stocks].sort((a, b) => b.change - a.change);
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
}

// ---------------------------------------------------------------------------
// SectorTableView
// ---------------------------------------------------------------------------

interface SectorTableViewProps {
  sectors: SectorItem[];
  onSectorClick: (sector: string) => void;
}

export function SectorTableView({ sectors, onSectorClick }: SectorTableViewProps) {
  const maxChange = Math.max(...sectors.map((s) => Math.abs(s.avgChange)), 1);
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
          {sectors.map((item) => (
            <tr
              key={item.sector}
              className="border-t border-border-default hover:bg-surface-hover cursor-pointer"
              onClick={() => onSectorClick(item.sector)}
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
}

// ---------------------------------------------------------------------------
// EmptyView
// ---------------------------------------------------------------------------

export function EmptyView() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-text-muted gap-2">
      <Grid3X3 size={36} strokeWidth={1} className="text-text-disabled" />
      <p className="text-sm text-text-muted">No stock data available</p>
    </div>
  );
}
