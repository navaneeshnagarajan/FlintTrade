/**
 * sectors.ts
 *
 * Simple sector classification for NSE stocks.
 * Maps a stock symbol to its broad sector name.
 * Used by SectorTab, DashboardTab, NetWorthTab to group holdings, and by the
 * Positions heat map to group the position book.
 *
 * This is the SINGLE classification source. Two widget-local copies of a
 * hardcoded sector map used to exist alongside it and disagreed with it
 * (NTPC/POWERGRID as Infra vs Energy, ADANIPORTS as Logistics vs Infra,
 * BAJFINANCE as NBFC vs Finance); a symbol must not land in two sectors
 * depending on which panel is open. Add missing symbols HERE.
 */

/** Direct symbol → sector lookup (uppercase symbols). */
const SECTOR_MAP: Record<string, string> = {
  // Energy
  RELIANCE: "Energy",
  ONGC: "Energy",
  BPCL: "Energy",
  IOC: "Energy",
  GAIL: "Energy",
  NTPC: "Energy",
  POWERGRID: "Energy",
  TATAPOWER: "Energy",
  ADANIGREEN: "Energy",
  // IT
  TCS: "IT",
  INFY: "IT",
  WIPRO: "IT",
  HCLTECH: "IT",
  TECHM: "IT",
  LTI: "IT",
  LTIM: "IT",
  MPHASIS: "IT",
  COFORGE: "IT",
  PERSISTENT: "IT",
  // Banking
  HDFCBANK: "Banking",
  ICICIBANK: "Banking",
  SBIN: "Banking",
  KOTAKBANK: "Banking",
  AXISBANK: "Banking",
  INDUSINDBK: "Banking",
  FEDERALBNK: "Banking",
  RBLBANK: "Banking",
  BANDHANBNK: "Banking",
  IDFCFIRSTB: "Banking",
  // Pharma
  SUNPHARMA: "Pharma",
  DRREDDY: "Pharma",
  CIPLA: "Pharma",
  DIVISLAB: "Pharma",
  LUPIN: "Pharma",
  BIOCON: "Pharma",
  ALKEM: "Pharma",
  IPCA: "Pharma",
  ABBOTINDIA: "Pharma",
  // Auto
  MARUTI: "Auto",
  TATAMOTORS: "Auto",
  "M&M": "Auto",
  "BAJAJ-AUTO": "Auto",
  HEROMOTOCO: "Auto",
  EICHERMOT: "Auto",
  ASHOKLEY: "Auto",
  BOSCHLTD: "Auto",
  // FMCG
  HINDUNILVR: "FMCG",
  ITC: "FMCG",
  NESTLEIND: "FMCG",
  BRITANNIA: "FMCG",
  DABUR: "FMCG",
  MARICO: "FMCG",
  GODREJCP: "FMCG",
  EMAMILTD: "FMCG",
  // Metals
  TATASTEEL: "Metals",
  JSWSTEEL: "Metals",
  HINDALCO: "Metals",
  COALINDIA: "Metals",
  SAIL: "Metals",
  JINDALSTEL: "Metals",
  NATIONALUM: "Metals",
  VEDL: "Metals",
  // Infra / Conglomerate
  ADANIENT: "Infra",
  ADANIPORTS: "Infra",
  ULTRACEMCO: "Infra",
  SHREECEM: "Infra",
  ACC: "Infra",
  AMBUJACEMENT: "Infra",
  LT: "Infra",
  // Finance (non-bank)
  BAJFINANCE: "Finance",
  BAJAJFINSV: "Finance",
  HDFCLIFE: "Finance",
  SBILIFE: "Finance",
  ICICIGI: "Finance",
  CHOLAFIN: "Finance",
  MUTHOOTFIN: "Finance",
  // Telecom
  BHARTIARTL: "Telecom",
  IDEA: "Telecom",
  // Consumer Discretionary
  TITAN: "Consumer",
  TATACONSUM: "Consumer",
  ASIANPAINT: "Consumer",
  HAVELLS: "Consumer",
  VOLTAS: "Consumer",
  WHIRLPOOL: "Consumer",
};

/**
 * The tradable root of a symbol — the underlying, with any derivative
 * expiry/strike suffix removed and any leading token taken from a
 * whitespace-delimited option description.
 *
 * ```
 * "NIFTY24APR22500CE"      → "NIFTY"
 * "NIFTY 22200 CE 10APR"   → "NIFTY"
 * "RELIANCE"               → "RELIANCE"
 * "M&M"                    → "M&M"     (punctuation is preserved — the
 *                                       sector map keys on the real symbol)
 * ```
 */
export function symbolRoot(symbol: string): string {
  const head = symbol.trim().split(/\s+/)[0] || symbol.trim();
  const root = head.replace(/\d{2}[A-Z]{3}\d{2}.*$/i, "");
  return (root || head).toUpperCase();
}

/**
 * Returns the broad sector name for a given NSE symbol.
 *
 * Derivative symbols are classified by their underlying (a NIFTY option is
 * not its own sector), so the caller never has to pre-strip an expiry.
 * Falls back to "Other" for unrecognised symbols.
 */
export function classifySector(symbol: string): string {
  return SECTOR_MAP[symbolRoot(symbol)] ?? "Other";
}

export interface SectorBreakdownEntry {
  sector: string;
  value: number;
  /** Percentage of total portfolio value, 0–100. */
  pct: number;
}

/**
 * Aggregates a holdings list into sector buckets.
 * Result is sorted by value descending.
 */
export function getSectorBreakdown(
  holdings: { symbol: string; currentVal: number }[],
): SectorBreakdownEntry[] {
  const map = new Map<string, number>();
  let total = 0;

  for (const h of holdings) {
    const sector = classifySector(h.symbol);
    map.set(sector, (map.get(sector) ?? 0) + h.currentVal);
    total += h.currentVal;
  }

  return [...map.entries()]
    .map(([sector, value]) => ({
      sector,
      value,
      pct: total > 0 ? (value / total) * 100 : 0,
    }))
    .sort((a, b) => b.value - a.value);
}
