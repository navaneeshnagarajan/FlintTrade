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
  Greeks,
  GexEntry,
  IVSmileEntry,
  MaxPainData,
  OIProfileEntry,
  SyntheticFutureData,
  MarginData,
  Holiday,
  MarketTiming,
  BrokerCapabilities,
  LeverageSettings,
} from "@/types/api";
import { useConnectionStore } from "@/stores/connectionStore";
import { useModeStore } from "@/stores/modeStore";
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

/** Base URL for the FlintTrade Python backend.
 *  In dev mode the Vite proxy maps /ft-api → localhost:5100.
 *  In production the backend shares the same origin. */
function getFtBase(): string {
  if (import.meta.env.DEV) return "/ft-api";
  return "";
}

function getApiKey(): string {
  return useConnectionStore.getState().apiKey;
}

/** POST an order through the FlintTrade safety proxy.
 *
 *  The backend at order_routes.py:
 *    - Reads X-FlintTrade-Mode to enforce explore/practice/live guards
 *    - Injects the OpenAlgo API key before forwarding the request
 *
 *  The API key is therefore NOT sent from the browser here; the backend
 *  holds it securely and adds it server-side.
 */
async function postOrder<T>(ftEndpoint: string, body: object = {}): Promise<T> {
  // Apply the order rate limit (10/s) — identical to OpenAlgo direct calls
  if (!orderLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for ${ftEndpoint} (order: 10/s)`);
  }

  // Read the current operating mode and attach it as a header so the
  // backend safety layer can enforce practice/explore blocking.
  const mode = useModeStore.getState().mode;

  let resp: Response;
  try {
    resp = await fetch(`${getFtBase()}/api/v1/orders/${ftEndpoint}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-FlintTrade-Mode": mode,
      },
      body: JSON.stringify(body),
    });
  } catch {
    throw new Error("Connection failed. Check FlintTrade backend is running.");
  }

  if (!resp.ok) {
    const body2 = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body2?.message ?? body2?.error ?? null;
    if (resp.status === 401) {
      throw new Error("API key invalid. Check Settings → Connection.");
    }
    if (resp.status === 400) {
      throw new Error(serverMsg ?? "Invalid order parameters. Check symbol and exchange.");
    }
    if (resp.status === 403) {
      // Backend returns 403 when mode blocks the action (e.g. real order in practice mode)
      throw new Error(serverMsg ?? `Order blocked in ${mode} mode.`);
    }
    if (resp.status === 500) {
      throw new Error(serverMsg ?? "FlintTrade backend error. Try again in a few seconds.");
    }
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }

  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `Order API ${ftEndpoint} error`);
  return (json.data ?? json) as T;
}

async function post<T>(endpoint: string, extra: object = {}): Promise<T> {
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

  let resp: Response;
  try {
    resp = await fetch(`${getBase()}/api/v1/${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ apikey: getApiKey(), ...extra }),
    });
  } catch {
    throw new Error("Connection failed. Check OpenAlgo is running.");
  }

  if (!resp.ok) {
    const body = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body?.message ?? body?.error ?? null;
    if (resp.status === 401) {
      throw new Error("API key invalid. Check Settings → Connection.");
    }
    if (resp.status === 400) {
      throw new Error(serverMsg ?? "Invalid order parameters. Check symbol and exchange.");
    }
    if (resp.status === 500) {
      throw new Error(serverMsg ?? "OpenAlgo server error. Try again in a few seconds.");
    }
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }

  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

async function get<T>(endpoint: string): Promise<T> {
  if (!generalLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for GET ${endpoint}`);
  }
  let resp: Response;
  try {
    resp = await fetch(`${getBase()}/api/v1/${endpoint}`);
  } catch {
    throw new Error("Connection failed. Check OpenAlgo is running.");
  }
  if (!resp.ok) {
    const body = await resp.json().catch(() => null) as { message?: string; error?: string } | null;
    const serverMsg = body?.message ?? body?.error ?? null;
    if (resp.status === 401) throw new Error("API key invalid. Check Settings → Connection.");
    if (resp.status === 500) throw new Error(serverMsg ?? "OpenAlgo server error. Try again in a few seconds.");
    throw new Error(serverMsg ?? `Server error (${resp.status})`);
  }
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return (json.data ?? json) as T;
}

// --- Orders (routed through FlintTrade safety proxy) ---
// These three functions no longer call OpenAlgo directly. Every request passes
// through order_routes.py in the FlintTrade backend, which:
//   1. Reads X-FlintTrade-Mode and blocks real orders in explore/practice mode
//   2. Injects the OpenAlgo API key before forwarding to OpenAlgo
// The API key is therefore never sent from the browser for order endpoints.
export const placeOrder = (params: PlaceOrderParams) =>
  postOrder<{ orderId: string }>("place", params);
export const placeSmartOrder = (params: PlaceOrderParams & { position_size: number }) =>
  postOrder<{ orderId: string }>("place-smart", params);
export const cancelAllOrders = (strategy = "Flint") =>
  postOrder<void>("cancel-all", { strategy });
export const closePosition = (strategy = "Flint") =>
  postOrder<void>("close-position", { strategy });

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
export const getHolidays = () => get<Holiday[]>("holidays");
export const getTimings = () => get<MarketTiming[]>("timings");
export const sendTelegram = (message: string) =>
  post<{ message: string }>("telegram", { message });

// --- Broker Management (OpenAlgo 2.0.0.2) ---
export const getBrokerCapabilities = () =>
  get<BrokerCapabilities>("broker/capabilities");
export const getLeverageSettings = () =>
  get<LeverageSettings>("broker/leverage");
