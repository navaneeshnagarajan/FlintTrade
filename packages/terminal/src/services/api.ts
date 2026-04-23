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
  ModifyOrderParams,
  OrderStatusParams,
  OpenPositionParams,
  BasketOrderParams,
  SplitOrderParams,
  OptionsOrderParams,
  OptionsMultiOrderParams,
  OptionGreeksParams,
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
export const cancelOrder = (orderId: string, strategy = "Flint") =>
  postOrder<void>("cancelorder", { orderId, strategy });
export const closePosition = (strategy = "Flint") =>
  postOrder<void>("close-position", { strategy });
export const modifyOrder = (params: ModifyOrderParams) =>
  post<{ orderId: string }>("modifyorder", params);
export const orderStatus = (params: OrderStatusParams) =>
  post<{ status: string }>("orderstatus", params);
export const openPosition = (params: OpenPositionParams) =>
  postOrder<{ orderId: string }>("openposition", params);
export const basketOrder = (params: BasketOrderParams) =>
  postOrder<{ orderId: string }>("basketorder", params);
export const optionsOrder = (params: OptionsOrderParams) =>
  postOrder<{ orderId: string }>("optionsorder", params);
export const optionsMultiOrder = (params: OptionsMultiOrderParams) =>
  postOrder<{ orderId: string }>("optionsmultiorder", params);
export const splitOrder = (params: SplitOrderParams) =>
  postOrder<{ orderId: string }>("splitorder", params);

// --- Data ---

/**
 * Shape returned by the OpenAlgo /multiquotes endpoint.
 * Each element is a per-symbol wrapper containing the quote payload under `data`.
 */
export interface MultiQuoteResult {
  symbol: string;
  exchange: string;
  data: Quote;
}

export const getQuotes = (symbol: string, exchange = "NSE") =>
  post<Quote>("quotes", { symbol, exchange });

/**
 * Fetch quotes for multiple symbols in one request.
 *
 * OpenAlgo returns `{ results: MultiQuoteResult[], status }` which the `post<T>`
 * helper unwraps to `{ results: MultiQuoteResult[] }`.  Some broker adapters may
 * return a flat `Quote[]` directly — the union type covers both shapes.
 * Callers should check `Array.isArray(result)` vs `"results" in result`,
 * or use `normaliseMultiQuotes()` to get a flat `Quote[]` in one step.
 */
export const getMultiQuotes = (symbols: Array<{ symbol: string; exchange: string }>) =>
  post<{ results: MultiQuoteResult[] } | MultiQuoteResult[]>("multiquotes", { symbols });

/**
 * Normalise the `getMultiQuotes` response into a flat `Quote[]`.
 *
 * Handles both shapes returned by different OpenAlgo broker adapters:
 *  - `{ results: [{ symbol, exchange, data: Quote }, ...] }` — standard v2 shape
 *  - `MultiQuoteResult[]` — flat array of wrapper objects
 *  - `Quote[]` — some adapters return flat quotes directly (no `data` wrapper)
 *
 * The returned quotes always have `symbol` and `exchange` fields set.
 */
export function normaliseMultiQuotes(
  raw: { results: MultiQuoteResult[] } | MultiQuoteResult[],
): Quote[] {
  const items: MultiQuoteResult[] = Array.isArray(raw) ? raw : raw.results ?? [];
  return items.map((item) => {
    // Standard shape: item.data is the Quote payload
    if (item.data && typeof item.data === "object") {
      return { ...item.data, symbol: item.symbol, exchange: item.exchange };
    }
    // Flat shape: the item itself is the Quote (broker adapter omits the `data` wrapper)
    return item as unknown as Quote;
  });
}
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
export const getHolidays = () => post<Holiday[]>("holidays"); // POST with apikey, not GET
export const getTimings = () => post<MarketTiming[]>("timings"); // POST with apikey, not GET
export const sendTelegram = (message: string) =>
  post<{ message: string }>("telegram", { message });

// --- Broker Management (OpenAlgo 2.0.0.2) ---
// NOTE: These endpoints are session-authenticated (not API key), and live
// outside /api/v1/. In dev mode the Vite proxy forwards them to OpenAlgo.
// In production, use the full OpenAlgo host.
export const getBrokerCapabilities = () =>
  get<BrokerCapabilities>("../broker/capabilities"); // actual path: /api/broker/capabilities
export const getLeverageSettings = () =>
  get<LeverageSettings>("../../leverage/api/current"); // actual path: /leverage/api/current

// --- Chart Preferences (OpenAlgo) ---
export const getChartPreferences = () => get<object>("chart");
export const updateChartPreferences = (prefs: object) => post<object>("chart", prefs);

// --- Analytics ---
export const getOptionGreeks = (params: OptionGreeksParams) => post<Greeks>("optiongreeks", params);
export const getAnalyzerStatus = () => post<{ enabled: boolean }>("analyzer", {});
export const toggleAnalyzer = (enable: boolean) => post<{ enabled: boolean }>("analyzer/toggle", { enable });
export const getPnlSymbols = () => post<Array<{ symbol: string; exchange: string }>>("pnl/symbols", {});
