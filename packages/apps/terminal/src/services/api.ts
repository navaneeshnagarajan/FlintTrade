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
import { useAuthStore } from "@/stores/authStore";
import { orderLimiter, smartOrderLimiter, generalLimiter } from "@/services/rateLimiter";
import { mockDataEngine } from "@/services/mockDataEngine";

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

function isExploreModeWithoutKey(): boolean {
  return useModeStore.getState().mode === "explore" && getApiKey().trim().length === 0;
}

function requireApiKey(endpoint: string): void {
  if (getApiKey().trim().length > 0) return;
  throw new Error(`OpenAlgo API key is not configured for ${endpoint}. Check Settings -> Connection.`);
}

function findMockQuote(symbol = "NIFTY", exchange = "NSE_INDEX"): Quote {
  const snapshot = mockDataEngine.getSnapshot();
  const match = snapshot.find((tick) => (
    tick.symbol === symbol || `${tick.exchange}:${tick.symbol}` === symbol
  )) ?? snapshot.find((tick) => tick.exchange === exchange) ?? snapshot[0];

  return {
    symbol: match?.symbol ?? symbol,
    exchange: match?.exchange ?? exchange,
    ltp: match?.ltp ?? 0,
    open: match?.open ?? 0,
    high: match?.high ?? 0,
    low: match?.low ?? 0,
    close: match?.close ?? 0,
    prev_close: match?.close ?? 0,
    volume: match?.volume ?? 0,
    change: match?.change ?? 0,
    pct: match?.changePct ?? 0,
  };
}

function makeMockHistory(symbol?: string, exchange?: string): OHLCVBar[] {
  const quote = findMockQuote(symbol, exchange);
  const now = Math.floor(Date.now() / 1000);
  return Array.from({ length: 96 }, (_, index) => {
    const drift = Math.sin(index / 6) * quote.ltp * 0.002;
    const open = quote.ltp + drift;
    const close = open + Math.cos(index / 5) * quote.ltp * 0.0015;
    return {
      timestamp: now - (95 - index) * 300,
      open,
      high: Math.max(open, close) + quote.ltp * 0.001,
      low: Math.min(open, close) - quote.ltp * 0.001,
      close,
      volume: Math.max(1, Math.round(quote.volume / 100 + index * 37)),
    };
  });
}

function mockOrders(): Order[] {
  return mockDataEngine.getMockOrders().map((order) => ({
    orderId: order.orderId,
    symbol: order.symbol,
    exchange: order.exchange,
    action: order.side,
    quantity: order.quantity,
    price: order.price,
    orderType: order.orderType,
    status: order.status,
    product: order.product,
    strategy: "Explore",
    timestamp: order.timestamp,
  }));
}

function mockPositions(): Position[] {
  return mockDataEngine.getMockPositions().map((position) => ({
    symbol: position.symbol,
    exchange: position.exchange,
    product: position.product,
    quantity: position.quantity,
    averagePrice: position.avgPrice,
    ltp: position.ltp,
    pnl: position.pnl,
    pnlPercent: position.avgPrice > 0 ? (position.pnl / (position.avgPrice * position.quantity)) * 100 : 0,
  }));
}

function mockHoldings(): Holding[] {
  return mockDataEngine.getMockHoldings().map((holding) => ({
    symbol: holding.symbol,
    exchange: holding.exchange,
    quantity: holding.quantity,
    averagePrice: holding.avgPrice,
    ltp: holding.ltp,
    pnl: holding.pnl,
    pnlPercent: holding.pnlPct,
  }));
}

function getExplorePostFallback<T>(endpoint: string, extra: object): T | undefined {
  const params = extra as Record<string, unknown>;
  const symbol = typeof params.symbol === "string" ? params.symbol : undefined;
  const exchange = typeof params.exchange === "string" ? params.exchange : undefined;

  switch (endpoint) {
    case "ping":
      return { status: "explore" } as T;
    case "quotes":
    case "ticker":
      return findMockQuote(symbol, exchange) as T;
    case "multiquotes": {
      const symbols = Array.isArray(params.symbols)
        ? params.symbols as Array<{ symbol?: string; exchange?: string }>
        : [];
      const results = symbols.map((item) => ({
        symbol: item.symbol ?? "NIFTY",
        exchange: item.exchange ?? "NSE_INDEX",
        data: findMockQuote(item.symbol, item.exchange),
      }));
      return { results } as T;
    }
    case "history":
      return makeMockHistory(symbol, exchange) as T;
    case "symbol":
      return {
        symbol: symbol ?? "NIFTY",
        name: symbol ?? "NIFTY",
        exchange: exchange ?? "NSE_INDEX",
        instrumenttype: "INDEX",
        lotsize: 1,
        tick_size: 0.05,
      } as T;
    case "funds":
      return {
        availableCash: 250_000,
        usedMargin: 48_500,
        totalBalance: 298_500,
      } as T;
    case "margin":
      return {
        total_margin_required: 0,
        span_margin: 0,
        exposure_margin: 0,
      } as T;
    case "orderbook":
      return { orders: mockOrders() } as T;
    case "positionbook":
      return { positions: mockPositions() } as T;
    case "holdings":
      return { holdings: mockHoldings() } as T;
    case "holidays":
      return [] as T;
    case "timings":
      return [
        { exchange: "NSE", start_time: 915, end_time: 1530 },
        { exchange: "BSE", start_time: 915, end_time: 1530 },
        { exchange: "MCX", start_time: 900, end_time: 2330 },
      ] as T;
    default:
      return undefined;
  }
}

function getExploreGetFallback<T>(endpoint: string): T | undefined {
  switch (endpoint) {
    case "intervals":
      return ["1m", "3m", "5m", "15m", "30m", "1h", "4h", "1D", "1W"] as T;
    case "../broker/capabilities":
      return {
        broker_name: "Explore",
        broker_type: "multi",
        supported_exchanges: ["NSE", "BSE", "NFO", "BFO", "MCX"],
        features: {
          market_protection: false,
          leverage: false,
          bracket_orders: false,
          cover_orders: false,
        },
      } as T;
    default:
      return undefined;
  }
}

/** POST an order through the FlintTrade safety proxy.
 *
 *  The backend at order_routes.py:
 *    - Validates `X-API-Key` against OPENALGO_API_KEY (via require_auth).
 *    - Reads `X-FlintTrade-Mode` to enforce explore / practice / live gates.
 *    - For live-mode orders, additionally requires
 *      `Authorization: Bearer <jwt>` with the `live_mode_unlocked` claim.
 *
 *  Headers we attach:
 *    - `Content-Type: application/json`
 *    - `X-FlintTrade-Mode: <explore|practice|live>`
 *    - `X-API-Key: <connectionStore.apiKey>`  (gates the auth middleware)
 *    - `Authorization: Bearer <authStore.token>` when a session token is
 *      available; the backend ignores it in explore/practice mode and
 *      checks the `live_mode_unlocked` claim before letting a real order
 *      reach OpenAlgo.
 *
 *  Pre-2026-05-19 this function only sent `Content-Type` and
 *  `X-FlintTrade-Mode`. Codex stop-gate review (task-mpcpfmws-5rokaa)
 *  flagged that every real terminal order placement would 401 against
 *  the require_auth middleware, even though the backend tests passed
 *  because they fabricated `X-API-Key` and `Authorization` in the test
 *  client.
 */
async function postOrder<T>(ftEndpoint: string, body: object = {}): Promise<T> {
  // Apply the order rate limit (10/s) — identical to OpenAlgo direct calls
  if (!orderLimiter.tryConsume()) {
    throw new Error(`Rate limit exceeded for ${ftEndpoint} (order: 10/s)`);
  }

  // Read the current operating mode and auth state to assemble headers.
  const mode = useModeStore.getState().mode;
  const apiKey = useConnectionStore.getState().apiKey;
  const jwt = useAuthStore.getState().token;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "X-FlintTrade-Mode": mode,
  };
  if (apiKey) headers["X-API-Key"] = apiKey;
  if (jwt) headers["Authorization"] = `Bearer ${jwt}`;

  let resp: Response;
  try {
    resp = await fetch(`${getFtBase()}/api/v1/orders/${ftEndpoint}`, {
      method: "POST",
      headers,
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

  if (isExploreModeWithoutKey()) {
    const fallback = getExplorePostFallback<T>(endpoint, extra);
    if (fallback !== undefined) return fallback;
    requireApiKey(endpoint);
  } else {
    requireApiKey(endpoint);
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

  if (isExploreModeWithoutKey()) {
    const fallback = getExploreGetFallback<T>(endpoint);
    if (fallback !== undefined) return fallback;
    requireApiKey(endpoint);
  } else {
    requireApiKey(endpoint);
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
//
// The leaf names below MUST match the backend route registrations:
//
//   core   orders_bp at /api/v1/orders : place, place-smart, modify, cancel,
//                                        cancel-all, close-position,
//                                        open-position, options, options-multi
//   engine order_bp  at /api/v1/orders : basket, split, options-strategy
//
// Pre-2026-05-19 this file mixed FT-proxy names (place, place-smart,
// cancel-all, close-position) with OpenAlgo-style names (cancelorder,
// openposition, basketorder, splitorder, optionsorder, optionsmultiorder),
// so half the order endpoints 404'd in production. Codex stop-gate review
// caught the mismatch on 2026-05-19 (task-mpcpfmws-5rokaa). A follow-up
// review then flagged that `optionsOrder` / `optionsMultiOrder` had been
// routed through `post()` (OpenAlgo direct) as a stopgap, bypassing the
// FT mode/safety gate. Both endpoints are now backed by /options and
// /options-multi handlers in core orders_bp that delegate to OpenAlgo's
// `optionsorder` and `optionsmultiorder` through `_dispatch_order`, so
// every options trade is mode-gated identically to a regular order.
//
// `orderStatus` stays on the OpenAlgo direct path (read-only, no mode
// gating needed for reads).
export const placeOrder = (params: PlaceOrderParams) =>
  postOrder<{ orderId: string }>("place", params);
export const placeSmartOrder = (params: PlaceOrderParams & { position_size: number }) =>
  postOrder<{ orderId: string }>("place-smart", params);
export const cancelAllOrders = (strategy = "Flint") =>
  postOrder<void>("cancel-all", { strategy });
export const cancelOrder = (orderId: string, strategy = "Flint") =>
  postOrder<void>("cancel", { orderId, strategy });
export const closePosition = (strategy = "Flint") =>
  postOrder<void>("close-position", { strategy });
export const modifyOrder = (params: ModifyOrderParams) =>
  postOrder<{ orderId: string }>("modify", params);
/** orderStatus is a READ-only endpoint, intentionally routed through OpenAlgo
 *  direct rather than the safety proxy (no mode gating needed for reads). */
export const orderStatus = (params: OrderStatusParams) =>
  post<{ status: string }>("orderstatus", params);
export const openPosition = (params: OpenPositionParams) =>
  postOrder<{ orderId: string }>("open-position", params);
export const basketOrder = (params: BasketOrderParams) =>
  postOrder<{ orderId: string }>("basket", params);
export const optionsOrder = (params: OptionsOrderParams) =>
  postOrder<{ orderId: string }>("options", params);
export const optionsMultiOrder = (params: OptionsMultiOrderParams) =>
  postOrder<{ orderId: string }>("options-multi", params);
export const splitOrder = (params: SplitOrderParams) =>
  postOrder<{ orderId: string }>("split", params);

// --- GTT (Good Till Triggered) ---
//
// Mirrors the OpenAlgo v2.0.0.9 GTT surface. All four endpoints are routed
// through the FlintTrade safety proxy (`postOrder`) so live triggers honour
// the mode gate and live_mode_unlocked JWT claim. Upstream supports Dhan
// and Zerodha live; other brokers return a clean 501 that surfaces here as
// a postOrder error.

export interface PlaceGttParams {
  /** Trigger type — SINGLE for one-leg, OCO for stoploss + target. */
  trigger_type: "SINGLE" | "OCO";
  symbol: string;
  exchange: string;
  action: "BUY" | "SELL";
  /** GTT product is restricted to CNC or NRML — MIS is rejected by upstream. */
  product: "CNC" | "NRML";
  quantity: number;
  pricetype?: "LIMIT" | "MARKET";
  price: number;
  /** Stoploss-leg trigger price (SINGLE-SL or OCO). */
  triggerprice_sl?: number;
  /** Target-leg trigger price (SINGLE-TG or OCO). */
  triggerprice_tg?: number;
  /** Stoploss limit price — OCO only. */
  stoploss?: number;
  /** Target limit price — OCO only. */
  target?: number;
  /** Optional ISO timestamp at which the trigger auto-expires. */
  expires_at?: string;
  strategy?: string;
}

export interface ModifyGttParams extends PlaceGttParams {
  trigger_id: string;
}

export interface CancelGttParams {
  trigger_id: string;
  strategy?: string;
}

export interface GttTrigger {
  trigger_id: string;
  status: string;
  trigger_type: string;
  symbol: string;
  exchange: string;
  action: string;
  quantity: string;
  product: string;
  price: string;
  triggerprice_sl: string;
  triggerprice_tg: string;
  stoploss: string;
  target: string;
  created_at: string;
  expires_at: string;
}

export const placeGtt = (params: PlaceGttParams) =>
  postOrder<{ orderId: string; trigger_id?: string }>("gtt-place", params);

export const modifyGtt = (params: ModifyGttParams) =>
  postOrder<{ orderId: string; trigger_id?: string }>("gtt-modify", params);

export const cancelGtt = (params: CancelGttParams) =>
  postOrder<{ orderId: string; trigger_id?: string }>("gtt-cancel", params);

export const getGttOrderbook = () =>
  // Read-only — go via OpenAlgo direct to avoid the safety-proxy overhead.
  post<GttTrigger[]>("gttorderbook", {});

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
export function searchSymbol(
  query: string,
  exchange?: string,
): Promise<Array<{ symbol: string; exchange: string }>> {
  // Sanitize: strip characters that are not word chars, spaces, hyphens, or dots
  const sanitized = query.replace(/[^\w\s\-.]/g, "").slice(0, 50).trim();
  if (!sanitized) {
    throw new Error("Search query is empty after sanitization");
  }
  const body: Record<string, string> = { query: sanitized };
  if (exchange) body.exchange = exchange;
  return post<Array<{ symbol: string; exchange: string }>>("search", body);
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
