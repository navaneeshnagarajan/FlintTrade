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

export const INDEX_CONFIG: Record<string, IndexConfig> = {
  NIFTY:      { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 75,  step: 50  },
  BANKNIFTY:  { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 30,  step: 100 },
  FINNIFTY:   { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 40,  step: 50  },
  MIDCPNIFTY: { exchange: "NSE_INDEX", optExchange: "NFO",  lotSize: 50,  step: 25  },
  SENSEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 10,  step: 100 },
  BANKEX:     { exchange: "BSE_INDEX", optExchange: "BFO",  lotSize: 15,  step: 100 },
};

export const SYMBOLS = Object.keys(INDEX_CONFIG);
export const DEFAULT_SYMBOL = "NIFTY";
