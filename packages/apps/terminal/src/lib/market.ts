/**
 * Exchange-aware market hours for Indian exchanges.
 *
 * All times in IST (Asia/Kolkata, UTC+5:30).
 * Hours expressed as minutes-since-midnight for fast comparison.
 */

import type { Holiday, MarketTiming } from "@/types/api";

// ---------------------------------------------------------------------------
// Per-exchange trading hours (minutes since midnight, IST)
// ---------------------------------------------------------------------------

interface ExchangeHours {
  /** Minutes since midnight IST when the exchange opens. */
  open: number;
  /** Minutes since midnight IST when the exchange closes (inclusive). */
  close: number;
}

export interface MarketHoursInstrument {
  /** Backend exchange identity. */
  exchange: string;
  /** Exchange symbol or dated contract symbol. */
  symbol: string;
}

export type MarketHoursTarget = string | MarketHoursInstrument;

const EXCHANGE_HOURS: Record<string, ExchangeHours> = {
  NSE:          { open: 9 * 60 + 15, close: 15 * 60 + 30 },  // 9:15–15:30
  BSE:          { open: 9 * 60 + 15, close: 15 * 60 + 30 },
  NFO:          { open: 9 * 60 + 15, close: 15 * 60 + 30 },
  BFO:          { open: 9 * 60 + 15, close: 15 * 60 + 30 },
  CDS:          { open: 9 * 60,      close: 17 * 60 },        // 9:00–17:00
  BCD:          { open: 9 * 60,      close: 17 * 60 },
  MCX:          { open: 9 * 60,      close: 23 * 60 + 30 },   // 9:00–23:30
  NCDEX:        { open: 10 * 60,     close: 17 * 60 },        // 10:00–17:00
  // NCO (NSE Commodities, Zerodha-only) — added upstream in OpenAlgo v2.0.0.7.
  NCO:          { open: 9 * 60,      close: 17 * 60 },        // 9:00–17:00
  NSE_INDEX:    { open: 9 * 60 + 15, close: 15 * 60 + 30 },  // quote-only, mirrors NSE
  BSE_INDEX:    { open: 9 * 60 + 15, close: 15 * 60 + 30 },
  // MCX_INDEX (commodity indices, e.g. MCXBULLDEX) — quote-only.
  MCX_INDEX:    { open: 9 * 60,      close: 23 * 60 + 30 },
  // GLOBAL_INDEX (foreign + IFSC reference indices) — always-on reference
  // feed; we expose the widest plausible window so the UI never reports
  // "closed" for a US/UK/Asia index quote.
  GLOBAL_INDEX: { open: 0,           close: 23 * 60 + 59 },
};

const CDS_CROSS_CURRENCY_HOURS: ExchangeHours = {
  open: 9 * 60,
  close: 19 * 60 + 30,
};

const CDS_CROSS_CURRENCY_UNDERLYINGS = ["EURUSD", "GBPUSD", "USDJPY"] as const;

/** Return whether a CDS symbol is a supported cross-currency underlying or contract. */
export function isCrossCurrencyCdsSymbol(symbol: string): boolean {
  const normalisedSymbol = symbol.trim().toUpperCase();
  return CDS_CROSS_CURRENCY_UNDERLYINGS.some((underlying) => (
    normalisedSymbol === underlying
    || (
      normalisedSymbol.startsWith(underlying)
      && /^\d/.test(normalisedSymbol.slice(underlying.length))
    )
  ));
}

function resolveMarketHours(target?: MarketHoursTarget): {
  exchange: string;
  hours: ExchangeHours | undefined;
} {
  const rawExchange = typeof target === "string"
    ? target
    : target?.exchange ?? "NSE";
  const exchange = rawExchange.trim().toUpperCase();
  const symbol = typeof target === "object" ? target.symbol : undefined;

  if (exchange === "CDS" && symbol && isCrossCurrencyCdsSymbol(symbol)) {
    return { exchange, hours: CDS_CROSS_CURRENCY_HOURS };
  }
  return { exchange, hours: EXCHANGE_HOURS[exchange] };
}

const HOLIDAY_EXCHANGE_ALIASES: Record<string, readonly string[]> = {
  NSE_INDEX: ["NSE_INDEX", "NSE"],
  NFO: ["NFO", "NSE"],
  BSE_INDEX: ["BSE_INDEX", "BSE"],
  BFO: ["BFO", "BSE"],
  MCX_INDEX: ["MCX_INDEX", "MCX"],
};

function exchangeHolidayAliases(exchange: string): readonly string[] {
  return HOLIDAY_EXCHANGE_ALIASES[exchange] ?? [exchange];
}

function holidayForDate(holidays: readonly Holiday[], date: Date): Holiday | undefined {
  const dateKey = date.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
  return holidays.find((candidate) => candidate.date === dateKey);
}

function epochMilliseconds(value: number): number | null {
  if (!Number.isFinite(value) || value <= 0) return null;
  // Calendar providers use epoch seconds or milliseconds. Values below this
  // threshold cannot be a contemporary millisecond timestamp.
  return value < 100_000_000_000 ? value * 1_000 : value;
}

function specialSessionState(
  exchange: string,
  holidays: readonly Holiday[],
  date: Date,
): boolean | undefined {
  const holiday = holidayForDate(holidays, date);
  if (!holiday) return undefined;

  const aliases = exchangeHolidayAliases(exchange);
  const sessions = holiday.open_exchanges.filter((session) => (
    aliases.includes(session.exchange.trim().toUpperCase())
  ));
  if (sessions.length === 0) return undefined;

  const now = date.getTime();
  return sessions.some((session) => {
    const start = epochMilliseconds(session.start_time);
    const end = epochMilliseconds(session.end_time);
    return start !== null && end !== null && end >= start && now >= start && now <= end;
  });
}

/** Return whether a calendar row closes this exchange, including the all-exchange `*` wildcard. */
export function holidayClosesExchange(holiday: Holiday, exchange: string): boolean {
  const aliases = exchangeHolidayAliases(exchange);
  return holiday.closed_exchanges.some((closedExchange) => {
    const closed = closedExchange.trim().toUpperCase();
    return closed === "*" || aliases.includes(closed);
  });
}

function isClosedByHoliday(exchange: string, holidays: readonly Holiday[], date: Date): boolean {
  if (holidays.length === 0) return false;

  const holiday = holidayForDate(holidays, date);
  if (!holiday) return false;

  return holidayClosesExchange(holiday, exchange);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Check if a given exchange is currently within trading hours.
 *
 * When called without an exchange argument, defaults to NSE/BSE equity hours
 * (9:15 AM – 3:30 PM IST, Mon–Fri) for backward compatibility.
 *
 * DELTA (crypto) is always considered open (24/7).
 */
export function isMarketHours(
  target?: MarketHoursTarget,
  holidays: readonly Holiday[] = [],
): boolean {
  const { exchange, hours } = resolveMarketHours(target);
  if (exchange === "DELTA") return true;

  const now = new Date();
  const ist = new Date(
    now.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const specialSession = specialSessionState(exchange, holidays, now);
  if (specialSession !== undefined) return specialSession;

  const day = ist.getDay();
  if (day === 0 || day === 6) return false;
  if (isClosedByHoliday(exchange, holidays, now)) return false;

  if (!hours) return false;

  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= hours.open && mins <= hours.close;
}

export type MarketSessionStatus = "open" | "closed" | "unavailable";

export interface MarketSessionInfo {
  status: MarketSessionStatus;
  label: string;
}

const MARKET_OPEN: MarketSessionInfo = { status: "open", label: "Market open" };
const MARKET_CLOSED: MarketSessionInfo = { status: "closed", label: "Market closed" };
const MARKET_UNAVAILABLE: MarketSessionInfo = {
  status: "unavailable",
  label: "Market unavailable",
};

/** Contemporary epoch-ms floor; values below this are seconds or clock encodings. */
const EPOCH_MS_FLOOR = 100_000_000_000;
/** ~2001-09-09; below this, a timing number is HHMM (915 / 1530), not epoch seconds. */
const EPOCH_SECONDS_FLOOR = 1_000_000_000;

function istWeekdayAndMinutes(date: Date): { day: number; minutes: number } {
  const ist = new Date(date.toLocaleString("en-US", { timeZone: "Asia/Kolkata" }));
  return {
    day: ist.getDay(),
    minutes: ist.getHours() * 60 + ist.getMinutes(),
  };
}

/** Interpret OpenAlgo/Explore `915` / `1530` as minutes since midnight IST. */
function hhmmToMinutes(value: number): number | null {
  if (!Number.isFinite(value) || value < 0 || value > 2359) return null;
  const hhmm = Math.trunc(value);
  const hours = Math.floor(hhmm / 100);
  const minutes = hhmm % 100;
  if (hours > 23 || minutes > 59) return null;
  return hours * 60 + minutes;
}

function sessionBoundToEpochMs(value: number): number | null {
  if (!Number.isFinite(value) || value <= 0) return null;
  if (value >= EPOCH_MS_FLOOR) return value;
  if (value >= EPOCH_SECONDS_FLOOR) return value * 1_000;
  return null;
}

/**
 * NSE cash regular-session status in Asia/Kolkata.
 *
 * Timing bounds may be epoch milliseconds (native brokers), epoch seconds,
 * or HHMM integers used by OpenAlgo and the Explore stub (`915` / `1530`).
 * Weekends are closed. Missing or unusable timings are unavailable rather
 * than a false closed state.
 */
export function getNseCashSessionStatus(
  timings: readonly MarketTiming[] | undefined,
  now: Date = new Date(),
): MarketSessionInfo {
  if (!timings) return MARKET_UNAVAILABLE;

  const { day, minutes } = istWeekdayAndMinutes(now);
  if (day === 0 || day === 6) return MARKET_CLOSED;

  const nseTiming = timings.find(
    (timing) => timing.exchange === "NSE" || timing.exchange === "NSE_INDEX",
  );
  if (!nseTiming) return MARKET_UNAVAILABLE;

  const startMins = hhmmToMinutes(nseTiming.start_time);
  const endMins = hhmmToMinutes(nseTiming.end_time);
  if (
    startMins !== null
    && endMins !== null
    && nseTiming.start_time < EPOCH_SECONDS_FLOOR
    && nseTiming.end_time < EPOCH_SECONDS_FLOOR
  ) {
    if (minutes >= startMins && minutes <= endMins) return MARKET_OPEN;
    return MARKET_CLOSED;
  }

  const startMs = sessionBoundToEpochMs(nseTiming.start_time);
  const endMs = sessionBoundToEpochMs(nseTiming.end_time);
  if (startMs === null || endMs === null) return MARKET_UNAVAILABLE;

  const nowMs = now.getTime();
  if (nowMs < startMs) return MARKET_CLOSED;
  if (nowMs <= endMs) return MARKET_OPEN;
  return MARKET_CLOSED;
}

export type MCXMarketStatus = "open" | "pre-market" | "closed" | "weekend";

export interface MCXMarketStatusInfo {
  status: MCXMarketStatus;
  label: string;
}

/**
 * Get MCX-specific market status.
 * MCX hours: 9:00 AM – 11:30 PM IST (Mon–Fri).
 */
export function getMCXStatus(): MCXMarketStatusInfo {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const day = ist.getDay();
  if (day === 0 || day === 6) {
    return { status: "weekend", label: "Weekend" };
  }

  const mins = ist.getHours() * 60 + ist.getMinutes();
  const mcx = EXCHANGE_HOURS.MCX;

  if (mins < mcx.open) return { status: "pre-market", label: "MCX Pre-Market" };
  if (mins <= mcx.close) return { status: "open", label: "MCX Open" };
  return { status: "closed", label: "MCX Closed" };
}

/**
 * Get market status for any exchange.
 * Returns pre-market / open / closed / weekend.
 */
export function getExchangeStatus(target: MarketHoursTarget): MCXMarketStatusInfo {
  const { exchange, hours } = resolveMarketHours(target);
  if (exchange === "DELTA") {
    return { status: "open", label: "DELTA Open (24/7)" };
  }

  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const day = ist.getDay();
  if (day === 0 || day === 6) {
    return { status: "weekend", label: "Weekend" };
  }

  if (!hours) {
    return { status: "closed", label: `${exchange} Unknown` };
  }

  const mins = ist.getHours() * 60 + ist.getMinutes();
  if (mins < hours.open) return { status: "pre-market", label: `${exchange} Pre-Market` };
  if (mins <= hours.close) return { status: "open", label: `${exchange} Open` };
  return { status: "closed", label: `${exchange} Closed` };
}

/** Exported for tests and widgets that need raw hours data. */
// ---------------------------------------------------------------------------
// Tick-atom keys for bare index symbols
// ---------------------------------------------------------------------------

// Index symbols tick under their *_INDEX exchange in every price source (WS
// bridge, demo feed, REST fallback), while order forms default to a tradeable
// exchange ("NSE"). Composing a tick key straight from the form exchange
// ("NSE:NIFTY") therefore reads an atom nothing writes, and the LTP sits at 0.
const INDEX_TICK_EXCHANGES: Record<string, string> = {
  NIFTY: "NSE_INDEX",
  BANKNIFTY: "NSE_INDEX",
  FINNIFTY: "NSE_INDEX",
  INDIAVIX: "NSE_INDEX",
  SENSEX: "BSE_INDEX",
};

/** Tick-atom key for an instrument, normalising bare index names to their *_INDEX exchange. */
export function tickKeyFor(symbol: string, exchange: string): string {
  return `${INDEX_TICK_EXCHANGES[symbol] ?? exchange}:${symbol}`;
}

export { EXCHANGE_HOURS };
export type { ExchangeHours };
