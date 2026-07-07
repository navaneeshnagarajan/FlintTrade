import { get, getV1, isDemoAuthSession, postV1 } from "./ftApi.helpers";

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

// DP1 — FII long/short ratio surface (derived from participant-OI).
export type FiiBiasLabel =
  | "Strongly Long"
  | "Long"
  | "Neutral"
  | "Short"
  | "Strongly Short";

export interface FiiLongShortSegment {
  segment: string;
  label: string;
  long: number;
  short: number;
  net: number;
  ls_ratio: number;
  long_pct: number;
}

export interface FiiLongShortRatio {
  trade_date: string;
  segments: FiiLongShortSegment[];
  futures_long: number;
  futures_short: number;
  futures_bias: number;
  bias_label: FiiBiasLabel;
  updated_at: string;
}

export interface FiiLongShortResponse {
  is_sample_data: boolean;
  ratio: FiiLongShortRatio;
}

export const getFiiLongShortData = (refresh?: boolean) => {
  const qs = refresh ? "?refresh=true" : "";
  return get<FiiLongShortResponse>("screener/fii-long-short" + qs);
};

// W7 — Index contribution decomposition (served by the /v1 breadth blueprint).
export interface IndexConstituent {
  symbol: string;
  weight: number;
  ltp: number;
  prev_close: number;
  change_pct: number;
  contribution_pct: number;
  contribution_points: number;
}

export interface IndexContribution {
  index_name: string;
  index_level: number;
  index_change_pct: number;
  index_change_points: number;
  weights_as_of: string;
  advancers: number;
  decliners: number;
  constituents: IndexConstituent[];
}

export interface IndexContributionResponse {
  is_sample_data: boolean;
  contribution: IndexContribution;
}

export const getIndexContribution = (index: string) =>
  getV1<IndexContributionResponse>(
    "index-contribution?index=" + encodeURIComponent(index),
  );

export const getRRGData = (tailLength?: number): Promise<RRGResponse> => {
  const params = new URLSearchParams();
  if (tailLength !== undefined) params.set("tail_length", String(tailLength));
  const qs = params.toString();
  return get<RRGResponse>("rrg/sectors" + (qs ? "?" + qs : ""));
};

export const getPortfolioRRGData = (
  symbols: string[],
  tailLength?: number,
): Promise<RRGResponse> => {
  const params = new URLSearchParams();
  params.set("symbols", symbols.join(","));
  if (tailLength !== undefined) params.set("tail_length", String(tailLength));
  return get<RRGResponse>("rrg/portfolio?" + params.toString());
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
  /**
   * True when the lot size came from a hardcoded table rather than the
   * broker symbol master. The backend stub and the demo-session fallback
   * both set it. This value multiplies REAL order quantities in the
   * Scalper, so consumers must treat a flagged lot size as unverified —
   * never silently prefer it over an audited local config.
   */
  is_sample_data?: boolean;
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

// ─── Market scanner (bare /v1/scanner family) ────────────────────────────────

export interface PrebuiltScanCondition {
  label: string;
  indicator: string;
  operator: string;
  value: number;
}

export interface PrebuiltScan {
  key: string;
  name: string;
  universe: string;
  timeframe: string;
  condition_count: number;
  conditions: PrebuiltScanCondition[];
}

export interface ScannerResultRow {
  symbol: string;
  exchange: string;
  ltp: number;
  change_pct: number;
  matched_conditions: string[];
  scan_time: string;
  score: number;
}

/** Full /v1/scanner/run body — no `data` wrapper, so the flag survives unwrap. */
export interface ScannerRunResponse {
  status: string;
  is_sample_data: boolean;
  scan_name: string;
  matched_count: number;
  total_universe: number;
  results: ScannerResultRow[];
}

/** List the prebuilt declarative scans (RSI oversold, volume spikes, …). */
export const getPrebuiltScans = () =>
  getV1<{ scans: PrebuiltScan[] }>("scanner/prebuilt");

/**
 * Run a prebuilt scan. The response carries ``is_sample_data`` itself —
 * live OHLCV via the broker registry when connected, deterministic synthetic
 * bars otherwise — so the caller badges from the response, not connection
 * guesswork. Registered at the bare ``/v1`` family → {@link postV1}.
 */
export const runPrebuiltScan = (key: string) =>
  postV1<ScannerRunResponse>("scanner/run", { prebuilt: key });

// ─── Economic calendar (bare /v1/economic family) ────────────────────────────

/** Backend macro-event row (economic_calendar.EconomicEvent.to_dict). */
export interface BackendEconomicEvent {
  date: string;
  time: string;
  event: string;
  country: string;
  impact: "high" | "medium" | "low";
  previous: string | null;
  forecast: string | null;
  actual: string | null;
  category: string;
}

export interface EconomicCalendarData {
  days: number;
  events: BackendEconomicEvent[];
}

/**
 * Fetch the macro economic calendar from the backend.
 *
 * The provider currently generates a deterministic sample schedule (no live
 * macro feed is integrated), so consumers must keep their sample badging; the
 * value of wiring is single-source-of-truth — when the provider gains a live
 * source, every consumer lights up without a frontend change. Registered at
 * the bare ``/v1`` family → {@link getV1}.
 */
export const getEconomicCalendar = (days?: number) =>
  getV1<EconomicCalendarData>(
    "economic/calendar" + (days !== undefined ? `?days=${days}` : ""),
  );

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
      // Fabricated on the client for demo sessions — flag it like the
      // backend stub does, so no consumer can mistake it for the symbol
      // master.
      is_sample_data: true,
    });
  }

  return get<LotSizeResponse>(
    `screener/lot-size?symbol=${encodeURIComponent(symbol)}&exchange=${encodeURIComponent(exchange)}`,
  );
};
