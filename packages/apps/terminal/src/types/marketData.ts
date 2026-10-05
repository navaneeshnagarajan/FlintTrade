/** Display models built by services/api.ts from native broker-read snapshots. */
export interface InstrumentIdentity { symbol: string; exchange: string }
export interface SessionPrices { open: number; high: number; low: number; close: number; volume: number }
export interface Quote extends InstrumentIdentity, SessionPrices {
  ltp: number; change?: number; pct?: number; prev_close?: number;
}
export interface OHLCVBar extends SessionPrices { timestamp: number }
export interface DepthLevel { price: number; quantity: number; orders: number }
export interface MarketDepth { buy: DepthLevel[]; sell: DepthLevel[] }

/** A partial quote notification published by the native polling registry. */
export interface WsTick extends InstrumentIdentity, Partial<SessionPrices> {
  ltp: number; change?: number; pct?: number;
  /** Session reference used for percentage change; never a replacement LTP. */
  prevClose?: number;
}
export type WsInstrument = InstrumentIdentity;
export type WsMode = "ltp" | "quote" | "depth";

/** Native option-chain normalisation uses separate call/put values per strike. */
export interface OptionChainStrike {
  strikePrice: number;
  ceSymbol: string; ceLtp: number; ceOi: number; ceVolume: number; ceIv: number;
  peSymbol: string; peLtp: number; peOi: number; peVolume: number; peIv: number;
  ceDelta?: number; ceGamma?: number; ceTheta?: number; ceVega?: number;
  peDelta?: number; peGamma?: number; peTheta?: number; peVega?: number;
}
export interface OptionChainData { symbol: string; expiry: string; spotPrice: number; strikes: OptionChainStrike[] }
export interface Greeks {
  delta: number; gamma: number; theta: number; vega: number; iv: number;
  symbol?: string; exchange?: string; instrument_id?: string;
}
export interface OptionGreeksParams extends InstrumentIdentity { expiry?: string; strike?: number; optionType?: "CE" | "PE" }

/** Native calendar endpoints encode session boundaries as epoch seconds. */
export interface MarketTiming { exchange: string; start_time: number; end_time: number }
export interface Holiday { date: string; description: string; holiday_type: string; closed_exchanges: string[]; open_exchanges: MarketTiming[] }
export interface BrokerCapabilities {
  broker_name: string;
  broker_type: "equity" | "crypto" | "commodity" | "multi";
  supported_exchanges: string[];
  features: { market_protection: boolean; leverage: boolean; bracket_orders: boolean; cover_orders: boolean; [feature: string]: boolean };
}
export interface LeverageSettings {
  leverage?: number; max_leverage?: number; margin_mode?: string;
  available?: number; used?: number; total?: number; leverage_ratio?: number;
  [field: string]: unknown;
}
export interface MarginData { total_margin_required: number; span_margin: number; exposure_margin: number }
