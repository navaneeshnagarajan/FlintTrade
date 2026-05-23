/**
 * Sample earnings calendar data for explore/disconnected mode.
 * Companies and dates are illustrative only — not real financial data.
 */

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

// Build sample entries relative to today so calendar always looks populated
function isoDate(offset: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offset);
  return d.toISOString().slice(0, 10);
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
