// OpenAlgo API response types

export interface ApiResponse<T> {
  status: "success" | "error";
  message?: string;
  data?: T;
}

// --- Market Data ---
export interface Quote {
  symbol: string;
  exchange: string;
  ltp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  change?: number;
  pct?: number;
  prev_close?: number;
}

export interface DepthLevel {
  price: number;
  quantity: number;
  orders: number;
}

export interface MarketDepth {
  buy: DepthLevel[];
  sell: DepthLevel[];
}

export interface OHLCVBar {
  timestamp: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

// --- Trading ---
export interface Position {
  symbol: string;
  exchange: string;
  product: string;
  quantity: number;
  averagePrice: number;
  ltp: number;
  pnl: number;
  pnlPercent: number;
}

export interface Order {
  orderId: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
  orderType: string;
  status: string;
  product: string;
  strategy: string;
  timestamp: string;
  /** Present when the sandbox or broker row carries a stop trigger. Omitted, never invented as 0. */
  triggerPrice?: number;
}

export interface Trade {
  tradeId: string;
  orderId: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  price: number;
  timestamp: string;
}

export interface Holding {
  symbol: string;
  exchange: string;
  quantity: number;
  averagePrice: number;
  ltp: number;
  pnl: number;
  pnlPercent: number;
}

export interface Funds {
  availableCash: number;
  usedMargin: number;
  totalBalance: number;
}

// --- Options ---
export interface OptionChainStrike {
  strikePrice: number;
  ceSymbol: string;
  peSymbol: string;
  ceLtp: number;
  peLtp: number;
  ceOi: number;
  peOi: number;
  ceVolume: number;
  peVolume: number;
  ceIv: number;
  peIv: number;
  ceDelta?: number;
  ceGamma?: number;
  ceTheta?: number;
  ceVega?: number;
  peDelta?: number;
  peGamma?: number;
  peTheta?: number;
  peVega?: number;
}

export interface OptionChainData {
  symbol: string;
  expiry: string;
  spotPrice: number;
  strikes: OptionChainStrike[];
}

export interface Greeks {
  symbol?: string;
  exchange?: string;
  instrument_id?: string;
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  iv: number;
}

// --- Broker Capabilities (OpenAlgo 2.0.0.2) ---
export interface BrokerCapabilities {
  broker_name: string;
  broker_type: "equity" | "crypto" | "commodity" | "multi";
  supported_exchanges: string[];
  features: {
    market_protection: boolean;
    leverage: boolean;
    bracket_orders: boolean;
    cover_orders: boolean;
    [key: string]: boolean;
  };
}

// --- Leverage / Margin Settings ---
export interface LeverageSettings {
  leverage?: number;
  max_leverage?: number;
  margin_mode?: string;
  available?: number;
  used?: number;
  total?: number;
  leverage_ratio?: number;
  [key: string]: unknown;
}

// --- Order Placement ---
export interface PlaceOrderParams {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
  strategy?: string;
  /** Enable Market Price Protection — converts MARKET to LIMIT with price buffer. */
  marketProtection?: boolean;
  /**
   * Quantity shown publicly on the exchange order book; the remainder stays
   * hidden. Zero (the default) discloses the whole order. Carried through to
   * the backend as `disclosed_quantity`.
   */
  disclosedQuantity?: number;
}

export interface SmartOrderParams extends PlaceOrderParams {
  positionSize: number;
}

// --- Order modification / status / position control ---

export interface ModifyOrderParams {
  orderId: string;
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
  /**
   * Quantity shown publicly on the exchange order book. Carried through to
   * the backend as `disclosed_quantity` so a modify does not clear an
   * existing disclosure by sending an implicit zero.
   */
  disclosedQuantity?: number;
  strategy?: string;
}

export interface OrderStatusParams {
  orderId: string;
  strategy?: string;
}

export interface OpenPositionParams {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  product: "MIS" | "CNC" | "NRML";
  strategy?: string;
}

// --- Basket / multi-leg / split / options orders ---

export interface BasketOrderLeg {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  quantity: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
}

export interface BasketOrderParams {
  strategy?: string;
  orders: BasketOrderLeg[];
}

/** Per-leg outcome from the backend basket executor (order_routes `place_basket`). */
export interface BasketLegResult {
  leg_index: number;
  symbol: string;
  action: string;
  quantity: number;
  success: boolean;
  order_id: string;
  error: string;
  rolled_back: boolean;
  rollback_order_id: string;
}

/**
 * Response shape of `POST /api/v1/orders/basket` — returned on a 201 full
 * success. A 422 partial/total failure is thrown as an `OrderApiError` whose
 * `body` carries this same shape, so callers can surface the per-leg truth
 * (placed/failed counts, and any leg with `rolled_back: true` but an empty
 * `rollback_order_id` — a rollback that was attempted but never confirmed,
 * i.e. a possibly still-open live leg).
 */
export interface BasketOrderResult {
  status: "success" | "error";
  strategy: string;
  timestamp: string;
  placed_count: number;
  failed_count: number;
  rolled_back: boolean;
  order_ids: string[];
  legs: BasketLegResult[];
  message?: string;
  failed_leg_index?: number | null;
}

export interface SplitOrderParams {
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  totalQuantity: number;
  chunkSize: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
  delaySeconds?: number;
  strategy?: string;
}

export interface OptionsOrderParams {
  underlying: string;
  exchange: string;
  expiry: string;
  strike: number;
  optionType: "CE" | "PE";
  action: "BUY" | "SELL";
  quantity: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
  strategy?: string;
}

export interface OptionsMultiOrderLeg {
  expiry: string;
  strike: number;
  optionType: "CE" | "PE";
  action: "BUY" | "SELL";
  quantity: number;
  orderType: "MARKET" | "LIMIT" | "SL" | "SL-M";
  product: "MIS" | "CNC" | "NRML";
  price?: number;
  triggerPrice?: number;
}

export interface OptionsMultiOrderParams {
  underlying: string;
  exchange: string;
  legs: OptionsMultiOrderLeg[];
  strategy?: string;
}

// --- Greeks query ---

export interface OptionGreeksParams {
  symbol: string;
  exchange: string;
  /** Optional — derivable from symbol in most cases. */
  expiry?: string;
  strike?: number;
  optionType?: "CE" | "PE";
}

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

// --- Margin ---
export interface MarginData {
  total_margin_required: number;
  span_margin: number;
  exposure_margin: number;
}

// --- Holidays ---
export interface Holiday {
  date: string;
  description: string;
  holiday_type: string;
  closed_exchanges: string[];
  open_exchanges: Array<{
    exchange: string;
    start_time: number;
    end_time: number;
  }>;
}

// --- Market Timings ---
export interface MarketTiming {
  exchange: string;
  start_time: number;
  end_time: number;
}

// --- WebSocket ---
export interface WsTick {
  symbol: string;
  exchange: string;
  ltp: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  change?: number;
  pct?: number;
  /**
   * Previous session close price, fetched from REST /quotes on mount.
   * Not sent by WebSocket LTP mode — populated by usePrevClose hook.
   * Used to compute change% = (ltp - prevClose) / prevClose * 100.
   */
  prevClose?: number;
}

export type WsMode = "ltp" | "quote" | "depth";

export interface WsInstrument {
  symbol: string;
  exchange: string;
}

export type WsAction =
  | "subscribe_ltp"
  | "subscribe_quote"
  | "subscribe_depth"
  | "unsubscribe_ltp"
  | "unsubscribe_quote"
  | "unsubscribe_depth";
