import { get, post, postV1 } from "./ftApi.helpers";
import { classifySector } from "@/lib/sectors";
import type {
  GEXData,
  GammaDensityData,
  ArbitrageScanResponse,
  CandlestickPatternResponse,
  VolSurfaceData,
  IVSmileData,
  StraddlePnLData,
  StraddleLeg,
  OIProfileData,
} from "@/types/api";

export type { GEXData, GammaDensityData, ArbitrageScanResponse, CandlestickPatternResponse, VolSurfaceData, IVSmileData, StraddlePnLData, StraddleLeg, OIProfileData };


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
  /**
   * Absent on sample payloads — the backend stub deliberately stops minting
   * request-time timestamps on fabricated rates (a fresh ``updated_at`` on
   * stub data defeats the user's staleness instincts).
   */
  updated_at?: string;
  /**
   * True when the rates are fabricated. Survives the response unwrap because
   * this endpoint has no ``data`` envelope. Widgets must badge on THIS, not
   * on connection state — the backend serves the stub even when connected.
   */
  is_sample_data?: boolean;
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

type BackendEarningsResult = "beat" | "miss" | "meet" | "missed" | "inline" | null | undefined;

interface BackendEarningsCalendarEntry {
  symbol: string;
  company?: string;
  company_name?: string;
  date: string;
  result?: BackendEarningsResult;
  estimate?: number | null;
  estimated_eps?: number | null;
  actual?: number | null;
  actual_eps?: number | null;
  sector?: string | null;
}

interface BackendEarningsCalendarResponse {
  entries?: BackendEarningsCalendarEntry[];
  events?: BackendEarningsCalendarEntry[];
  /**
   * The earnings backend is synthetic-only (``generate_sample_data``); it
   * nests this flag inside ``data`` so it survives the response unwrap.
   */
  is_sample_data?: boolean;
}

export interface EarningsCalendarResult {
  entries: EarningsCalendarEntry[];
  /** True when the backend fabricated the rows — badge regardless of connection. */
  is_sample_data: boolean;
}

function normaliseEarningsResult(result: BackendEarningsResult): EarningsCalendarEntry["result"] | undefined {
  if (result === "beat" || result === "missed" || result === "inline") return result;
  if (result === "miss") return "missed";
  if (result === "meet") return "inline";
  return undefined;
}

function normaliseEarningsEntry(entry: BackendEarningsCalendarEntry): EarningsCalendarEntry {
  return {
    symbol: entry.symbol,
    company: entry.company ?? entry.company_name ?? entry.symbol,
    date: entry.date,
    result: normaliseEarningsResult(entry.result),
    estimate: entry.estimate ?? entry.estimated_eps ?? undefined,
    actual: entry.actual ?? entry.actual_eps ?? undefined,
    sector: entry.sector ?? classifySector(entry.symbol),
  };
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

export interface GlobalIndicesResponse {
  indices: GlobalIndexEntry[];
  /**
   * Absent on sample payloads — the backend stub no longer stamps ``now()``
   * on hardcoded index levels (fabricated prices "updated 5 seconds ago"
   * actively misled connected traders).
   */
  updated_at?: string;
  /**
   * True when the indices are fabricated. Survives the response unwrap
   * because this endpoint has no ``data`` envelope. Widgets must badge on
   * THIS, not on connection state.
   */
  is_sample_data?: boolean;
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

export const getGammaDensityData = (
  symbol: string,
  exchange: string,
  expiry?: string,
) =>
  post<GammaDensityData>("gammadensity", {
    symbol,
    exchange,
    ...(expiry ? { expiry } : {}),
  });

export interface ArbitrageScanRequest {
  cash_future?: Array<{
    underlying: string;
    spot: number;
    future_price: number;
    days_to_expiry: number;
    exchange?: string;
  }>;
  cross_exchange?: Array<{
    symbol: string;
    exchange_a: string;
    price_a: number;
    exchange_b: string;
    price_b: number;
  }>;
  risk_free_rate?: number;
  edge_threshold_pct?: number;
}

export const getArbitrageScan = (req: ArbitrageScanRequest = {}) =>
  post<ArbitrageScanResponse>("screener/arbitrage", req);

export interface CandlestickPatternBar {
  open: number;
  high: number;
  low: number;
  close: number;
  time?: string;
}

export const getCandlestickPatterns = (bars: CandlestickPatternBar[]) =>
  post<CandlestickPatternResponse>("candlestick-patterns", { bars });

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

// --- OI change analysis + unusual OI (bare /v1/oi family) -------------------

/** One strike's OI-action classification (signal_short: LB/SC/SB/LU/OA/OR/N). */
export interface OIChangeSignalRow {
  strike: number;
  option_type: "CE" | "PE";
  oi: number;
  oi_change: number;
  price_change: string;
  signal: string;
  signal_short: string;
}

export interface OIChangeAnalysisData {
  signals: OIChangeSignalRow[];
  long_buildups: number[];
  short_coverings: number[];
  short_buildups: number[];
  long_unwindings: number[];
  summary: Record<string, number>;
}

/**
 * Classify each strike's OI change as Long Build-up / Short Covering / Short
 * Build-up / Long Unwinding given the underlying's price direction.
 *
 * Registered at the bare ``/v1/oi`` family → {@link postV1}. The backend uses
 * the live option chain when a broker is connected, else a sample chain; the
 * caller decides sample-vs-live presentation by connection state (the route's
 * ``is_sample_data`` flag is a sibling of ``data`` and unwrapped away).
 */
export const getOIChangeAnalysis = (
  symbol: string,
  exchange: string,
  expiry: string,
  priceChange: "up" | "down" | "flat",
) =>
  postV1<OIChangeAnalysisData>("oi/analysis", {
    symbol,
    exchange,
    expiry,
    price_change: priceChange,
  });

/** One unusual-OI outlier (z-score over the strike OI-change distribution). */
export interface UnusualOIRow {
  strike: number;
  option_type: "CE" | "PE";
  oi: number;
  oi_change: number;
  change_pct: number;
  z_score: number;
  direction: "addition" | "reduction";
}

export interface UnusualOIData {
  unusual: UnusualOIRow[];
  count: number;
  threshold: number;
}

/**
 * Detect unusual OI activity — strikes whose OI change is a |z-score| ≥
 * ``threshold`` outlier. Registered at the bare ``/v1/oi`` family → {@link postV1}.
 */
export const getUnusualOI = (
  symbol: string,
  exchange: string,
  expiry: string,
  threshold?: number,
) =>
  postV1<UnusualOIData>("oi/unusual", {
    symbol,
    exchange,
    expiry,
    ...(threshold !== undefined ? { threshold } : {}),
  });

// --- Portfolio optimiser (bare /v1/portfolio family) ------------------------

export type OptimisationMethod =
  | "markowitz" | "risk_parity" | "equal_weight" | "min_variance" | "max_sharpe";

export interface PortfolioOptimiseConfig {
  method?: OptimisationMethod;
  risk_free_rate?: number;
  max_weight?: number;
  min_weight?: number;
}

export interface PortfolioResult {
  weights: Record<string, number>;
  expected_return: number;
  expected_volatility: number;
  sharpe_ratio: number;
  diversification_ratio: number;
}

/**
 * Mean-variance optimise portfolio weights over a basket's daily-return series.
 *
 * The numpy/scipy optimiser (`portfolio_optimiser.py`) is registered at the bare
 * ``/v1/portfolio`` family → {@link postV1}. ``returns`` maps ticker → an
 * EQUAL-LENGTH daily-return series (the backend builds a `pd.DataFrame` from it,
 * so callers must align/truncate the per-ticker series to a common length).
 */
export const optimisePortfolio = (
  returns: Record<string, number[]>,
  config?: PortfolioOptimiseConfig,
) =>
  postV1<PortfolioResult>("portfolio/optimise", {
    returns,
    ...(config ? { config } : {}),
  });

/**
 * Compute the efficient frontier for a basket's daily-return series.
 *
 * Returns ``n_points`` portfolios ordered low → high expected return, each a
 * full {@link PortfolioResult}. Same bare ``/v1/portfolio`` family and
 * equal-length ``returns`` contract as {@link optimisePortfolio}.
 */
export const getPortfolioFrontier = (
  returns: Record<string, number[]>,
  nPoints?: number,
  config?: PortfolioOptimiseConfig,
) =>
  postV1<PortfolioResult[]>("portfolio/frontier", {
    returns,
    ...(nPoints !== undefined ? { n_points: nPoints } : {}),
    ...(config ? { config } : {}),
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

export const getEarningsCalendar = async (
  year: number,
  month: number,
): Promise<EarningsCalendarResult> => {
  const raw = await get<BackendEarningsCalendarResponse>(
    `earnings/calendar?year=${year}&month=${month}`,
  );
  const rows = raw.entries ?? raw.events ?? [];
  return {
    entries: rows.map(normaliseEarningsEntry),
    // Propagated so the widget badges fabricated rows even when a broker is
    // connected — the "live" backend source is currently a sample generator.
    is_sample_data: raw.is_sample_data === true,
  };
};

export const getGlobalIndices = () =>
  get<GlobalIndicesResponse>("market/global_indices");
