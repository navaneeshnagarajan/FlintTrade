/**
 * sampleData.ts — sample rows for the Pre-Market Scanner's OI Change and
 * Sectors tabs, which have no live scan source yet (disclosed per-tab).
 *
 * The Gap Scan and Volume tabs no longer read from here — they run real
 * backend prebuilt scans whose sample fallback lives server-side.
 */

// ─── Types ──────────────────────────────────────────────────────────────────────

export interface OIChangeEntry {
  symbol: string;
  exchange: string;
  prevOI: number;
  currentOI: number;
  oiChange: number;
  oiChangePct: number;
  signal: "bullish" | "bearish" | "neutral";
  price: number;
  priceChange: number;
}

export interface SectorMoverEntry {
  sector: string;
  advancers: number;
  decliners: number;
  unchanged: number;
  avgChange: number;
  topGainer: string;
  topLoser: string;
  signal: "strong" | "moderate" | "weak" | "bearish";
}

// ─── Sample Data ────────────────────────────────────────────────────────────────

export const SAMPLE_OI_CHANGES: OIChangeEntry[] = [
  { symbol: "NIFTY 24200 CE", exchange: "NFO", prevOI: 12_50_000, currentOI: 15_80_000, oiChange: 3_30_000, oiChangePct: 26.4, signal: "bullish", price: 245.50, priceChange: 12.5 },
  { symbol: "BANKNIFTY 51000 PE", exchange: "NFO", prevOI: 8_40_000, currentOI: 10_50_000, oiChange: 2_10_000, oiChangePct: 25.0, signal: "bearish", price: 310.20, priceChange: 45.8 },
  { symbol: "NIFTY 24000 PE", exchange: "NFO", prevOI: 18_20_000, currentOI: 22_10_000, oiChange: 3_90_000, oiChangePct: 21.4, signal: "bearish", price: 125.80, priceChange: -18.3 },
  { symbol: "RELIANCE 3000 CE", exchange: "NFO", prevOI: 5_60_000, currentOI: 6_70_000, oiChange: 1_10_000, oiChangePct: 19.6, signal: "bullish", price: 42.30, priceChange: 8.7 },
  { symbol: "HDFCBANK 1700 CE", exchange: "NFO", prevOI: 4_20_000, currentOI: 4_95_000, oiChange: 75_000, oiChangePct: 17.9, signal: "bullish", price: 28.40, priceChange: 5.2 },
  { symbol: "NIFTY 24500 CE", exchange: "NFO", prevOI: 22_00_000, currentOI: 25_60_000, oiChange: 3_60_000, oiChangePct: 16.4, signal: "bearish", price: 85.60, priceChange: -12.4 },
  { symbol: "TATAMOTORS 1000 CE", exchange: "NFO", prevOI: 3_80_000, currentOI: 4_35_000, oiChange: 55_000, oiChangePct: 14.5, signal: "bullish", price: 22.10, priceChange: 6.3 },
  { symbol: "BANKNIFTY 51500 CE", exchange: "NFO", prevOI: 6_10_000, currentOI: 6_90_000, oiChange: 80_000, oiChangePct: 13.1, signal: "bearish", price: 185.40, priceChange: -24.6 },
  { symbol: "INFY 1850 CE", exchange: "NFO", prevOI: 2_90_000, currentOI: 3_25_000, oiChange: 35_000, oiChangePct: 12.1, signal: "bullish", price: 35.70, priceChange: 9.1 },
  { symbol: "SBIN 820 PE", exchange: "NFO", prevOI: 7_50_000, currentOI: 8_30_000, oiChange: 80_000, oiChangePct: 10.7, signal: "bearish", price: 18.90, priceChange: 4.8 },
];

export const SAMPLE_SECTOR_MOVERS: SectorMoverEntry[] = [
  { sector: "Auto", advancers: 6, decliners: 2, unchanged: 0, avgChange: 1.85, topGainer: "TATAMOTORS", topLoser: "EICHERMOT", signal: "strong" },
  { sector: "Finance", advancers: 5, decliners: 2, unchanged: 1, avgChange: 1.42, topGainer: "BAJFINANCE", topLoser: "CHOLAFIN", signal: "strong" },
  { sector: "IT", advancers: 4, decliners: 4, unchanged: 2, avgChange: 0.35, topGainer: "INFY", topLoser: "WIPRO", signal: "moderate" },
  { sector: "Pharma", advancers: 4, decliners: 3, unchanged: 1, avgChange: 0.72, topGainer: "SUNPHARMA", topLoser: "BIOCON", signal: "moderate" },
  { sector: "Banking", advancers: 3, decliners: 5, unchanged: 2, avgChange: -0.45, topGainer: "HDFCBANK", topLoser: "SBIN", signal: "weak" },
  { sector: "Infra", advancers: 3, decliners: 4, unchanged: 1, avgChange: 0.28, topGainer: "ADANIENT", topLoser: "ULTRACEMCO", signal: "moderate" },
  { sector: "Energy", advancers: 2, decliners: 5, unchanged: 1, avgChange: -1.45, topGainer: "NTPC", topLoser: "RELIANCE", signal: "bearish" },
  { sector: "Metals", advancers: 1, decliners: 6, unchanged: 1, avgChange: -1.82, topGainer: "HINDALCO", topLoser: "TATASTEEL", signal: "bearish" },
  { sector: "FMCG", advancers: 4, decliners: 3, unchanged: 1, avgChange: 0.18, topGainer: "ITC", topLoser: "HINDUNILVR", signal: "moderate" },
  { sector: "Telecom", advancers: 1, decliners: 1, unchanged: 0, avgChange: 0.65, topGainer: "BHARTIARTL", topLoser: "IDEA", signal: "moderate" },
];
