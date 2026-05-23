// ---------------------------------------------------------------------------
// OptionChain — shared types
// ---------------------------------------------------------------------------

export interface SymbolDef {
  label: string;
  exchange: string;
  spotSymbol: string;
  spotExchange: string;
}

export interface SymbolSearchResult {
  symbol: string;
  exchange: string;
}

/** Shape returned by getInstruments() */
export interface InstrumentRecord {
  symbol: string;
  name: string;
  exchange: string;
  instrumenttype: string;
  lotsize: number;
  tick_size: number;
  token: string;
}

export type ViewType = "LTP" | "OI" | "GREEKS";

/** Raw option row from OpenAlgo optionchain API */
export interface RawOptionRow {
  strike_price?: number;
  strike?: number;
  ltp?: number;
  last_price?: number;
  change?: number;
  change_percent?: number;
  change_pct?: number;
  volume?: number;
  oi?: number;
  open_interest?: number;
  oi_change?: number;
  delta?: number;
  gamma?: number;
  theta?: number;
  vega?: number;
  iv?: number;
  implied_volatility?: number;
}

/** OpenAlgo v2 chain entry: { strike, ce: {...}, pe: {...} } */
export interface ChainEntry {
  strike: number;
  ce: RawOptionRow | null;
  pe: RawOptionRow | null;
}

/** OpenAlgo optionchain raw API shape (v2 format) */
export interface RawOptionChain {
  chain?: ChainEntry[];
  atm_strike?: number;
  underlying_ltp?: number;
  underlying_prev_close?: number;
  pcr?: number;
  // Legacy v1 format (kept for backwards compat)
  calls?: RawOptionRow[];
  puts?: RawOptionRow[];
}

export interface StrikeRow {
  strike: number;
  call: RawOptionRow | null;
  put: RawOptionRow | null;
}

export interface OrderToast {
  text: string;
  ok: boolean;
}

export interface OrderParams {
  symbol: string;
  exchange: string;
  strike: number;
  optionType: string;
  expiry: string;
  action: string;
  ltp: number | null;
}

/** OI interpretation badge type — from OiPulse patterns */
export type OISignal =
  | "Long Build Up"   // price up + OI up   → bullish
  | "Short Covering"  // price up + OI down  → short squeeze
  | "Long Unwinding"  // price down + OI down → bulls exiting
  | "Short Build Up"  // price down + OI up  → bearish
  | null;

export interface BasketItem {
  strike: number;
  optionType: "CE" | "PE";
  ltp: number | null;
  expiry: string;
}

/** Exchanges that have option chains */
export const OPTION_CHAIN_EXCHANGES = new Set(["NFO", "BFO", "MCX", "CDS"]);

export const SYMBOLS: SymbolDef[] = [
  // NSE Index Options (NFO)
  { label: "NIFTY",       exchange: "NFO", spotSymbol: "NIFTY",       spotExchange: "NSE_INDEX" },
  { label: "BANKNIFTY",   exchange: "NFO", spotSymbol: "BANKNIFTY",   spotExchange: "NSE_INDEX" },
  { label: "FINNIFTY",    exchange: "NFO", spotSymbol: "FINNIFTY",    spotExchange: "NSE_INDEX" },
  { label: "MIDCPNIFTY",  exchange: "NFO", spotSymbol: "MIDCPNIFTY",  spotExchange: "NSE_INDEX" },
  { label: "NIFTYNXT50",  exchange: "NFO", spotSymbol: "NIFTYNXT50",  spotExchange: "NSE_INDEX" },
  // BSE Index Options (BFO)
  { label: "SENSEX",      exchange: "BFO", spotSymbol: "SENSEX",      spotExchange: "BSE_INDEX" },
  { label: "BANKEX",      exchange: "BFO", spotSymbol: "BANKEX",      spotExchange: "BSE_INDEX" },
  // MCX Commodity Options
  { label: "GOLD",        exchange: "MCX", spotSymbol: "GOLD",        spotExchange: "MCX" },
  { label: "SILVER",      exchange: "MCX", spotSymbol: "SILVER",      spotExchange: "MCX" },
  { label: "CRUDEOIL",    exchange: "MCX", spotSymbol: "CRUDEOIL",    spotExchange: "MCX" },
  { label: "NATURALGAS",  exchange: "MCX", spotSymbol: "NATURALGAS",  spotExchange: "MCX" },
  { label: "COPPER",      exchange: "MCX", spotSymbol: "COPPER",      spotExchange: "MCX" },
  { label: "ZINC",        exchange: "MCX", spotSymbol: "ZINC",        spotExchange: "MCX" },
  { label: "LEAD",        exchange: "MCX", spotSymbol: "LEAD",        spotExchange: "MCX" },
  { label: "NICKEL",      exchange: "MCX", spotSymbol: "NICKEL",      spotExchange: "MCX" },
  { label: "ALUMINIUM",   exchange: "MCX", spotSymbol: "ALUMINIUM",   spotExchange: "MCX" },
  { label: "MENTHAOIL",   exchange: "MCX", spotSymbol: "MENTHAOIL",   spotExchange: "MCX" },
  { label: "COTTON",      exchange: "MCX", spotSymbol: "COTTON",      spotExchange: "MCX" },
  // Currency Options (CDS)
  { label: "USDINR",      exchange: "CDS", spotSymbol: "USDINR",      spotExchange: "CDS" },
  { label: "EURINR",      exchange: "CDS", spotSymbol: "EURINR",      spotExchange: "CDS" },
  { label: "GBPINR",      exchange: "CDS", spotSymbol: "GBPINR",      spotExchange: "CDS" },
  { label: "JPYINR",      exchange: "CDS", spotSymbol: "JPYINR",      spotExchange: "CDS" },
];

export const EXCHANGES = ["NFO", "BFO", "MCX", "CDS"];
export const VIEWS: ViewType[] = ["LTP", "OI", "GREEKS"];
export const STRIKES_AROUND_ATM = 10;
