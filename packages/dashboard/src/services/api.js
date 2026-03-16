/**
 * OpenAlgo REST API client for the dashboard.
 * Base URL from VITE_OPENALGO_HOST, API key from VITE_OPENALGO_API_KEY.
 */

const BASE = import.meta.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000";
const API_KEY = import.meta.env.VITE_OPENALGO_API_KEY || "";

async function post(endpoint, extra = {}) {
  const resp = await fetch(`${BASE}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apikey: API_KEY, ...extra }),
  });
  if (!resp.ok) throw new Error(`API ${endpoint}: HTTP ${resp.status}`);
  return resp.json();
}

// --- Account APIs ---
export const getFunds = () => post("funds");
export const getPositionbook = () => post("positionbook");
export const getOrderbook = () => post("orderbook");
export const getTradebook = () => post("tradebook");
export const getHoldings = () => post("holdings");

// --- Data APIs ---
export const getQuotes = (symbol, exchange = "NSE") => post("quotes", { symbol, exchange });
export const getMultiQuotes = (symbols) => post("multiquotes", { symbols });

// --- Utility APIs ---
export const ping = () => post("ping");
export const analyzerStatus = () => post("analyzer/status");
