import { get, post, postV1 } from "./ftApi.helpers";
import type {
  GEXData,
  VolSurfaceData,
  IVSmileData,
  StraddlePnLData,
  StraddleLeg,
  OIProfileData,
} from "@/types/api";

export type { GEXData, VolSurfaceData, IVSmileData, StraddlePnLData, StraddleLeg, OIProfileData };


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
  post<IVSmileData>("ivsmile", {
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

export const compilePineScript = (code: string) =>
  post<PineCompileResult>("indicators/pine/compile", { code });

// --- Multi-timeframe confluence (registered at the bare /v1 family) ---------

/** OHLCV bar accepted by the multi-timeframe analyser. ``timestamp`` is
 *  optional (epoch seconds); only OHLCV values drive the indicators. */
export interface MtfBar {
  timestamp?: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MtfSignal {
  timeframe: string;
  trend: "bullish" | "bearish" | "neutral";
  rsi: number;
  macd_histogram: number;
  ema_position: "above" | "below";
  strength: number;
}

export interface MtfAnalysis {
  symbol: string;
  signals: MtfSignal[];
  confluence: number;
  overall: "bullish" | "bearish" | "neutral";
}

/**
 * Compute multi-timeframe signal confluence for a symbol.
 *
 * The analyser (RSI / MACD / EMA per timeframe) lives in the screener service
 * and is registered at the bare ``/v1`` blueprint family, so this must go
 * through {@link postV1} (``/v1/analytics/mtf``) — the ``/api/v1`` `post`
 * helper would 404. Callers supply live OHLCV bars per timeframe (typically
 * fetched via ``getHistory``); the backend skips any timeframe with fewer than
 * 30 bars.
 */
export const getMultiTimeframe = (
  symbol: string,
  data: Record<string, MtfBar[]>,
) =>
  postV1<MtfAnalysis>("analytics/mtf", { symbol, data });

// --- Pair correlation (registered at the bare /v1 family) -------------------

/** Per-symbol returns + prices series fed to the pair-correlation engine. */
export interface PairSeries {
  returns: number[];
  prices: number[];
}

export interface PairSignal {
  pair: [string, string];
  correlation: number;
  current_spread: number;
  mean_spread: number;
  std_spread: number;
  z_score: number;
  signal: "converging" | "diverging" | "neutral";
}

export interface PairCorrelationResponse {
  signals: PairSignal[];
}

/**
 * Analyse the engine's preset instrument pairs for spread divergence.
 *
 * Preset mode: the backend forms its own preset pairs and analyses only those
 * whose BOTH legs are present in ``data`` (others are silently skipped). So a
 * caller can drive it with just the symbols it can fetch live (e.g. NSE
 * equities/indices), and the commodity/currency presets simply fall away.
 * Registered at the bare ``/v1`` family → must use {@link postV1}.
 */
export const getPairCorrelation = (data: Record<string, PairSeries>) =>
  postV1<PairCorrelationResponse>("analytics/pairs", { preset: true, data });

// --- Volatility cone (registered at the bare /v1 family) --------------------

/** One lookback row of the volatility cone (HV percentiles are decimals). */
export interface VolConePoint {
  lookback: number;
  current_hv: number;
  current_iv: number | null;
  p10: number;
  p25: number;
  p50: number;
  p75: number;
  p90: number;
  min: number;
  max: number;
  iv_percentile: number | null;
}

/**
 * Compute a historical-volatility cone from a daily-return series.
 *
 * The screener's {@link https VolatilityCone} engine (rolling-HV percentile
 * stats) is registered at the bare ``/v1`` family, so this must use
 * {@link postV1} (``/v1/analytics/volcone``). Callers supply the daily-return
 * series (oldest first; derivable from ``getHistory`` closes) and optionally the
 * current implied vol to overlay; ``parseResponse`` unwraps the envelope so this
 * returns the per-lookback rows directly. The series must hold at least
 * ``max(lookback_periods) + 1`` points or the backend returns 422.
 */
export const getVolatilityCone = (
  returns: number[],
  lookbackPeriods?: number[],
  currentIv?: number,
) =>
  postV1<VolConePoint[]>("analytics/volcone", {
    returns,
    ...(lookbackPeriods ? { lookback_periods: lookbackPeriods } : {}),
    ...(currentIv !== undefined ? { current_iv: currentIv } : {}),
  });

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
