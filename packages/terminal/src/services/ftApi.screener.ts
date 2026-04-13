import { get, post } from "./ftApi.helpers";

export interface FundamentalSearchResult {
  name: string;
  symbol: string;
  url: string;
}

export interface FundamentalData {
  symbol: string;
  company_name: string;
  current_price: number | null;
  market_cap: number | null;
  pe_ratio: number | null;
  pb_ratio: number | null;
  book_value: number | null;
  dividend_yield: number | null;
  roce: number | null;
  roe: number | null;
  face_value: number | null;
  high_low: { high: number | null; low: number | null } | null;
  sales: number | null;
  net_profit: number | null;
  operating_margin: number | null;
  sales_growth_3yr: number | null;
  profit_growth_3yr: number | null;
  promoter_holding: number | null;
  fii_holding: number | null;
  dii_holding: number | null;
  ev_to_ebitda: number | null;
  price_to_sales: number | null;
  sector: string;
  industry: string;
  bse_code: string;
  nse_symbol: string;
  pros: string[];
  cons: string[];
}

export interface FundamentalScreenFilters {
  pe_min?: number;
  pe_max?: number;
  pb_min?: number;
  pb_max?: number;
  market_cap_min?: number;
  market_cap_max?: number;
  roce_min?: number;
  roe_min?: number;
  dividend_yield_min?: number;
  sector?: string;
  sort_by?: string;
  limit?: number;
}

export interface FundamentalStockRow {
  symbol: string;
  name: string;
  exchange: string;
  market_cap: number;
  pe_ratio: number;
  pb_ratio: number;
  roe: number;
  roce: number;
  dividend_yield: number;
  sector: string;
}

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

export const searchFundamentals = (query: string) =>
  get<{
    query: string;
    results: FundamentalSearchResult[];
    count: number;
  }>("screener/fundamental/search?q=" + encodeURIComponent(query));

export const getFundamentals = (symbol: string) =>
  get<FundamentalData>("screener/fundamental/" + encodeURIComponent(symbol));

export const screenStocks = (filters: FundamentalScreenFilters) =>
  post<{
    stocks: FundamentalStockRow[];
    count: number;
    filters_applied: Record<string, unknown>;
  }>("screener/fundamental/screen", filters);

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
