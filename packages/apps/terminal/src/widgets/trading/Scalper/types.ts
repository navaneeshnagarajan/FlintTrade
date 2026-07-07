// ─── Scalper — shared types and constants ─────────────────────────────────────

import type { WsTick } from "@/types/api";

/** WsTick extended with optional prev_close that some OpenAlgo responses carry */
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
  lotSize: number;
  step: number;
}

/**
 * LAST-RESORT lot-size fallback — DISPLAY ONLY, never order-sizing.
 *
 * The Scalper resolves the real lot size at runtime from the broker symbol
 * master (`getSymbol` — the same symbol-info API QuickTrade uses), then from
 * the backend lot-size resolver route. Until one of those confirms, these
 * built-in values are shown with an "(unverified)" marker and order
 * placement FAILS CLOSED — a stale hardcoded lot size mis-sizes every order.
 * Values mirror `flinttrade_screener.lot_sizes.FALLBACK_LOT_SIZES`.
 */
export const INDEX_CONFIG: Record<string, IndexConfig> = {
  NIFTY:      { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 75,  step: 50  },
  BANKNIFTY:  { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 30,  step: 100 },
  FINNIFTY:   { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 65,  step: 50  },
  MIDCPNIFTY: { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 120, step: 25  },
  SENSEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 20,  step: 100 },
  BANKEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 30,  step: 100 },
};

export const SYMBOLS = Object.keys(INDEX_CONFIG);
export const DEFAULT_SYMBOL = "NIFTY";
