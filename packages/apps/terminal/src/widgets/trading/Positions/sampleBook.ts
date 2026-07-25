/**
 * The ONE labelled sample position book, used in Explore only.
 *
 * The merged widget replaces two private fixtures that described different
 * books: the heat map's ten equity/option rows and the net view's nine
 * option legs (which additionally carried a `strategy` field and lot sizes
 * that no broker boundary ever produces). One fixture means the three views
 * show the same sample book, exactly as they show the same live book.
 *
 * It is shaped like a real positionbook payload — quantities in units, one row
 * per broker row — and deliberately contains:
 *   - a symbol held in two products (NIFTY24APR22500CE MIS long, NRML short),
 *     so netting has something to net;
 *   - a scrip whose two legs net flat (RELIANCE CNC long against an MIS short),
 *     so the flat-exclusion and the "incl. n flat" total note are visible;
 *   - both profits and losses across several sectors, so the heat map's
 *     diverging colour scale and its sector grouping are exercised.
 *
 * Every surface that renders it MUST carry the Sample badge and the watermark.
 */

import type { Position } from "@/types/api";

export const SAMPLE_POSITION_BOOK: Position[] = [
  { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "MIS", quantity: 75, averagePrice: 180, ltp: 235, pnl: 4125, pnlPercent: 30.6 },
  { symbol: "NIFTY24APR22500CE", exchange: "NFO", product: "NRML", quantity: -30, averagePrice: 205, ltp: 235, pnl: -900, pnlPercent: -14.6 },
  { symbol: "BANKNIFTY24APR49000PE", exchange: "NFO", product: "MIS", quantity: -30, averagePrice: 290, ltp: 210, pnl: 2400, pnlPercent: 27.6 },
  { symbol: "INFY", exchange: "NSE", product: "CNC", quantity: 100, averagePrice: 1480, ltp: 1510, pnl: 3000, pnlPercent: 2.0 },
  { symbol: "TCS", exchange: "NSE", product: "CNC", quantity: 50, averagePrice: 3900, ltp: 3820, pnl: -4000, pnlPercent: -2.1 },
  { symbol: "HDFCBANK", exchange: "NSE", product: "MIS", quantity: 200, averagePrice: 1640, ltp: 1658, pnl: 3600, pnlPercent: 1.1 },
  { symbol: "RELIANCE", exchange: "NSE", product: "CNC", quantity: 80, averagePrice: 2950, ltp: 2870, pnl: -6400, pnlPercent: -2.7 },
  { symbol: "RELIANCE", exchange: "NSE", product: "MIS", quantity: -80, averagePrice: 2960, ltp: 2870, pnl: 7200, pnlPercent: 3.0 },
  { symbol: "SBIN", exchange: "NSE", product: "MIS", quantity: 300, averagePrice: 810, ltp: 832, pnl: 6600, pnlPercent: 2.7 },
  { symbol: "WIPRO", exchange: "NSE", product: "CNC", quantity: 150, averagePrice: 455, ltp: 448, pnl: -1050, pnlPercent: -1.5 },
  { symbol: "SUNPHARMA", exchange: "NSE", product: "CNC", quantity: 60, averagePrice: 1620, ltp: 1580, pnl: -2400, pnlPercent: -2.5 },
  { symbol: "BAJFINANCE", exchange: "NSE", product: "MIS", quantity: 40, averagePrice: 7200, ltp: 7350, pnl: 6000, pnlPercent: 2.1 },
];
