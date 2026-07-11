/**
 * Exchange-aware market hours for Indian exchanges.
 *
 * All times in IST (Asia/Kolkata, UTC+5:30).
 * Hours expressed as minutes-since-midnight for fast comparison.
 */

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
  const exchange = typeof target === "string"
    ? target
    : target?.exchange ?? "NSE";
  const symbol = typeof target === "object" ? target.symbol : undefined;

  if (exchange === "CDS" && symbol && isCrossCurrencyCdsSymbol(symbol)) {
    return { exchange, hours: CDS_CROSS_CURRENCY_HOURS };
  }
  return { exchange, hours: EXCHANGE_HOURS[exchange] };
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
export function isMarketHours(target?: MarketHoursTarget): boolean {
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const day = ist.getDay();
  if (day === 0 || day === 6) return false;

  // Delta Exchange — 24/7 crypto
  const { exchange, hours } = resolveMarketHours(target);
  if (exchange === "DELTA") return true;

  if (!hours) return false;

  const mins = ist.getHours() * 60 + ist.getMinutes();
  return mins >= hours.open && mins <= hours.close;
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
  const ist = new Date(
    new Date().toLocaleString("en-US", { timeZone: "Asia/Kolkata" }),
  );
  const day = ist.getDay();
  if (day === 0 || day === 6) {
    return { status: "weekend", label: "Weekend" };
  }

  const { exchange, hours } = resolveMarketHours(target);
  if (exchange === "DELTA") {
    return { status: "open", label: "DELTA Open (24/7)" };
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
export { EXCHANGE_HOURS };
export type { ExchangeHours };
