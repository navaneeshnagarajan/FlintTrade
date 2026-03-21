/**
 * OpenAlgo REST API client (TypeScript).
 * Host & API key sourced from connectionStore (Zustand).
 * All responses are unwrapped: { data: X, status: "success" } → X
 */

import type {
  Position,
  Order,
  Trade,
  Holding,
  Funds,
  Quote,
  MarketDepth,
  OHLCVBar,
  OptionChainData,
  PlaceOrderParams,
  SmartOrderParams,
  Greeks,
  GexEntry,
  IVSmileEntry,
  MaxPainData,
  OIProfileEntry,
  SyntheticFutureData,
  MarginData,
  Holiday,
  MarketTiming,
} from "@/types/api";
import { useConnectionStore } from "@/stores/connectionStore";
import { orderLimiter, smartOrderLimiter, generalLimiter } from "@/services/rateLimiter";

// Endpoints subject to the 10/s order rate limit (excludes placesmartorder which has its own)
const ORDER_ENDPOINTS = new Set([
  "placeorder",
  "modifyorder",
  "cancelorder",
  "cancelallorder",
  "closeposition",
  "openposition",
  "optionsorder",
  "optionsmultiorder",
  "basketorder",
  "splitorder",
]);

// Endpoints subject to the 2/s smart-order rate limit
const SMART_ORDER_ENDPOINTS = new Set(["placesmartorder"]);

function getBase(): string {
  // In dev mode, Vite proxy handles routing to OpenAlgo — use relative paths
  // In production, use the full host from connectionStore
  if (import.meta.env.DEV) return "";
  return useConnectionStore.getState().host;
}

function getApiKey(): string {
  return useConnectionStore.getState().apiKey;
}

async function post<T>(endpoint: string, extra: Record<string, unknown> = {}): Promise<T> {
  // Enforce rate limits before making the request
  if (SMART_ORDER_ENDPOINTS.has(endpoint)) {
    if (!smartOrderLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (smart order: 2/s)`);
    }
  } else if (ORDER_ENDPOINTS.has(endpoint)) {
    if (!orderLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (order: 10/s)`);
    }
  } else {
    if (!generalLimiter.tryConsume()) {
      throw new Error(`Rate limit exceeded for ${endpoint} (general: 50/s)`);
    }
  }

  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apikey: getApiKey(), ...extra }),
  });
  if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

async function get<T>(endpoint: string): Promise<T> {
  if (!generalLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for GET ${endpoint}`);
  }
  const resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

// --- Orders ---
export const placeOrder = (params: PlaceOrderParams) =>
  post<{ orderId: string }>("placeorder", params as unknown as Record<string, unknown>);
export const placeSmartOrder = (params: SmartOrderParams) =>
  post<{ orderId: string }>("placesmartorder", params as unknown as Record<string, unknown>);
export const cancelOrder = (strategy: string, orderid: string) =>
  post<void>("cancelorder", { strategy, orderid });
export const cancelAllOrders = (strategy = "Flint") =>
  post<void>("cancelallorder", { strategy });
export const closePosition = (strategy = "Flint") =>
  post<void>("closeposition", { strategy }); // BUG FIX 2: passes strategy string, was passing { product: "MIS" }
export const modifyOrder = (params: Record<string, unknown>) =>
  post<void>("modifyorder", params);
export const orderStatus = (strategy: string, orderid: string) =>
  post<Order>("orderstatus", { strategy, orderid });
export const openPosition = (params: PlaceOrderParams) =>
  post<Record<string, unknown>>("openposition", params as unknown as Record<string, unknown>);

// --- Data ---
export const getQuotes = (symbol: string, exchange = "NSE") =>
  post<Quote>("quotes", { symbol, exchange });
export const getMultiQuotes = (symbols: Array<{ symbol: string; exchange: string }>) =>
  post<Quote[]>("multiquotes", { symbols });
export const getDepth = (symbol: string, exchange = "NSE") =>
  post<MarketDepth>("depth", { symbol, exchange });
export const getHistory = (
  symbol: string,
  exchange: string,
  interval: string,
  start_date: string,
  end_date: string,
) => post<OHLCVBar[]>("history", { symbol, exchange, interval, start_date, end_date });
export const getOptionChain = (symbol: string, exchange = "NFO", expiry?: string) =>
  post<OptionChainData>("optionchain", {
    underlying: symbol, // OpenAlgo v2 uses 'underlying' not 'symbol'
    exchange,
    // OpenAlgo expiry format: "24MAR26" (no dashes). Expiry API returns "24-MAR-26".
    ...(expiry ? { expiry_date: expiry.replace(/-/g, "") } : {}),
  });
export const getOptionGreeks = (symbol: string, exchange = "NFO") =>
  post<Greeks>("optiongreeks", { symbol, exchange });
export const getExpiry = (
  symbol: string,
  exchange = "NFO",
  instrumenttype: "options" | "futures" = "options",
) => post<{ expiry: string[] }>("expiry", { symbol, exchange, instrumenttype });
export function searchSymbol(query: string): Promise<Array<{ symbol: string; exchange: string }>> {
  // Sanitize: strip characters that are not word chars, spaces, hyphens, or dots
  const sanitized = query.replace(/[^\w\s\-.]/g, "").slice(0, 50).trim();
  if (!sanitized) {
    throw new Error("Search query is empty after sanitization");
  }
  return post<Array<{ symbol: string; exchange: string }>>("search", { query: sanitized });
}
export const getIntervals = () => get<string[]>("intervals");
export const getMultiOptionGreeks = (symbols: Array<{ symbol: string; exchange: string }>) =>
  post<Greeks[]>("multioptiongreeks", { symbols });
export const getOptionSymbol = (
  underlying: string,
  exchange: string,
  expiry_date: string,
  option_type: string,
  offset: string,
) => post<{ symbol: string; exchange: string }>("optionsymbol", { underlying, exchange, expiry_date, option_type, offset });
export const getSymbol = (symbol: string, exchange: string) =>
  post<{ symbol: string; name: string; exchange: string; instrumenttype: string; lotsize: number; tick_size: number }>("symbol", { symbol, exchange });
export const getSyntheticFuture = (symbol: string, exchange: string, expiry_date?: string) =>
  post<SyntheticFutureData>("syntheticfuture", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });
export const getTicker = (symbol: string, exchange: string) =>
  post<Quote>("ticker", { symbol, exchange });
export const getInstruments = () => get<Array<{ symbol: string; name: string; exchange: string; instrumenttype: string; lotsize: number; tick_size: number; token: string }>>("instruments");
export const getGex = (symbol: string, exchange: string, expiry_date?: string) =>
  post<GexEntry[]>("gex", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });
export const getIVSmile = (symbol: string, exchange: string, expiry_date?: string) =>
  post<IVSmileEntry[]>("iv_smile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });
export const getMaxPain = (symbol: string, exchange: string, expiry_date?: string) =>
  post<MaxPainData>("max_pain", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });
export const getOIProfile = (symbol: string, exchange: string, expiry_date?: string) =>
  post<OIProfileEntry[]>("oi_profile", { symbol, exchange, ...(expiry_date ? { expiry_date } : {}) });

// --- Account ---
export const getFunds = () => post<Funds>("funds");
export const getMargin = (symbol: string, exchange: string, qty: number, product: string, action: string) =>
  post<MarginData>("margin", { symbol, exchange, qty, product, action });

// OpenAlgo wraps list responses: { data: { orders: [...], statistics: {...} } }
// post() unwraps json.data, so we receive { orders: [...], statistics: {...} }.
// We extract the nested array and fall back to the raw value for brokers that
// return a plain array (future-proofing / broker inconsistency).
export const getOrderbook = async (): Promise<Order[]> => {
  const raw = await post<Order[] | { orders?: Order[] }>("orderbook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.orders) ? raw.orders : [];
};

export const getTradebook = async (): Promise<Trade[]> => {
  const raw = await post<Trade[] | { trades?: Trade[] }>("tradebook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.trades) ? raw.trades : [];
};

export const getPositionbook = async (): Promise<Position[]> => {
  const raw = await post<Position[] | { positions?: Position[] }>("positionbook");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.positions) ? raw.positions : [];
};

export const getHoldings = async (): Promise<Holding[]> => {
  const raw = await post<Holding[] | { holdings?: Holding[] }>("holdings");
  if (Array.isArray(raw)) return raw;
  return Array.isArray(raw.holdings) ? raw.holdings : [];
};

// --- Utility ---
export const ping = () => post<{ status: string }>("ping"); // OpenAlgo docs: POST /api/v1/ping
export const analyzerStatus = () => get<{ enabled: boolean }>("analyzer/status");
export const analyzerToggle = () => post<void>("analyzer/toggle");
export const getHolidays = () => get<Holiday[]>("holidays");
export const getTimings = () => get<MarketTiming[]>("timings");
export const sendTelegram = (message: string) =>
  post<{ message: string }>("telegram", { message });
