/**
 * sampleData.ts — sample sector-mover rows for the Pre-Market Scanner's
 * Explore-mode Sectors tab (the only remaining sample surface).
 *
 * Gap/Volume run real backend prebuilt scans and OI Change consumes the
 * live /v1/oi/unusual surface — their sample fallbacks live server-side.
 */

// ─── Types ──────────────────────────────────────────────────────────────────────

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
