/**
 * Delta Exchange crypto pair metadata for FlintTrade.
 *
 * Delta Exchange is the Indian crypto derivatives exchange supported by
 * OpenAlgo (exchange identifier: "DELTA").  This module mirrors the Python
 * CryptoUtils catalogue and provides typed helpers for:
 *
 *  - Lot size and tick size lookups (used in order validation and display)
 *  - Price formatting with quote-currency precision
 *  - Trading fee schedule (maker / taker)
 *  - Market hours (Delta Exchange is always open — 24/7)
 *
 * Pattern intentionally mirrors `mcxLots.ts` so widget code stays consistent.
 */

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Full metadata for one Delta Exchange trading pair. */
export interface CryptoPairInfo {
  /** Base currency (e.g. "BTC"). */
  base: string;
  /** Quote currency (e.g. "USD" or "INR"). */
  quote: string;
  /** Minimum tradeable quantity increment. */
  lotSize: number;
  /** Minimum price movement. */
  tickSize: number;
  /** Maker fee as a fraction of notional (negative = rebate). */
  makerFee: number;
  /** Taker fee as a fraction of notional. */
  takerFee: number;
  /** Human-readable contract description. */
  description: string;
}

/** Maker / taker fee schedule returned by {@link getCryptoTradingFee}. */
export interface CryptoFeeSchedule {
  maker: number;
  taker: number;
}

// ---------------------------------------------------------------------------
// Pair catalogue
// ---------------------------------------------------------------------------

/**
 * All supported Delta Exchange perpetual / spot pairs.
 *
 * Fee schedule reflects Delta Exchange standard tier (updated 2026-04).
 * INR-quoted pairs have smaller lot sizes to match notional value equivalence.
 */
export const CRYPTO_PAIRS: Record<string, CryptoPairInfo> = {
  // ── USD-quoted pairs ──────────────────────────────────────────────────
  BTCUSD: {
    base: "BTC",
    quote: "USD",
    lotSize: 0.001,
    tickSize: 0.5,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Bitcoin Perpetual (USD)",
  },
  ETHUSD: {
    base: "ETH",
    quote: "USD",
    lotSize: 0.01,
    tickSize: 0.05,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Ethereum Perpetual (USD)",
  },
  SOLUSD: {
    base: "SOL",
    quote: "USD",
    lotSize: 0.1,
    tickSize: 0.01,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Solana Perpetual (USD)",
  },
  BNBUSD: {
    base: "BNB",
    quote: "USD",
    lotSize: 0.01,
    tickSize: 0.01,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "BNB Perpetual (USD)",
  },
  XRPUSD: {
    base: "XRP",
    quote: "USD",
    lotSize: 1.0,
    tickSize: 0.0001,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "XRP Perpetual (USD)",
  },
  MATICUSD: {
    base: "MATIC",
    quote: "USD",
    lotSize: 1.0,
    tickSize: 0.0001,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Polygon Perpetual (USD)",
  },
  // ── INR-quoted pairs ─────────────────────────────────────────────────
  BTCINR: {
    base: "BTC",
    quote: "INR",
    lotSize: 0.0001,
    tickSize: 1.0,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Bitcoin Perpetual (INR)",
  },
  ETHINR: {
    base: "ETH",
    quote: "INR",
    lotSize: 0.001,
    tickSize: 0.5,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Ethereum Perpetual (INR)",
  },
  SOLINR: {
    base: "SOL",
    quote: "INR",
    lotSize: 0.1,
    tickSize: 0.1,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "Solana Perpetual (INR)",
  },
  XRPINR: {
    base: "XRP",
    quote: "INR",
    lotSize: 1.0,
    tickSize: 0.01,
    makerFee: 0.0002,
    takerFee: 0.0005,
    description: "XRP Perpetual (INR)",
  },
};

// ---------------------------------------------------------------------------
// Exchange identifiers that map to Delta Exchange
// ---------------------------------------------------------------------------

/** Set of exchange strings (upper-cased) that identify Delta Exchange. */
export const DELTA_EXCHANGE_NAMES = new Set<string>([
  "DELTA",
  "DELTAEXCHANGE",
  "CRYPTO",
]);

// ---------------------------------------------------------------------------
// Decimal precision per quote currency
// ---------------------------------------------------------------------------

const QUOTE_DECIMALS: Record<string, number> = {
  USD: 2,
  INR: 2,
  USDT: 4,
  BTC: 8,
  ETH: 6,
};

// ---------------------------------------------------------------------------
// Convenience exports (mirrors MCX_COMMODITIES pattern)
// ---------------------------------------------------------------------------

/** All known Delta Exchange pair symbols. */
export const CRYPTO_SYMBOLS: string[] = Object.keys(CRYPTO_PAIRS).sort();

// ---------------------------------------------------------------------------
// Helper functions
// ---------------------------------------------------------------------------

/**
 * Return true if `exchange` refers to Delta Exchange.
 *
 * Comparison is case-insensitive.
 *
 * @example
 * isCryptoExchange("DELTA")       // true
 * isCryptoExchange("delta")       // true
 * isCryptoExchange("NSE")         // false
 */
export function isCryptoExchange(exchange: string): boolean {
  return DELTA_EXCHANGE_NAMES.has(exchange.toUpperCase());
}

/**
 * Return true if `symbol` is a known Delta Exchange trading pair.
 *
 * Comparison is case-insensitive.
 *
 * @example
 * isCryptoPair("BTCUSD")          // true
 * isCryptoPair("btcusd")          // true
 * isCryptoPair("RELIANCE")        // false
 */
export function isCryptoPair(symbol: string): boolean {
  return symbol.toUpperCase() in CRYPTO_PAIRS;
}

/**
 * Return the full {@link CryptoPairInfo} for `symbol`, or `undefined` if unknown.
 *
 * @example
 * getCryptoPairInfo("BTCUSD")?.lotSize   // 0.001
 */
export function getCryptoPairInfo(symbol: string): CryptoPairInfo | undefined {
  return CRYPTO_PAIRS[symbol.toUpperCase()];
}

/**
 * Return the minimum lot size for `symbol`.
 *
 * Falls back to `0.001` (BTC default) for unknown symbols so callers always
 * receive a usable value.
 *
 * @example
 * getCryptoLotSize("BTCUSD")   // 0.001
 * getCryptoLotSize("XRPUSD")   // 1.0
 */
export function getCryptoLotSize(symbol: string): number {
  return CRYPTO_PAIRS[symbol.toUpperCase()]?.lotSize ?? 0.001;
}

/**
 * Return the minimum price tick for `symbol`.
 *
 * Falls back to `0.01` for unknown symbols.
 *
 * @example
 * getCryptoTickSize("BTCUSD")   // 0.5
 * getCryptoTickSize("ETHUSD")   // 0.05
 */
export function getCryptoTickSize(symbol: string): number {
  return CRYPTO_PAIRS[symbol.toUpperCase()]?.tickSize ?? 0.01;
}

/**
 * Format `price` with the correct decimal precision for `symbol`.
 *
 * Decimal places are determined by the quote currency:
 * - USD / INR → 2 dp
 * - USDT      → 4 dp
 * - BTC       → 8 dp
 * - ETH       → 6 dp
 * - Unknown   → 2 dp (safe default)
 *
 * @throws {RangeError} If `price` is negative.
 *
 * @example
 * formatCryptoPrice(67432.5, "BTCUSD")   // "67432.50"
 * formatCryptoPrice(0.05,    "ETHUSD")   // "0.05"
 */
export function formatCryptoPrice(price: number, symbol: string): string {
  if (price < 0) {
    throw new RangeError(`Price cannot be negative: ${price}`);
  }
  const info = CRYPTO_PAIRS[symbol.toUpperCase()];
  const quote = info?.quote ?? "USD";
  const dp = QUOTE_DECIMALS[quote] ?? 2;
  return price.toFixed(dp);
}

/**
 * Return the maker/taker fee schedule for `symbol`.
 *
 * Falls back to the standard Delta Exchange tier for unknown symbols.
 *
 * @example
 * getCryptoTradingFee("BTCUSD")   // { maker: 0.0002, taker: 0.0005 }
 */
export function getCryptoTradingFee(symbol: string): CryptoFeeSchedule {
  const info = CRYPTO_PAIRS[symbol.toUpperCase()];
  if (info) {
    return { maker: info.makerFee, taker: info.takerFee };
  }
  // Standard Delta Exchange tier as fallback
  return { maker: 0.0002, taker: 0.0005 };
}

/**
 * Delta Exchange is always open — crypto markets run 24/7.
 *
 * This function exists so exchange-agnostic code can call a single
 * `isCryptoMarketOpen()` check without reading from `market.ts` directly.
 *
 * @returns Always `true`.
 */
export function isCryptoMarketOpen(): true {
  return true;
}

/**
 * Round `quantity` down to the nearest valid lot size increment.
 *
 * Prevents order rejection caused by sub-lot quantities.
 *
 * @throws {RangeError} If `quantity` is not positive.
 *
 * @example
 * roundToLotSize(0.0037, "BTCUSD")   // 0.003
 */
export function roundToLotSize(quantity: number, symbol: string): number {
  if (quantity <= 0) {
    throw new RangeError(`Quantity must be positive: ${quantity}`);
  }
  const lot = getCryptoLotSize(symbol);
  const factor = Math.round(1 / lot);
  return Math.floor(quantity * factor) / factor;
}

/**
 * Round `price` to the nearest valid tick increment.
 *
 * Prevents order rejection caused by invalid price precision.
 *
 * @throws {RangeError} If `price` is not positive.
 *
 * @example
 * roundToTickSize(67432.3, "BTCUSD")   // 67432.5
 */
export function roundToTickSize(price: number, symbol: string): number {
  if (price <= 0) {
    throw new RangeError(`Price must be positive: ${price}`);
  }
  const tick = getCryptoTickSize(symbol);
  const factor = Math.round(1 / tick);
  return Math.round(price * factor) / factor;
}
