import { get, post } from "./ftApi.helpers";
import type {
  GEXData,
  VolSurfaceData,
  IVSmileData,
  StraddlePnLData,
  StraddleLeg,
  OIProfileData,
} from "@/types/api";

export type { GEXData, VolSurfaceData, IVSmileData, StraddlePnLData, StraddleLeg, OIProfileData };

export interface IndicatorBar {
  time: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

export interface PineCompileResult {
  python_code: string;
  imports: string[];
  warnings: string[];
  unsupported: string[];
  supported_functions: string[];
}

export interface EtfScreenerRow {
  symbol: string;
  name: string;
  category: "Equity" | "Gold" | "Silver" | "Debt" | "International" | "Sector";
  exchange: string;
  price: number;
  change_1d: number;
  change_1w: number;
  change_1m: number;
  change_3m: number;
  change_6m: number;
  change_1y: number;
  volume: number;
  week52_high: number;
  week52_low: number;
  expense_ratio: number;
  aum_cr: number;
  momentum_score: number;
  /** 30 normalised prices [0, 1] for sparkline rendering. */
  sparkline: number[];
  /** Calendar-year returns keyed by year string e.g. "2023". */
  annual_returns: Record<string, number>;
}

export interface EtfCalendarYear {
  year: string;
  returns: Record<string, number>; // symbol → return%
}

export interface EtfScreenerResponse {
  etfs: EtfScreenerRow[];
  updated_at: string;
  is_sample_data: boolean;
}

export interface SectorRotationRow {
  symbol: string;
  name: string;
  change_1d: number;
  change_1w: number;
  change_1m: number;
  change_3m: number;
  change_6m: number;
  change_1y: number;
  market_cap_cr: number;
  momentum_score: number;
  quadrant: "leading" | "weakening" | "lagging" | "improving";
}

export interface SectorRotationResponse {
  sectors: SectorRotationRow[];
  updated_at: string;
  is_sample_data: boolean;
}

export interface RiskReturnPoint {
  symbol: string;
  name: string;
  category: string;
  annualised_return: number;
  annualised_volatility: number;
  sharpe_ratio: number;
}

export interface RiskReturnResponse {
  points: RiskReturnPoint[];
  avg_return: number;
  avg_volatility: number;
  best_sharpe_symbol: string;
  best_sharpe: number;
  updated_at: string;
  is_sample_data: boolean;
}

export type MarketRegime = "Risk-On" | "Risk-Off" | "Rotation";

export interface CorrelationResponse {
  symbols: string[];
  matrix: number[][];
  regime: MarketRegime;
  regime_rationale: string;
  vix: number;
  dxy: number;
  updated_at: string;
  is_sample_data: boolean;
}

export interface FundingRateEntry {
  symbol: string;
  rate: number;
  predicted_rate: number;
  next_funding_ms: number;
  history: number[];
  open_interest_usd: number | null;
}

export interface FundingRatesResponse {
  rates: FundingRateEntry[];
  updated_at: string;
}

export interface EarningsCalendarEntry {
  symbol: string;
  company: string;
  date: string;
  result?: "beat" | "missed" | "inline";
  estimate?: number;
  actual?: number;
  sector: string;
}

export interface GlobalIndexEntry {
  id: string;
  name: string;
  region: "India" | "US" | "Europe" | "Asia";
  ltp: number;
  change: number;
  change_pct: number;
  history: number[];
}

export const getGEXData = (
  symbol: string,
  exchange: string,
  expiry_date?: string,
) =>
  post<GEXData>("gex", {
    symbol,
    exchange,
    ...(expiry_date ? { expiry_date } : {}),
  });

export const getVolSurface = (
  symbol: string,
  exchange: string,
  expiry_dates: string[],
  strike_count?: number,
) =>
  post<VolSurfaceData>("volsurface", {
    symbol,
    exchange,
    expiry_dates,
    ...(strike_count !== undefined ? { strike_count } : {}),
  });

export const getFtIVSmile = (
  symbol: string,
  exchange: string,
  expiry_dates?: string[],
) =>
  post<IVSmileData>("iv_smile", {
    symbol,
    exchange,
    ...(expiry_dates ? { expiry_dates } : {}),
  });

export const getStraddlePnL = (
  symbol: string,
  exchange: string,
  expiry_date: string,
  adjustments?: StraddleLeg[],
) =>
  post<StraddlePnLData>("straddlepnl", {
    symbol,
    exchange,
    expiry_date,
    ...(adjustments ? { adjustments } : {}),
  });

export const getFtOIProfile = (
  symbol: string,
  exchange: string,
  expiry_date: string,
  strike_count?: number,
) =>
  post<OIProfileData>("oiprofile", {
    symbol,
    exchange,
    expiry_date,
    ...(strike_count !== undefined ? { strike_count } : {}),
  });

export const computeIndicators = (
  bars: IndicatorBar[],
  indicators: string[],
) =>
  post<Record<string, unknown>>("indicators/compute", {
    bars: bars as IndicatorBar[],
    indicators,
  });

export const compilePineScript = (code: string) =>
  post<PineCompileResult>("indicators/pine/compile", { code });

export const getEtfScreener = () =>
  get<EtfScreenerResponse>("etf/screener");

export const getSectorRotation = () =>
  get<SectorRotationResponse>("sectors/rotation");

export const getRiskReturn = () =>
  get<RiskReturnResponse>("analytics/risk-return");

export const getCorrelationMatrix = () =>
  get<CorrelationResponse>("analytics/correlation");

export const getCryptoFundingRates = () =>
  get<FundingRatesResponse>("crypto/funding_rates");

export const getEarningsCalendar = (year: number, month: number) =>
  get<{ entries: EarningsCalendarEntry[] }>(
    `earnings/calendar?year=${year}&month=${month}`,
  );

export const getGlobalIndices = () =>
  get<{ indices: GlobalIndexEntry[]; updated_at: string }>("market/global_indices");
