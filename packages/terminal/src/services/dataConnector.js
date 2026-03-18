/**
 * DataBus connector — bridges OpenAlgo REST and WebSocket to the DataBus pub/sub system.
 *
 * Single entry-point: call startDataConnector() once from App.jsx on mount.
 * All widgets subscribe to dataBus topics; this module is the only caller of
 * the raw API and WebSocket services.
 *
 * Topic schema
 * ─────────────────────────────────────────────────────────────────────────────
 * "quote:{SYMBOL}:{EXCHANGE}"      — tick from WebSocket (or REST fallback)
 * "positions"                      — full positionbook array, polled every 5s / 60s
 * "orders"                         — full orderbook array, polled every 10s
 * "funds"                          — funds object, polled every 30s
 * "holdings"                       — holdings array, polled every 60s
 * "optionchain:{SYMBOL}:{EXCHANGE}:{EXPIRY}"  — on-demand fetch
 * "history:{SYMBOL}:{EXCHANGE}:{INTERVAL}"    — on-demand fetch
 * ─────────────────────────────────────────────────────────────────────────────
 */

import {
  getPositionbook,
  getOrderbook,
  getFunds,
  getHoldings,
  getOptionChain,
  getHistory,
  getExpiry,
  getQuotes,
} from "./api.js";
import { wsService } from "./websocket.js";
import { dataBus } from "./dataBus.js";
import { generalLimiter } from "./rateLimiter.js";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

/** Index instruments subscribed on WebSocket connect. */
const INDEX_INSTRUMENTS = [
  { symbol: "NIFTY", exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SENSEX", exchange: "BSE_INDEX" },
  { symbol: "INDIAVIX", exchange: "NSE_INDEX" },
];

/** Poll intervals (milliseconds). */
const POLL = {
  positions: {
    market: 5_000,
    offMarket: 60_000,
  },
  orders: 10_000,
  funds: 30_000,
  holdings: 60_000,
  indexQuotes: 10_000, // REST fallback for ticker bar when WS not delivering
};

const DEV = import.meta.env.DEV === true || import.meta.env.MODE === "development";

// ---------------------------------------------------------------------------
// Internal state
// ---------------------------------------------------------------------------

/** Handle objects returned by setInterval — cleared on stop. */
const _intervals = {
  positions: null,
  orders: null,
  funds: null,
  holdings: null,
  indexQuotes: null,
};

/** Tracks whether the connector has been started to prevent double-init. */
let _running = false;

/**
 * Tracks on-demand topics that have already been fetched so we don't refetch
 * on every new subscriber for the same topic.
 * @type {Set<string>}
 */
const _onDemandFetched = new Set();

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Returns true when the Indian equity market is open.
 * Equity session: 09:15 – 15:30 IST, Monday – Friday.
 * MCX evening session is NOT considered here because positions and orders are
 * per-account and the same poll schedule is acceptable for MCX.
 *
 * @returns {boolean}
 */
function isMarketHours() {
  const ist = new Date(new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  const mins = ist.getHours() * 60 + ist.getMinutes();
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  return mins >= 555 && mins <= 930; // 9:15 = 555, 15:30 = 930
}

/**
 * Logs API calls when running in development mode.
 *
 * @param {string} label - Short description of the call.
 */
function devLog(label) {
  if (DEV) {
    // eslint-disable-next-line no-console
    console.debug(`[DataConnector] ${label}`);
  }
}

/**
 * Safely calls an async API function, rate-limited via generalLimiter.
 * Skips the call (returns undefined) if the limiter rejects.
 * Never throws — errors are logged and swallowed so poll loops stay alive.
 *
 * @param {string} label - Human-readable name used in logs.
 * @param {() => Promise<unknown>} apiFn - Zero-argument async function.
 * @returns {Promise<unknown|undefined>}
 */
async function rateLimitedCall(label, apiFn) {
  if (!generalLimiter.tryConsume(1)) {
    devLog(`rate limited — skipping ${label}`);
    return undefined;
  }
  devLog(`calling ${label}`);
  try {
    return await apiFn();
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn(`[DataConnector] ${label} failed:`, err?.message ?? err);
    return undefined;
  }
}

// ---------------------------------------------------------------------------
// Poll workers
// ---------------------------------------------------------------------------

/**
 * Fetches the position book and publishes to dataBus.
 * Called by the positions interval.
 */
async function pollPositions() {
  const data = await rateLimitedCall("positionbook", getPositionbook);
  if (data !== undefined) {
    dataBus.publish("positions", data);
  }
}

/**
 * Fetches the order book and publishes to dataBus.
 * Called by the orders interval.
 */
async function pollOrders() {
  const data = await rateLimitedCall("orderbook", getOrderbook);
  if (data !== undefined) {
    dataBus.publish("orders", data);
  }
}

/**
 * Fetches funds and publishes to dataBus.
 * Called by the funds interval.
 */
async function pollFunds() {
  const data = await rateLimitedCall("funds", getFunds);
  if (data !== undefined) {
    dataBus.publish("funds", data);
  }
}

/**
 * Fetches holdings and publishes to dataBus.
 * Holdings change infrequently; called by the holdings interval.
 * Dhan Sandbox may not support holdings — errors are silently suppressed.
 */
async function pollHoldings() {
  const data = await rateLimitedCall("holdings", getHoldings);
  if (data !== undefined) {
    dataBus.publish("holdings", data);
  }
}

/**
 * REST fallback for index quotes when WebSocket isn't delivering ticks.
 * Polls each index instrument via getQuotes and publishes to the same
 * dataBus topic that WebSocket ticks would use.
 */
async function pollIndexQuotes() {
  for (const inst of INDEX_INSTRUMENTS) {
    const data = await rateLimitedCall(
      `quote:${inst.symbol}`,
      () => getQuotes(inst.symbol, inst.exchange)
    );
    if (data !== undefined) {
      const topic = `quote:${inst.symbol.toUpperCase()}:${inst.exchange.toUpperCase()}`;
      dataBus.publish(topic, data);
    }
  }
}

// ---------------------------------------------------------------------------
// Adaptive positions poll
// ---------------------------------------------------------------------------

/**
 * Schedules the positions poll with an interval that adapts to market hours.
 * During market hours: every 5 s. Off-hours: every 60 s.
 * The interval is re-evaluated on each tick to handle the open/close boundary
 * without restarting the whole connector.
 */
function _schedulePositions() {
  // Cancel any existing positions timer before rescheduling.
  if (_intervals.positions !== null) {
    clearInterval(_intervals.positions);
    _intervals.positions = null;
  }

  const interval = isMarketHours() ? POLL.positions.market : POLL.positions.offMarket;

  _intervals.positions = setInterval(async () => {
    await pollPositions();

    // Re-check whether the interval needs to change after each poll.
    const newInterval = isMarketHours() ? POLL.positions.market : POLL.positions.offMarket;
    if (newInterval !== interval) {
      // Schedule will reset itself on the next invocation by comparing
      // the captured `interval` closure value with the freshly computed one.
      // Use a one-shot reschedule to avoid drift accumulation.
      _schedulePositions();
    }
  }, interval);
}

// ---------------------------------------------------------------------------
// WebSocket tick handler
// ---------------------------------------------------------------------------

/**
 * Handles "ws:tick" DOM events dispatched by WebSocketService.
 * Publishes to "quote:{symbol}:{exchange}" on the DataBus.
 *
 * Expected tick shape (OpenAlgo v2 WebSocket):
 *   { symbol, exchange, ltp, open, high, low, close, volume, ... }
 *
 * @param {CustomEvent} event
 */
function _onWsTick(event) {
  const tick = event?.detail;
  if (!tick || typeof tick !== "object") return;

  const { symbol, exchange } = tick;
  if (!symbol || !exchange) return;

  // Normalise symbol to uppercase for consistent topic names.
  const topic = `quote:${String(symbol).toUpperCase()}:${String(exchange).toUpperCase()}`;
  dataBus.publish(topic, tick);
}

/**
 * Handles "ws:status" DOM events dispatched by WebSocketService.
 * Publishes to "ws:status" on the DataBus so widgets can react to
 * connection state without touching the DOM event system directly.
 *
 * @param {CustomEvent} event
 */
function _onWsStatus(event) {
  const detail = event?.detail;
  if (detail && typeof detail === "object") {
    dataBus.publish("ws:status", detail);
    devLog(`WebSocket ${detail.connected ? "connected" : "disconnected"}`);
  }
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Starts the DataBus connector.
 *
 * Call once from App.jsx on mount:
 * ```js
 * import { startDataConnector } from './services/dataConnector.js';
 * useEffect(() => {
 *   startDataConnector();
 *   return () => stopDataConnector();
 * }, []);
 * ```
 *
 * What this does:
 * 1. Connects WebSocket via wsService.
 * 2. Subscribes to index ticks (NIFTY, BANKNIFTY, SENSEX, INDIAVIX).
 * 3. Bridges "ws:tick" DOM events → dataBus "quote:{symbol}:{exchange}".
 * 4. Starts polling loops for positions, orders, funds, holdings.
 * 5. Each poll is guarded by generalLimiter.tryConsume().
 */
export function startDataConnector() {
  if (_running) {
    devLog("already running — ignoring duplicate startDataConnector() call");
    return;
  }
  _running = true;
  devLog("starting");

  // --- WebSocket -----------------------------------------------------------

  wsService.connect();
  wsService.subscribe(INDEX_INSTRUMENTS, "ltp");

  window.addEventListener("ws:tick", _onWsTick);
  window.addEventListener("ws:status", _onWsStatus);

  // --- REST polling --------------------------------------------------------

  // Fire immediately so widgets get data without waiting for the first interval.
  pollPositions();
  pollOrders();
  pollFunds();
  pollHoldings();
  pollIndexQuotes();

  // Adaptive positions schedule (5 s market / 60 s off-market).
  _schedulePositions();

  _intervals.orders = setInterval(pollOrders, POLL.orders);
  _intervals.funds = setInterval(pollFunds, POLL.funds);
  _intervals.holdings = setInterval(pollHoldings, POLL.holdings);
  _intervals.indexQuotes = setInterval(pollIndexQuotes, POLL.indexQuotes);

  devLog("started — polling positions, orders, funds, holdings");
}

/**
 * Stops the DataBus connector.
 *
 * Disconnects WebSocket, removes DOM event listeners, and clears all
 * polling intervals. Safe to call multiple times.
 */
export function stopDataConnector() {
  if (!_running) return;
  _running = false;
  devLog("stopping");

  // --- WebSocket -----------------------------------------------------------

  window.removeEventListener("ws:tick", _onWsTick);
  window.removeEventListener("ws:status", _onWsStatus);
  wsService.disconnect();

  // --- Intervals -----------------------------------------------------------

  for (const key of Object.keys(_intervals)) {
    if (_intervals[key] !== null) {
      clearInterval(_intervals[key]);
      _intervals[key] = null;
    }
  }

  // Clear the on-demand fetch cache so a fresh start re-fetches everything.
  _onDemandFetched.clear();

  devLog("stopped");
}

/**
 * Fetches data for topics that are not polled automatically.
 * Safe to call from multiple widgets — the actual API call fires only once
 * per topic until stopDataConnector() is called.
 *
 * Supported topic patterns:
 * - `"optionchain:{SYMBOL}:{EXCHANGE}:{EXPIRY}"`
 *   Fetches the option chain and publishes under the same topic.
 *   If expiry is omitted ("optionchain:{SYMBOL}:{EXCHANGE}"), the nearest
 *   expiry is resolved first via getExpiry() and then the chain is fetched.
 *
 * - `"history:{SYMBOL}:{EXCHANGE}:{INTERVAL}"`
 *   Fetches the last 30 calendar days of OHLCV bars and publishes under the
 *   same topic.
 *
 * Unrecognised topics are ignored with a console warning in development mode.
 *
 * @param {string} topic - DataBus topic string.
 * @returns {Promise<void>}
 */
export async function fetchOnDemand(topic) {
  if (_onDemandFetched.has(topic)) {
    devLog(`on-demand cache hit — ${topic}`);
    return;
  }

  if (topic.startsWith("optionchain:")) {
    await _fetchOptionChain(topic);
  } else if (topic.startsWith("history:")) {
    await _fetchHistory(topic);
  } else {
    if (DEV) {
      // eslint-disable-next-line no-console
      console.warn(`[DataConnector] fetchOnDemand: unrecognised topic "${topic}"`);
    }
  }
}

// ---------------------------------------------------------------------------
// On-demand fetch helpers
// ---------------------------------------------------------------------------

/**
 * Fetches option chain data for a given topic and publishes to dataBus.
 *
 * @param {string} topic - e.g. "optionchain:NIFTY:NFO:2024-01-25"
 *                         or "optionchain:NIFTY:NFO" (no expiry — resolve first).
 * @returns {Promise<void>}
 */
async function _fetchOptionChain(topic) {
  // topic = "optionchain:{SYMBOL}:{EXCHANGE}" or "optionchain:{SYMBOL}:{EXCHANGE}:{EXPIRY}"
  const parts = topic.split(":");
  // parts[0] = "optionchain"
  const symbol = parts[1];
  const exchange = parts[2] ?? "NFO";
  let expiry = parts[3]; // may be undefined

  if (!symbol) {
    devLog(`on-demand optionchain: missing symbol in topic "${topic}"`);
    return;
  }

  // Mark as fetched before the await to prevent concurrent duplicates.
  _onDemandFetched.add(topic);

  // Resolve nearest expiry if not supplied.
  if (!expiry) {
    const expiryData = await rateLimitedCall(`expiry:${symbol}`, () =>
      getExpiry(symbol, exchange)
    );
    if (!expiryData) {
      _onDemandFetched.delete(topic); // allow retry on next subscriber
      return;
    }
    // OpenAlgo getExpiry returns { expiry: [...] } or an array — normalise.
    const expiryList = Array.isArray(expiryData)
      ? expiryData
      : Array.isArray(expiryData?.expiry)
      ? expiryData.expiry
      : [];
    expiry = expiryList[0];
    if (!expiry) {
      devLog(`on-demand optionchain: no expiry returned for ${symbol}:${exchange}`);
      _onDemandFetched.delete(topic);
      return;
    }
  }

  const data = await rateLimitedCall(`optionchain:${symbol}:${exchange}`, () =>
    getOptionChain(symbol, exchange)
  );

  if (data !== undefined) {
    dataBus.publish(topic, data);
    devLog(`published ${topic}`);
  } else {
    // Allow retry on next subscriber call.
    _onDemandFetched.delete(topic);
  }
}

/**
 * Fetches OHLCV history for a given topic and publishes to dataBus.
 * Uses a 30-calendar-day window ending today by default.
 *
 * @param {string} topic - e.g. "history:NIFTY:NSE_INDEX:1h"
 * @returns {Promise<void>}
 */
async function _fetchHistory(topic) {
  // topic = "history:{SYMBOL}:{EXCHANGE}:{INTERVAL}"
  const parts = topic.split(":");
  const symbol = parts[1];
  const exchange = parts[2];
  const interval = parts[3] ?? "1d";

  if (!symbol || !exchange) {
    devLog(`on-demand history: missing symbol or exchange in topic "${topic}"`);
    return;
  }

  // Mark as fetched before the await to prevent concurrent duplicates.
  _onDemandFetched.add(topic);

  // Build a 30-day window in YYYY-MM-DD format.
  const now = new Date();
  const endDate = _toISTDateString(now);
  const startDate = _toISTDateString(new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000));

  const data = await rateLimitedCall(`history:${symbol}:${exchange}:${interval}`, () =>
    getHistory(symbol, exchange, interval, startDate, endDate)
  );

  if (data !== undefined) {
    dataBus.publish(topic, data);
    devLog(`published ${topic}`);
  } else {
    _onDemandFetched.delete(topic);
  }
}

/**
 * Formats a Date object as a YYYY-MM-DD string in IST.
 *
 * @param {Date} date
 * @returns {string}
 */
function _toISTDateString(date) {
  return new Date(date.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }))
    .toISOString()
    .slice(0, 10);
}
