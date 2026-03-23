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
  delta: number;
  gamma: number;
  theta: number;
  vega: number;
  iv: number;
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
}

export interface SmartOrderParams extends PlaceOrderParams {
  positionSize: number;
}

// --- GEX (Gamma Exposure) ---
export interface GexEntry {
  strike: number;
  call_gamma: number;
  put_gamma: number;
  net_gamma: number;
  call_oi: number;
  put_oi: number;
}

// --- IV Smile ---
export interface IVSmileEntry {
  strike: number;
  call_iv: number;
  put_iv: number;
  moneyness: number;
}

// --- Max Pain ---
export interface MaxPainData {
  max_pain_strike: number;
  strikes: Array<{
    strike: number;
    call_oi: number;
    put_oi: number;
    call_pain: number;
    put_pain: number;
    total_pain: number;
  }>;
}

// --- OI Profile ---
export interface OIProfileEntry {
  strike: number;
  type: "CE" | "PE";
  oi: number;
  oi_delta_d: number;
  ltp: number;
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
