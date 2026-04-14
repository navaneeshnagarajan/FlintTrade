/**
 * Raw API response types matching OpenAlgo's snake_case wire format.
 *
 * OpenAlgo REST endpoints return snake_case field names, while the typed
 * api.ts interfaces use camelCase after normalisation. These raw interfaces
 * reflect the actual wire format so widgets can safely process API data
 * before normalisation.
 *
 * All numeric fields are typed as `string | number` because JSON fields may
 * arrive as strings from some brokers even when they represent numbers.
 */

export interface RawPosition {
  symbol: string;
  pnl?: string | number;
  average_price?: string | number;
  ltp?: string | number;
  quantity?: string | number;
}

export interface RawOrder {
  symbol: string;
  orderId?: string;
  order_id?: string;
  action?: string;
  quantity?: string | number;
  price?: string | number;
  order_status?: string;
  status?: string;
  timestamp?: string;
}

/** Holdings — broker field names vary, so aliases are included. */
export interface RawHolding {
  symbol?: string;
  tradingsymbol?: string;
  exchange?: string;
  quantity?: string | number;
  qty?: string | number;
  average_price?: string | number;
  avg_price?: string | number;
  ltp?: string | number;
  close_price?: string | number;
}

/** Tradebook — broker field names vary; all known aliases included. */
export interface RawTrade {
  symbol?: string;
  tradingsymbol?: string;
  action?: string;
  transaction_type?: string;
  side?: string;
  quantity?: string | number;
  qty?: string | number;
  filled_quantity?: string | number;
  average_price?: string | number;
  price?: string | number;
  trade_price?: string | number;
  trade_time?: string;
  timestamp?: string;
  order_time?: string;
}

export interface RawFunds {
  availablecash?: string | number;
  utiliseddebits?: string | number;
}
