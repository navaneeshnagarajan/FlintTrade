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
} from "@/types/api";
import { useConnectionStore } from "@/stores/connectionStore";

function getBase(): string {
  return useConnectionStore.getState().host;
}

function getApiKey(): string {
  return useConnectionStore.getState().apiKey;
}

async function post<T>(endpoint: string, extra: Record<string, unknown> = {}): Promise<T> {
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
  post<OptionChainData>("optionchain", { symbol, exchange, ...(expiry ? { expiry } : {}) }); // BUG FIX 3: includes expiry parameter
export const getOptionGreeks = (symbol: string, exchange = "NFO") =>
  post<Greeks>("optiongreeks", { symbol, exchange });
export const getExpiry = (symbol: string, exchange = "NFO") =>
  post<{ expiry: string[] }>("expiry", { symbol, exchange });
export const searchSymbol = (query: string) =>
  post<Array<{ symbol: string; exchange: string }>>("search", { query });
export const getIntervals = () => get<string[]>("intervals");

// --- Account ---
export const getFunds = () => post<Funds>("funds");
export const getOrderbook = () => post<Order[]>("orderbook");
export const getTradebook = () => post<Trade[]>("tradebook");
export const getPositionbook = () => post<Position[]>("positionbook");
export const getHoldings = () => post<Holding[]>("holdings");

// --- Utility ---
export const ping = () => get<{ status: string }>("ping"); // BUG FIX 1: was POST, OpenAlgo docs specify GET
export const analyzerStatus = () => get<{ enabled: boolean }>("analyzer/status");
export const analyzerToggle = () => post<void>("analyzer/toggle");
