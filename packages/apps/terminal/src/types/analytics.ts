/** Analytics returned by FlintTrade's option and research endpoints.
 * These are native response contracts; sample provenance is explicit.
 */
// --- GEX (Gamma Exposure) ---
export interface GexEntry {
  strike: number;
  call_gex: number;
  put_gex: number;
  net_gex: number;
  call_oi: number;
  put_oi: number;
}

export interface ProvenancedRows<T> {
  rows: T[];
  /** Missing provenance is treated as sample/untrusted by the API normaliser. */
  is_sample_data: boolean;
}

// --- IV Smile ---
export interface IVSmileEntry {
  strike: number;
  /** Decimal IV, e.g. 0.14 = 14%. */
  call_iv: number;
  /** Decimal IV, e.g. 0.14 = 14%. */
  put_iv: number;
  /** Strike/spot ratio; ATM is 1.0. */
  moneyness: number;
}

export interface IVSmileSeriesData {
  points: IVSmileEntry[];
  /** Missing provenance is treated as sample/untrusted by the API normaliser. */
  is_sample_data: boolean;
}

// --- Max Pain ---
export interface MaxPainData {
  /** Missing provenance is treated as sample/untrusted by the API normaliser. */
  is_sample_data: boolean;
  /** Null when the backend did not provide a valid positive strike. */
  max_pain_strike: number | null;
  total_loss_at_max_pain?: number;
  strike_losses?: Array<{
    strike: number;
    total_loss: number;
  }>;
  strikes: Array<{
    strike: number;
    call_oi?: number;
    put_oi?: number;
    call_pain?: number;
    put_pain?: number;
    total_pain: number;
  }>;
}

// --- OI Profile ---
export interface OIProfileEntry {
  strike: number;
  type: "CE" | "PE";
  oi: number;
  /** Omitted until the backend has a trustworthy prior OI snapshot. */
  oi_delta_d?: number;
  /** Omitted when the backend response has no option-leg price. */
  ltp?: number;
  /** Omitted until a trustworthy prior-price snapshot is available. */
  price_change?: number;
}

// --- GEX (new FlintTrade backend shape) ---
export interface GEXStrike {
  strike: number;
  call_gex: number;
  put_gex: number;
  net_gex: number;
  call_oi: number;
  put_oi: number;
}

export interface GEXData {
  underlying: string;
  spot_price: number;
  atm_strike: number;
  strikes: GEXStrike[];
  gamma_flip_strike: number | null;
  dealer_zone: string;
  total_call_gex: number;
  total_put_gex: number;
  net_gex: number;
}

// --- Gamma Density (DP2) ---
export interface GammaDensityStrike {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  iv: number;
  density_intraday: number;
  density_expiry: number;
}

export interface GammaExpectedMoveBand {
  sigma_move: number;
  one_sigma_low: number;
  one_sigma_high: number;
  two_sigma_low: number;
  two_sigma_high: number;
}

export interface GammaDensityData {
  underlying: string;
  exchange: string;
  spot_price: number;
  atm_strike: number;
  atm_iv: number;
  dte_days: number;
  peak_intraday_strike: number | null;
  peak_expiry_strike: number | null;
  intraday_band: GammaExpectedMoveBand;
  expiry_band: GammaExpectedMoveBand;
  strikes: GammaDensityStrike[];
}

// --- Arbitrage scanner (DP3) ---
export type ArbSignal = "cash_and_carry" | "reverse" | "fair";

export interface CashFutureOpportunity {
  underlying: string;
  exchange: string;
  spot: number;
  future_price: number;
  days_to_expiry: number;
  basis: number;
  basis_pct: number;
  fair_basis: number;
  mispricing: number;
  annualised_return_pct: number;
  signal: ArbSignal;
}

export interface CrossExchangeOpportunity {
  symbol: string;
  exchange_a: string;
  price_a: number;
  exchange_b: string;
  price_b: number;
  spread: number;
  spread_pct: number;
  buy_on: string;
  sell_on: string;
}

export interface ArbitrageScan {
  risk_free_rate: number;
  edge_threshold_pct: number;
  cash_future: CashFutureOpportunity[];
  cross_exchange: CrossExchangeOpportunity[];
}

export interface ArbitrageScanResponse {
  is_sample_data: boolean;
  scan: ArbitrageScan;
}

// --- Candlestick pattern detection (W4) ---
export type PatternDirection = "bullish" | "bearish" | "neutral";

export interface PatternMatch {
  index: number;
  time: string;
  pattern: string;
  label: string;
  direction: PatternDirection;
  strength: number;
}

export interface PatternScan {
  bar_count: number;
  matches: PatternMatch[];
}

export interface CandlestickPatternResponse {
  is_sample_data: boolean;
  scan: PatternScan;
}

// --- Vol Surface ---
export interface VolSurfaceData {
  underlying: string;
  spot_price: number;
  strikes: number[];
  expiries: string[];
  days_to_expiry: number[];
  iv_matrix: number[][];
  atm_strike: number;
}

// --- IV Smile (new FlintTrade backend shape) ---
export interface IVSmileCurveData {
  expiry: string;
  days_to_expiry: number;
  /** Decimal IV, e.g. 0.14 = 14%. */
  atm_iv: number;
  atm_strike: number;
  points: IVSmileEntry[];
  /** Decimal IV difference, e.g. 0.02 = two volatility points. */
  skew_25delta: number;
}

export interface IVSmileData {
  underlying: string;
  spot_price: number;
  curves: IVSmileCurveData[];
  /** True when the backend fabricated the curves instead of using a complete live chain. */
  is_sample_data: boolean;
}

// --- Straddle P&L ---
export interface StraddleLeg {
  strike: number;
  type: "CE" | "PE";
  action: "BUY" | "SELL";
  premium: number;
  lots: number;
}

export interface StraddlePnLPoint {
  spot_price: number;
  pnl: number;
}

export interface StraddlePnLData {
  underlying: string;
  atm_strike: number;
  call_premium: number;
  put_premium: number;
  break_even_low: number;
  break_even_high: number;
  max_loss: number;
  curve: StraddlePnLPoint[];
  legs: StraddleLeg[];
}

// --- OI Profile (new FlintTrade backend shape) ---
export interface OIProfileStrike {
  strike: number;
  ce_oi: number;
  pe_oi: number;
  ce_oi_change: number;
  pe_oi_change: number;
}

export interface OIProfileData {
  underlying: string;
  expiry: string;
  spot_price: number;
  atm_strike: number;
  max_pain_strike: number;
  strikes: OIProfileStrike[];
  total_ce_oi: number;
  total_pe_oi: number;
  pcr: number;
}

// --- Synthetic Future ---
export interface SyntheticFutureData {
  underlying: string;
  underlying_ltp: number;
  expiry: string;
  atm_strike: number;
  synthetic_future_price: number;
}
