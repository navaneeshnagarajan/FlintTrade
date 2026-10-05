/** Terminal order vocabulary supported by FlintTrade's native adapter mappings.
 * Availability for a particular account still comes from its capabilities.
 */
const orderSegments = [
  ["NSE", "NSE (Equity)"], ["BSE", "BSE (Equity)"],
  ["NFO", "NFO (F&O)"], ["BFO", "BFO (BSE F&O)"],
  ["MCX", "MCX (Commodities)"], ["CDS", "CDS (Currency)"],
  ["BCD", "BCD (BSE Currency)"],
] as const;
const indexSegments = [
  ["NSE_INDEX", "NSE Indices"], ["BSE_INDEX", "BSE Indices"],
  ["MCX_INDEX", "MCX Indices"], ["GLOBAL_INDEX", "Global Indices"],
] as const;
export const TRADEABLE_EXCHANGES = orderSegments.map(([value, label]) => ({ value, label }));
export const QUOTE_ONLY_EXCHANGES = indexSegments.map(([value, label]) => ({ value, label, quoteOnly: true as const }));
export const EXCHANGES = [...TRADEABLE_EXCHANGES, ...QUOTE_ONLY_EXCHANGES];
export type ExchangeValue = typeof EXCHANGES[number]["value"];

export const PRODUCTS = [
  { value: "MIS", label: "MIS (Intraday)" },
  { value: "NRML", label: "NRML (Overnight)" },
  { value: "CNC", label: "CNC (Delivery)" },
] as const;
export type ProductValue = typeof PRODUCTS[number]["value"];
export const ORDER_TYPES = [
  { value: "MARKET", label: "Market" },
  { value: "LIMIT", label: "Limit" },
  { value: "SL", label: "Stop Loss" },
  { value: "SL-M", label: "SL Market" },
] as const;
export type OrderTypeValue = typeof ORDER_TYPES[number]["value"];

/** Persistent triggers require a position product that survives the session. */
export const GTT_PRODUCTS = PRODUCTS.filter((product) => product.value !== "MIS");
export type GttProductValue = typeof GTT_PRODUCTS[number]["value"];
export const GTT_TRIGGER_TYPES = [
  { value: "SINGLE", label: "Single trigger" },
  { value: "OCO", label: "OCO (Stoploss + Target)" },
] as const;
export type GttTriggerType = typeof GTT_TRIGGER_TYPES[number]["value"];
