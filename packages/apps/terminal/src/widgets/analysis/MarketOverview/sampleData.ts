/**
 * Sample datasets for the Market Overview widget's non-sector surfaces.
 *
 * All values are illustrative — never real market data — and every consumer
 * badges them via a fail-closed provenance check (`is_sample_data !== false`
 * means sample). The sector table lives separately in ./sampleSectors.ts as
 * the widget's single sample sector source.
 */

import type { GlobalIndexEntry } from "@/services/ftApi";
import type { FiiLongShortRatio, IndexContribution } from "@/services/ftApi.screener";
import type { FiiDiiCashRow, IndexBreadthRow } from "./types";

// ---------------------------------------------------------------------------
// Breadth (from the retired MarketBreadth widget)
// ---------------------------------------------------------------------------

export interface BreadthPoint {
  time: string;
  advances: number;
  declines: number;
  unchanged: number;
}

export interface BreadthSnapshot {
  series: BreadthPoint[];
  newHighs: number;
  newLows: number;
  mcclellanOscillator: number;
  breadthThrust: number;
  totalAdvances: number;
  totalDeclines: number;
  totalUnchanged: number;
}

export const SAMPLE_BREADTH_SERIES: BreadthPoint[] = [
  { time: "09:30", advances: 820, declines: 430, unchanged: 50 },
  { time: "10:00", advances: 900, declines: 370, unchanged: 30 },
  { time: "10:30", advances: 780, declines: 490, unchanged: 30 },
  { time: "11:00", advances: 850, declines: 420, unchanged: 30 },
  { time: "11:30", advances: 920, declines: 350, unchanged: 30 },
  { time: "12:00", advances: 860, declines: 410, unchanged: 30 },
  { time: "12:30", advances: 790, declines: 480, unchanged: 30 },
  { time: "13:00", advances: 830, declines: 440, unchanged: 30 },
  { time: "13:30", advances: 880, declines: 390, unchanged: 30 },
  { time: "14:00", advances: 910, declines: 360, unchanged: 30 },
  { time: "14:30", advances: 870, declines: 400, unchanged: 30 },
  { time: "15:00", advances: 940, declines: 330, unchanged: 30 },
  { time: "15:30", advances: 960, declines: 310, unchanged: 30 },
];

export const SAMPLE_BREADTH: BreadthSnapshot = {
  series: SAMPLE_BREADTH_SERIES,
  newHighs: 127,
  newLows: 43,
  mcclellanOscillator: 42.7,
  breadthThrust: 0.618,
  totalAdvances: 960,
  totalDeclines: 310,
  totalUnchanged: 30,
};

/**
 * Per-index breadth split, ported from Market Intelligence's breadth tab.
 * No live per-index breadth endpoint exists, so this section is always
 * sample and carries an unconditional badge.
 */
export const SAMPLE_INDEX_BREADTH: IndexBreadthRow[] = [
  { label: "NSE 500", advances: 312, declines: 164, unchanged: 24, total: 500, newHighs: 42, newLows: 8 },
  { label: "BSE 500", advances: 298, declines: 178, unchanged: 24, total: 500, newHighs: 38, newLows: 12 },
  { label: "Nifty 50", advances: 32, declines: 17, unchanged: 1, total: 50, newHighs: 6, newLows: 2 },
];

// ---------------------------------------------------------------------------
// Top movers (from the retired MarketSummary widget)
// ---------------------------------------------------------------------------

export interface MoverEntry {
  symbol: string;
  changePct: number;
}

export const SAMPLE_GAINERS: MoverEntry[] = [
  { symbol: "INFY",        changePct: 3.42 },
  { symbol: "TCS",         changePct: 2.87 },
  { symbol: "HCLTECH",     changePct: 2.61 },
  { symbol: "WIPRO",       changePct: 2.14 },
  { symbol: "TECHM",       changePct: 1.93 },
];

export const SAMPLE_LOSERS: MoverEntry[] = [
  { symbol: "BANKBARODA",  changePct: -2.83 },
  { symbol: "UNIONBANK",   changePct: -2.41 },
  { symbol: "CANBK",       changePct: -2.19 },
  { symbol: "PNB",         changePct: -1.97 },
  { symbol: "INDUSINDBK",  changePct: -1.62 },
];

// ---------------------------------------------------------------------------
// Global indices (from the retired GlobalIndices widget)
// ---------------------------------------------------------------------------

function generateHistory(base: number, seed: number): number[] {
  return Array.from({ length: 30 }, (_, i) => {
    const noise = Math.sin((i + seed) * 0.61) * 0.008 + Math.cos((i * seed) * 0.4) * 0.005;
    return base * (1 + noise);
  });
}

export const SAMPLE_GLOBAL_INDICES: GlobalIndexEntry[] = [
  // India
  { id: "NIFTY50", name: "NIFTY 50", region: "India", ltp: 22_450.30, change: 125.60, change_pct: 0.56, history: generateHistory(22_450, 1) },
  { id: "SENSEX", name: "SENSEX", region: "India", ltp: 73_961.20, change: -210.40, change_pct: -0.28, history: generateHistory(73_961, 2) },
  // US
  { id: "SPX", name: "S&P 500", region: "US", ltp: 5_248.80, change: 32.10, change_pct: 0.62, history: generateHistory(5_248, 3) },
  { id: "NASDAQ", name: "NASDAQ", region: "US", ltp: 16_399.50, change: -45.20, change_pct: -0.28, history: generateHistory(16_399, 4) },
  { id: "DJI", name: "DOW JONES", region: "US", ltp: 39_127.14, change: 88.60, change_pct: 0.23, history: generateHistory(39_127, 5) },
  // Europe
  { id: "FTSE100", name: "FTSE 100", region: "Europe", ltp: 7_952.62, change: -18.40, change_pct: -0.23, history: generateHistory(7_952, 6) },
  { id: "DAX", name: "DAX", region: "Europe", ltp: 18_134.70, change: 54.30, change_pct: 0.30, history: generateHistory(18_134, 7) },
  // Asia
  { id: "N225", name: "Nikkei 225", region: "Asia", ltp: 38_820.60, change: -312.50, change_pct: -0.80, history: generateHistory(38_820, 8) },
  { id: "HSI", name: "Hang Seng", region: "Asia", ltp: 16_541.30, change: 120.80, change_pct: 0.74, history: generateHistory(16_541, 9) },
  { id: "SHCOMP", name: "Shanghai Comp", region: "Asia", ltp: 3_041.20, change: -9.60, change_pct: -0.31, history: generateHistory(3_041, 10) },
];

// ---------------------------------------------------------------------------
// FII long/short (from the retired FiiLongShort widget)
// ---------------------------------------------------------------------------

export const SAMPLE_FII_LONG_SHORT: FiiLongShortRatio = {
  trade_date: "04-Apr-2026",
  segments: [
    { segment: "index_futures", label: "Index Futures", long: 125000, short: 140000, net: -15000, ls_ratio: 0.8929, long_pct: 47.17 },
    { segment: "stock_futures", label: "Stock Futures", long: 80000, short: 75000, net: 5000, ls_ratio: 1.0667, long_pct: 51.61 },
    { segment: "index_calls", label: "Index Calls", long: 90000, short: 110000, net: -20000, ls_ratio: 0.8182, long_pct: 45.0 },
    { segment: "index_puts", label: "Index Puts", long: 95000, short: 85000, net: 10000, ls_ratio: 1.1176, long_pct: 52.78 },
  ],
  futures_long: 205000,
  futures_short: 215000,
  futures_bias: 48.81,
  bias_label: "Neutral",
  updated_at: "2026-04-04 18:00:00 IST",
};

// ---------------------------------------------------------------------------
// FII/DII cash segment (ported from Market Intelligence's flows tab)
// ---------------------------------------------------------------------------

export const SAMPLE_FII_DII_CASH: FiiDiiCashRow[] = [
  { date: "2024-12-27", fii_buy: 12450, fii_sell: 9820, fii_net: 2630, dii_buy: 8940, dii_sell: 7120, dii_net: 1820 },
  { date: "2024-12-26", fii_buy: 9840, fii_sell: 11250, fii_net: -1410, dii_buy: 9820, dii_sell: 7840, dii_net: 1980 },
  { date: "2024-12-24", fii_buy: 14820, fii_sell: 10490, fii_net: 4330, dii_buy: 7640, dii_sell: 8120, dii_net: -480 },
  { date: "2024-12-23", fii_buy: 8920, fii_sell: 13450, fii_net: -4530, dii_buy: 10240, dii_sell: 7840, dii_net: 2400 },
  { date: "2024-12-20", fii_buy: 11240, fii_sell: 9870, fii_net: 1370, dii_buy: 8490, dii_sell: 9120, dii_net: -630 },
  { date: "2024-12-19", fii_buy: 7840, fii_sell: 14280, fii_net: -6440, dii_buy: 11240, dii_sell: 6480, dii_net: 4760 },
  { date: "2024-12-18", fii_buy: 15640, fii_sell: 8920, fii_net: 6720, dii_buy: 7840, dii_sell: 9120, dii_net: -1280 },
];

// ---------------------------------------------------------------------------
// Index contribution (from the retired IndexContribution widget)
// ---------------------------------------------------------------------------

export const SAMPLE_INDEX_CONTRIBUTION: IndexContribution = {
  index_name: "NIFTY",
  index_level: 24000,
  index_change_pct: 0.42,
  index_change_points: 100.8,
  weights_as_of: "2026-06-30",
  advancers: 34,
  decliners: 17,
  constituents: [
    { symbol: "HDFCBANK", weight: 13.2, ltp: 1015, prev_close: 1000, change_pct: 1.5, contribution_pct: 0.198, contribution_points: 47.4 },
    { symbol: "RELIANCE", weight: 9.8, ltp: 1188, prev_close: 1200, change_pct: -1.0, contribution_pct: -0.098, contribution_points: -23.5 },
    { symbol: "ICICIBANK", weight: 8.4, ltp: 1112, prev_close: 1100, change_pct: 1.09, contribution_pct: 0.092, contribution_points: 22.0 },
    { symbol: "INFY", weight: 5.6, ltp: 1485, prev_close: 1500, change_pct: -1.0, contribution_pct: -0.056, contribution_points: -13.4 },
    { symbol: "BHARTIARTL", weight: 4.2, ltp: 1618, prev_close: 1600, change_pct: 1.13, contribution_pct: 0.047, contribution_points: 11.4 },
    { symbol: "ITC", weight: 3.8, ltp: 446, prev_close: 450, change_pct: -0.89, contribution_pct: -0.034, contribution_points: -8.1 },
    { symbol: "LT", weight: 3.6, ltp: 3636, prev_close: 3600, change_pct: 1.0, contribution_pct: 0.036, contribution_points: 8.6 },
    { symbol: "SBIN", weight: 3.2, ltp: 792, prev_close: 800, change_pct: -1.0, contribution_pct: -0.032, contribution_points: -7.7 },
  ],
};
