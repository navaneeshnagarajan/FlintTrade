/**
 * tradingConstants — shared exchange, product, and order type options.
 * Used by TradingStep (setup wizard) and any trading widget that needs these lists.
 *
 * Mirrors VALID_EXCHANGES from
 * .local/external/openalgo/utils/constants.py — keep in sync after every
 * upstream refresh. Index-only segments (*_INDEX, GLOBAL_INDEX) are
 * tagged ``quoteOnly: true`` so the order-entry UI can hide them from
 * the destination picker while keeping them visible in symbol search.
 */

export const EXCHANGES = [
  { value: "NSE",          label: "NSE (Equity)"               },
  { value: "NFO",          label: "NFO (F&O)"                  },
  { value: "BSE",          label: "BSE (Equity)"               },
  { value: "BFO",          label: "BFO (BSE F&O)"              },
  { value: "MCX",          label: "MCX (Commodities)"          },
  { value: "CDS",          label: "CDS (Currency)"             },
  { value: "BCD",          label: "BCD (BSE Currency)"         },
  { value: "NCDEX",        label: "NCDEX (Agri Commodities)"   },
  { value: "NCO",          label: "NCO (NSE Commodities)"      },
  { value: "NSE_INDEX",    label: "NSE Indices",      quoteOnly: true },
  { value: "BSE_INDEX",    label: "BSE Indices",      quoteOnly: true },
  { value: "MCX_INDEX",    label: "MCX Indices",      quoteOnly: true },
  { value: "GLOBAL_INDEX", label: "Global Indices",   quoteOnly: true },
] as const;

/** Subset of EXCHANGES that can receive orders (no quote-only segments). */
export const TRADEABLE_EXCHANGES = EXCHANGES.filter(
  (e) => !("quoteOnly" in e && e.quoteOnly),
);

/** Subset of EXCHANGES that price index baskets and reject orders. */
export const QUOTE_ONLY_EXCHANGES = EXCHANGES.filter(
  (e) => "quoteOnly" in e && e.quoteOnly,
);

export const PRODUCTS = [
  { value: "MIS",  label: "MIS (Intraday)"  },
  { value: "NRML", label: "NRML (Overnight)" },
  { value: "CNC",  label: "CNC (Delivery)"  },
] as const;

export const ORDER_TYPES = [
  { value: "MARKET", label: "Market"    },
  { value: "LIMIT",  label: "Limit"     },
  { value: "SL",     label: "Stop Loss" },
  { value: "SL-M",   label: "SL Market" },
] as const;

export type ExchangeValue = typeof EXCHANGES[number]["value"];
export type ProductValue = typeof PRODUCTS[number]["value"];
export type OrderTypeValue = typeof ORDER_TYPES[number]["value"];

/** Products allowed on GTT (Good Till Triggered) orders — MIS is rejected
 * upstream because triggers can sit for days. */
export const GTT_PRODUCTS = [
  { value: "CNC",  label: "CNC (Delivery)"   },
  { value: "NRML", label: "NRML (Overnight)" },
] as const;

export type GttProductValue = typeof GTT_PRODUCTS[number]["value"];

export const GTT_TRIGGER_TYPES = [
  { value: "SINGLE", label: "Single trigger"          },
  { value: "OCO",    label: "OCO (Stoploss + Target)" },
] as const;

export type GttTriggerType = typeof GTT_TRIGGER_TYPES[number]["value"];
