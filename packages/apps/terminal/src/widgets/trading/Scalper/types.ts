// ─── Scalper — shared types and constants ─────────────────────────────────────

import type { WsTick } from "@/types/api";

/** WsTick extended with optional prev_close that some broker responses carry */
export interface TickData extends WsTick {
  prev_close?: number;
}

export type TickMap = Record<string, TickData>;

export type OrderAction = "BUY" | "SELL";
export type ProductType = "MIS" | "NRML";
export type OrderTypeValue = "MARKET" | "LIMIT";
export type IntervalValue = "1m" | "3m" | "5m" | "15m";
export type StatusType = "idle" | "success" | "error" | "pending";

export interface PendingOrder {
  sym: string;
  exch: string;
  action: OrderAction;
}

export interface StatusState {
  message: string;
  type: StatusType;
}

// ─── Constants ────────────────────────────────────────────────────────────────

export interface IndexConfig {
  exchange: string;
  optExchange: string;
  step: number;
}

/**
 * Shown on a Scalper row when the broker instrument master has no lot size.
 * Orders still fail closed until a live symbol master confirms the multiplier.
 */
export const LOT_SIZE_MASTER_HINT = "Lot size comes from the broker instrument master.";

/**
 * Index rows for the Scalper. Lot size is not stored here. The display reads
 * the cached broker instrument master and names the near-month contract,
 * plus the next month when its size differs. A missing row shows an em dash
 * with {@link LOT_SIZE_MASTER_HINT}. Strike steps are not contract multipliers.
 * Order placement stays fail-closed until the live symbol master confirms.
 */
export const INDEX_CONFIG: Record<string, IndexConfig> = {
  NIFTY:      { exchange: "NSE_INDEX", optExchange: "NFO",  step: 50  },
  BANKNIFTY:  { exchange: "NSE_INDEX", optExchange: "NFO",  step: 100 },
  FINNIFTY:   { exchange: "NSE_INDEX", optExchange: "NFO",  step: 50  },
  MIDCPNIFTY: { exchange: "NSE_INDEX", optExchange: "NFO",  step: 25  },
  SENSEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  step: 100 },
  BANKEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  step: 100 },
};

export const SYMBOLS = Object.keys(INDEX_CONFIG);
export const DEFAULT_SYMBOL = "NIFTY";
