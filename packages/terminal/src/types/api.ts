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
  time: number;
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
