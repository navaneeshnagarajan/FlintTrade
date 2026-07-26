/**
 * Sample earnings calendar data for explore/disconnected mode.
 * Companies and dates are illustrative only — not real financial data.
 */

import { toIstIsoDate } from "@/lib/ist";

export interface EarningsEntry {
  symbol: string;
  company: string;
  date: string; // ISO date YYYY-MM-DD
  /** Only present for past dates */
  result?: "beat" | "missed" | "inline";
  estimate?: number; // EPS estimate
  actual?: number;   // Actual EPS (past only)
  sector: string;
}

/**
 * An IST calendar date, offset by whole days from today.
 *
 * Sample entries are built relative to today so the calendar always looks
 * populated. The date must be the IST trading day, matching the grid's cell
 * keys — a UTC date would drop every entry one square to the left.
 *
 * @param offset - Days from today; negative for the past.
 * @returns The ISO date ``YYYY-MM-DD`` of that IST day.
 */
function isoDate(offset: number): string {
  return toIstIsoDate(new Date(Date.now() + offset * 86_400_000));
}

export const SAMPLE_EARNINGS: EarningsEntry[] = [
  // Past — with results
  { symbol: "INFY", company: "Infosys", date: isoDate(-12), result: "beat", estimate: 18.5, actual: 19.2, sector: "IT" },
  { symbol: "TCS", company: "TCS", date: isoDate(-10), result: "inline", estimate: 28.1, actual: 28.0, sector: "IT" },
  { symbol: "HDFCBANK", company: "HDFC Bank", date: isoDate(-8), result: "beat", estimate: 19.8, actual: 20.5, sector: "Banking" },
  { symbol: "RELIANCE", company: "Reliance Industries", date: isoDate(-7), result: "missed", estimate: 62.0, actual: 59.3, sector: "Energy" },
  { symbol: "WIPRO", company: "Wipro", date: isoDate(-5), result: "beat", estimate: 6.1, actual: 6.4, sector: "IT" },
  { symbol: "ICICIBANK", company: "ICICI Bank", date: isoDate(-4), result: "beat", estimate: 15.2, actual: 16.1, sector: "Banking" },
  { symbol: "AXISBANK", company: "Axis Bank", date: isoDate(-2), result: "missed", estimate: 18.4, actual: 17.9, sector: "Banking" },
  { symbol: "LT", company: "L&T", date: isoDate(-1), result: "inline", estimate: 30.2, actual: 30.4, sector: "Infra" },
  // Future
  { symbol: "BAJFINANCE", company: "Bajaj Finance", date: isoDate(2), sector: "Finance" },
  { symbol: "MARUTI", company: "Maruti Suzuki", date: isoDate(3), sector: "Auto" },
  { symbol: "TATASTEEL", company: "Tata Steel", date: isoDate(3), sector: "Metals" },
  { symbol: "SUNPHARMA", company: "Sun Pharma", date: isoDate(5), sector: "Pharma" },
  { symbol: "ONGC", company: "ONGC", date: isoDate(7), sector: "Energy" },
  { symbol: "HINDUNILVR", company: "HUL", date: isoDate(8), sector: "FMCG" },
  { symbol: "SBIN", company: "State Bank of India", date: isoDate(10), sector: "Banking" },
  { symbol: "KOTAKBANK", company: "Kotak Bank", date: isoDate(12), sector: "Banking" },
  { symbol: "DRREDDY", company: "Dr Reddy's", date: isoDate(14), sector: "Pharma" },
  { symbol: "TECHM", company: "Tech Mahindra", date: isoDate(15), sector: "IT" },
];

export const SAMPLE_SECTORS = [...new Set(SAMPLE_EARNINGS.map((e) => e.sector))].sort();
