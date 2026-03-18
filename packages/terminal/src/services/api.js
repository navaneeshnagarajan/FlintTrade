/**
 * OpenAlgo REST API client.
 * Base URL from VITE_OPENALGO_HOST, API key from VITE_OPENALGO_API_KEY.
 * All responses are unwrapped: { data: X, status: "success" } → X
 */

const BASE = import.meta.env.DEV ? "" : (import.meta.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000");
const API_KEY = import.meta.env.VITE_OPENALGO_API_KEY || "";

async function post(endpoint, extra = {}) {
  const resp = await fetch(`${BASE}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apikey: API_KEY, ...extra }),
  });
  if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return json.data ?? json;
}

async function get(endpoint) {
  const resp = await fetch(`${BASE}/api/v1/${endpoint}`);
  if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
  const json = await resp.json();
  if (json.status === "error") throw new Error(json.message || `API ${endpoint} error`);
  return json.data ?? json;
}

// --- Order APIs ---
export const placeOrder = (params) => post("placeorder", params);
export const placeSmartOrder = (params) => post("placesmartorder", params);
export const cancelOrder = (strategy, orderid) => post("cancelorder", { strategy, orderid });
export const cancelAllOrders = (strategy = "Flint") => post("cancelallorder", { strategy });
export const closePosition = (strategy = "Flint") => post("closeposition", { strategy });
export const modifyOrder = (params) => post("modifyorder", params);
export const orderStatus = (strategy, orderid) => post("orderstatus", { strategy, orderid });

// --- Data APIs ---
export const getQuotes = (symbol, exchange = "NSE") => post("quotes", { symbol, exchange });
export const getMultiQuotes = (symbols) => post("multiquotes", { symbols });
export const getDepth = (symbol, exchange = "NSE") => post("depth", { symbol, exchange });
export const getHistory = (symbol, exchange, interval, start_date, end_date) =>
  post("history", { symbol, exchange, interval, start_date, end_date });
export const getOptionChain = (symbol, exchange = "NFO") => post("optionchain", { symbol, exchange });
export const getOptionGreeks = (symbol, exchange = "NFO") => post("optiongreeks", { symbol, exchange });
export const getExpiry = (symbol, exchange = "NFO") => post("expiry", { symbol, exchange });
export const searchSymbol = (query) => post("search", { query });
export const getIntervals = () => get("intervals");

// --- Account APIs ---
export const getFunds = () => post("funds");
export const getOrderbook = () => post("orderbook");
export const getTradebook = () => post("tradebook");
export const getPositionbook = () => post("positionbook");
export const getHoldings = () => post("holdings");

// --- Utility APIs ---
export const ping = () => post("ping");
export const analyzerStatus = () => get("analyzer/status");
export const analyzerToggle = () => post("analyzer/toggle");
