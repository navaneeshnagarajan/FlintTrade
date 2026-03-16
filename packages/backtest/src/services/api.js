/**
 * Backtest API client.
 * Talks to the backtest-engine Python backend and OpenAlgo for symbol search.
 */

const BACKTEST_HOST = import.meta.env.VITE_BACKTEST_HOST || "http://127.0.0.1:5000";
const OPENALGO_HOST = import.meta.env.VITE_OPENALGO_HOST || "http://127.0.0.1:5000";
const API_KEY = import.meta.env.VITE_OPENALGO_API_KEY || "";

async function postBacktest(endpoint, body = {}) {
  const resp = await fetch(`${BACKTEST_HOST}/api/backtest/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!resp.ok) throw new Error(`Backtest API ${endpoint}: HTTP ${resp.status}`);
  return resp.json();
}

async function getBacktest(endpoint) {
  const resp = await fetch(`${BACKTEST_HOST}/api/backtest/${endpoint}`);
  if (!resp.ok) throw new Error(`Backtest API ${endpoint}: HTTP ${resp.status}`);
  return resp.json();
}

async function postOpenAlgo(endpoint, extra = {}) {
  const resp = await fetch(`${OPENALGO_HOST}/api/v1/${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ apikey: API_KEY, ...extra }),
  });
  if (!resp.ok) throw new Error(`OpenAlgo ${endpoint}: HTTP ${resp.status}`);
  return resp.json();
}

// --- Backtest APIs ---
export const runBacktest = (config) => postBacktest("run", config);
export const getBacktestStatus = (jobId) => getBacktest(`status/${jobId}`);
export const getBacktestResult = (jobId) => getBacktest(`result/${jobId}`);
export const getStrategies = () => getBacktest("strategies");
export const getBacktestHistory = () => getBacktest("history");
export const deleteBacktest = (jobId) => postBacktest(`delete/${jobId}`);

// --- OpenAlgo APIs ---
export const searchSymbol = (query) => postOpenAlgo("search", { query });
