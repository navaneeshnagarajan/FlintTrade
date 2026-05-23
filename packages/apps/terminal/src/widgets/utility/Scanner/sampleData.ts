/**
 * sampleData.ts — Realistic Indian market sample data for the Pre-Market Scanner.
 *
 * Seeded with NIFTY 50 stocks and realistic pre-market patterns.
 * Will be replaced with real OpenAlgo data when pre-market API is available.
 */

// ─── Types ──────────────────────────────────────────────────────────────────────

export interface GapScanEntry {
  symbol: string;
  exchange: string;
  prevClose: number;
  openPrice: number;
  gapPercent: number;
  gapType: "up" | "down";
  volume: number;
  sector: string;
}

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

export interface VolumeSpikeEntry {
  symbol: string;
  exchange: string;
  preMarketVolume: number;
  avgVolume: number;
  volumeRatio: number;
  price: number;
  changePercent: number;
  sector: string;
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

export const SAMPLE_GAP_SCANS: GapScanEntry[] = [
  { symbol: "TATAMOTORS", exchange: "NSE", prevClose: 985.45, openPrice: 1012.30, gapPercent: 2.73, gapType: "up", volume: 2_450_000, sector: "Auto" },
  { symbol: "BAJFINANCE", exchange: "NSE", prevClose: 7245.00, openPrice: 7412.50, gapPercent: 2.31, gapType: "up", volume: 1_125_000, sector: "Finance" },
  { symbol: "INFY", exchange: "NSE", prevClose: 1842.00, openPrice: 1875.60, gapPercent: 1.82, gapType: "up", volume: 3_200_000, sector: "IT" },
  { symbol: "SUNPHARMA", exchange: "NSE", prevClose: 1625.30, openPrice: 1650.80, gapPercent: 1.57, gapType: "up", volume: 980_000, sector: "Pharma" },
  { symbol: "ADANIENT", exchange: "NSE", prevClose: 2840.00, openPrice: 2878.50, gapPercent: 1.36, gapType: "up", volume: 1_560_000, sector: "Infra" },
  { symbol: "HDFCBANK", exchange: "NSE", prevClose: 1685.20, openPrice: 1698.40, gapPercent: 0.78, gapType: "up", volume: 4_100_000, sector: "Banking" },
  { symbol: "WIPRO", exchange: "NSE", prevClose: 542.80, openPrice: 535.20, gapPercent: -1.40, gapType: "down", volume: 2_800_000, sector: "IT" },
  { symbol: "COALINDIA", exchange: "NSE", prevClose: 478.90, openPrice: 470.15, gapPercent: -1.83, gapType: "down", volume: 1_950_000, sector: "Metals" },
  { symbol: "ONGC", exchange: "NSE", prevClose: 265.40, openPrice: 259.80, gapPercent: -2.11, gapType: "down", volume: 3_400_000, sector: "Energy" },
  { symbol: "TATASTEEL", exchange: "NSE", prevClose: 145.60, openPrice: 141.85, gapPercent: -2.58, gapType: "down", volume: 5_200_000, sector: "Metals" },
  { symbol: "RELIANCE", exchange: "NSE", prevClose: 2945.00, openPrice: 2870.30, gapPercent: -2.54, gapType: "down", volume: 6_100_000, sector: "Energy" },
  { symbol: "SBIN", exchange: "NSE", prevClose: 815.30, openPrice: 793.40, gapPercent: -2.68, gapType: "down", volume: 7_800_000, sector: "Banking" },
];

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

export const SAMPLE_VOLUME_SPIKES: VolumeSpikeEntry[] = [
  { symbol: "TATAMOTORS", exchange: "NSE", preMarketVolume: 2_450_000, avgVolume: 850_000, volumeRatio: 2.88, price: 1012.30, changePercent: 2.73, sector: "Auto" },
  { symbol: "SBIN", exchange: "NSE", preMarketVolume: 7_800_000, avgVolume: 3_100_000, volumeRatio: 2.52, price: 793.40, changePercent: -2.68, sector: "Banking" },
  { symbol: "RELIANCE", exchange: "NSE", preMarketVolume: 6_100_000, avgVolume: 2_800_000, volumeRatio: 2.18, price: 2870.30, changePercent: -2.54, sector: "Energy" },
  { symbol: "TATASTEEL", exchange: "NSE", preMarketVolume: 5_200_000, avgVolume: 2_500_000, volumeRatio: 2.08, price: 141.85, changePercent: -2.58, sector: "Metals" },
  { symbol: "INFY", exchange: "NSE", preMarketVolume: 3_200_000, avgVolume: 1_600_000, volumeRatio: 2.00, price: 1875.60, changePercent: 1.82, sector: "IT" },
  { symbol: "WIPRO", exchange: "NSE", preMarketVolume: 2_800_000, avgVolume: 1_500_000, volumeRatio: 1.87, price: 535.20, changePercent: -1.40, sector: "IT" },
  { symbol: "ONGC", exchange: "NSE", preMarketVolume: 3_400_000, avgVolume: 1_900_000, volumeRatio: 1.79, price: 259.80, changePercent: -2.11, sector: "Energy" },
  { symbol: "BAJFINANCE", exchange: "NSE", preMarketVolume: 1_125_000, avgVolume: 650_000, volumeRatio: 1.73, price: 7412.50, changePercent: 2.31, sector: "Finance" },
  { symbol: "ADANIENT", exchange: "NSE", preMarketVolume: 1_560_000, avgVolume: 920_000, volumeRatio: 1.70, price: 2878.50, changePercent: 1.36, sector: "Infra" },
  { symbol: "HDFCBANK", exchange: "NSE", preMarketVolume: 4_100_000, avgVolume: 2_600_000, volumeRatio: 1.58, price: 1698.40, changePercent: 0.78, sector: "Banking" },
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
