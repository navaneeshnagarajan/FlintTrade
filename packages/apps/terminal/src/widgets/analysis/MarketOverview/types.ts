/**
 * MarketOverviewWidget — shared types.
 *
 * The treemap/grid/table types are carried over from the retired SectorMap
 * widget unchanged so the squarified layout keeps its stable output API.
 */

/** Top-level tabs of the Market Overview widget. */
export type MarketOverviewTab =
  | "breadth"
  | "sectors"
  | "rotation"
  | "flows"
  | "indices"
  | "contribution";

/** Views inside the Sectors tab. */
export type SectorView = "treemap" | "grid" | "table" | "bars";

/** Views inside the Rotation tab. */
export type RotationView = "sectors" | "portfolio";

/** Treemap sizing behaviour (carried from SectorMap). */
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

/** One row of the per-index breadth split (ported from Market Intelligence). */
export interface IndexBreadthRow {
  label: string;
  advances: number;
  declines: number;
  unchanged: number;
  total: number;
  newHighs: number;
  newLows: number;
}

/** One row of the FII/DII cash-segment table. */
export interface FiiDiiCashRow {
  date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
}
