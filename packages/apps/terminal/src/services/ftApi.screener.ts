import { get, isDemoAuthSession } from "./ftApi.helpers";

export interface FiiDiiSnapshot {
  trade_date: string;
  fii_buy: number;
  fii_sell: number;
  fii_net: number;
  dii_buy: number;
  dii_sell: number;
  dii_net: number;
  fii_idx_fut_long: number;
  fii_idx_fut_short: number;
  fii_idx_fut_net: number;
  fii_stk_fut_long: number;
  fii_stk_fut_short: number;
  fii_stk_fut_net: number;
  fii_idx_call_long: number;
  fii_idx_call_short: number;
  fii_idx_call_net: number;
  fii_idx_put_long: number;
  fii_idx_put_short: number;
  fii_idx_put_net: number;
  dii_idx_fut_long: number;
  dii_idx_fut_short: number;
  dii_idx_fut_net: number;
  dii_stk_fut_long: number;
  dii_stk_fut_short: number;
  dii_stk_fut_net: number;
  pcr: number;
  sentiment_score: number;
  updated_at: string;
}

export interface FiiDiiTrend {
  days: number;
  snapshots: FiiDiiSnapshot[];
  fii_net_total: number;
  dii_net_total: number;
  avg_sentiment: number;
}

export interface FiiDiiResponse {
  is_sample_data: boolean;
  latest: FiiDiiSnapshot;
  trend: FiiDiiTrend | null;
}

export interface RRGTailPoint {
  date: string;
  rs_ratio: number;
  rs_momentum: number;
}

export type RRGQuadrant = "leading" | "weakening" | "lagging" | "improving" | "neutral";

export interface SectorRRG {
  symbol: string;
  name: string;
  tail: RRGTailPoint[];
  current_quadrant: RRGQuadrant;
}

export interface RRGResponse {
  benchmark: string;
  tail_length: number;
  is_sample_data: boolean;
  sectors: SectorRRG[];
}

export const getFiiDiiData = (days?: number, refresh?: boolean) => {
  const params = new URLSearchParams();
  if (days !== undefined) params.set("days", String(days));
  if (refresh) params.set("refresh", "true");
  const qs = params.toString();
  return get<FiiDiiResponse>("screener/fii-dii" + (qs ? "?" + qs : ""));
};

export const getRRGData = (tailLength?: number): Promise<RRGResponse> => {
  const params = new URLSearchParams();
  if (tailLength !== undefined) params.set("tail_length", String(tailLength));
  const qs = params.toString();
  return get<RRGResponse>("rrg/sectors" + (qs ? "?" + qs : ""));
};

// ─── Shareholding ─────────────────────────────────────────────────────────────

export interface QuarterlyHolding {
  quarter: string;
  percentage: number;
}

export interface ShareholdingData {
  symbol: string;
  as_of_quarter: string;
  promoter_pct: number;
  fii_pct: number;
  dii_pct: number;
  public_pct: number;
  government_pct: number;
  promoter_history: QuarterlyHolding[];
  fii_history: QuarterlyHolding[];
  dii_history: QuarterlyHolding[];
  public_history: QuarterlyHolding[];
}

export interface AnnualFinancial {
  year: string;
  revenue: number | null;
  net_profit: number | null;
  operating_cash_flow: number | null;
}

export interface FinancialSummary {
  symbol: string;
  revenue: number | null;
  net_profit: number | null;
  operating_cash_flow: number | null;
  debt_to_equity: number | null;
  roe: number | null;
  roce: number | null;
  pe_ratio: number | null;
  market_cap: number | null;
  book_value: number | null;
  annual_history: AnnualFinancial[];
}

export interface CorporateAnnouncement {
  symbol: string;
  date: string;
  category: string;
  headline: string;
  attachment_url: string;
}

export interface ShareholdingResponse {
  is_sample_data: boolean;
  shareholding: ShareholdingData;
  financials: FinancialSummary;
  announcements: CorporateAnnouncement[];
}

export const getShareholding = (symbol: string): Promise<ShareholdingResponse> =>
  get<ShareholdingResponse>(
    "screener/shareholding?symbol=" + encodeURIComponent(symbol.toUpperCase()),
  );

// ─── Lot Size ────────────────────────────────────────────────────────────────

export interface LotSizeResponse {
  symbol: string;
  exchange: string;
  lot_size: number;
}

/**
 * Fetch the lot size for a given symbol from the FlintTrade backend.
 * Falls back to the built-in table on the server side if live data
 * is unavailable.
 */
// ─── Sector Constituents ─────────────────────────────────────────────────────

export interface SectorConstituentRRG {
  symbol: string;
  name: string;
  weight: number;
  tail: RRGTailPoint[];
  current_quadrant: RRGQuadrant;
}

export interface SectorConstituentsResponse {
  sector: string;
  benchmark: string;
  is_sample_data: boolean;
  constituents: SectorConstituentRRG[];
}

/**
 * Fetch the individual stock RRG positions within a sector.
 * Used for the drill-down view in the Portfolio RRG tab.
 */
export const getSectorConstituents = (
  sector: string,
  tailLength?: number,
): Promise<SectorConstituentsResponse> => {
  const params = new URLSearchParams();
  params.set("sector", sector);
  if (tailLength !== undefined) params.set("tail_length", String(tailLength));
  return get<SectorConstituentsResponse>(
    "screener/sector-constituents?" + params.toString(),
  );
};

// ─── Lot Size ────────────────────────────────────────────────────────────────

export const getLotSize = (
  symbol: string,
  exchange: string = "NFO",
): Promise<LotSizeResponse> => {
  if (isDemoAuthSession()) {
    const fallbackLotSize = symbol.toUpperCase().includes("BANK")
      ? 30
      : symbol.toUpperCase().includes("FIN")
        ? 40
        : 75;
    return Promise.resolve({
      symbol,
      exchange,
      lot_size: fallbackLotSize,
    });
  }

  return get<LotSizeResponse>(
    `screener/lot-size?symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}`,
  );
};
