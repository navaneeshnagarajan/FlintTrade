/**
 * SectorMapWidget — shared types.
 */

export type ActiveMode = "treemap" | "grid" | "sector" | "rrg" | "portfolio";
export type SizingMode = "equal" | "value";

export interface StockData {
  symbol: string;
  ltp: number;
  change: number;
  sector: string;
}

export interface SectorItem {
  sector: string;
  stockCount: number;
  avgChange: number;
  stocks: StockData[];
}

export interface TreemapItem {
  value: number;
  [key: string]: unknown;
}

export interface TreemapLayoutItem extends TreemapItem {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface TreemapSectorLayout extends SectorItem {
  x: number;
  y: number;
  width: number;
  height: number;
  value: number;
  stockLayout: Array<StockData & TreemapLayoutItem>;
}

export interface ContainerSize {
  width: number;
  height: number;
}
