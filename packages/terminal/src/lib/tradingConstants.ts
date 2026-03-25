/**
 * tradingConstants — shared exchange, product, and order type options.
 * Used by TradingStep (setup wizard) and any trading widget that needs these lists.
 */

export const EXCHANGES = [
  { value: "NSE", label: "NSE (Equity)"      },
  { value: "NFO", label: "NFO (F&O)"         },
  { value: "BSE", label: "BSE (Equity)"      },
  { value: "BFO", label: "BFO (BSE F&O)"     },
  { value: "MCX", label: "MCX (Commodities)" },
  { value: "CDS", label: "CDS (Currency)"    },
] as const;

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
