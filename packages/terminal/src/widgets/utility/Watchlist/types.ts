/**
 * WatchlistWidget — shared types, constants, and helpers.
 */

import type { Quote } from "@/types/api";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface WatchlistItem {
  symbol:   string;
  exchange: string;
}

/** Partial quote shape from OpenAlgo — fields may be absent depending on mode */
export interface PartialQuote extends Partial<Quote> {
  prev_close?: number;
}

export type QuoteMap  = Record<string, PartialQuote>;
export type SparkMap  = Record<string, number[]>;

export interface SymbolContextMenuState {
  x:    number;
  y:    number;
  item: WatchlistItem;
}

export interface TabContextMenuState {
  x:   number;
  y:   number;
  idx: number;
}

export interface SearchResult {
  symbol:   string;
  exchange: string;
  name?:    string;
}

/** One watchlist tab */
export interface WatchlistTab {
  id:      string;
  name:    string;
  symbols: WatchlistItem[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const LS_KEY_MULTI  = "flinttrade:watchlists";
export const LS_KEY_LEGACY = "flinttrade:watchlist";

export const MAX_TABS = 5;

export const DEFAULT_SYMBOLS: WatchlistItem[] = [
  { symbol: "NIFTY",     exchange: "NSE_INDEX" },
  { symbol: "BANKNIFTY", exchange: "NSE_INDEX" },
  { symbol: "SBIN",      exchange: "NSE"       },
  { symbol: "RELIANCE",  exchange: "NSE"       },
  { symbol: "HDFCBANK",  exchange: "NSE"       },
];

/** Max sparkline history samples per symbol */
export const SPARK_MAX = 20;

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const FMT = new Intl.NumberFormat("en-IN", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  return FMT.format(Number(v));
}

export function fmtPct(v: number | null | undefined): string | null {
  if (v == null || isNaN(v)) return null;
  const n = Number(v);
  return (n >= 0 ? "+" : "") + n.toFixed(2) + "%";
}

export function generateId(): string {
  return Math.random().toString(36).slice(2, 9);
}

export function makeDefaultTab(): WatchlistTab {
  return { id: generateId(), name: "Watchlist 1", symbols: DEFAULT_SYMBOLS };
}

const watchlistItemSchema = z.object({
  symbol: z.string(),
  exchange: z.string(),
}) satisfies z.ZodType<WatchlistItem>;

const watchlistTabSchema = z.object({
  id: z.string(),
  name: z.string(),
  symbols: z.array(watchlistItemSchema),
}) satisfies z.ZodType<WatchlistTab>;

/** Load all watchlist tabs from localStorage. Migrates legacy single-list format. */
export function loadTabs(): WatchlistTab[] {
  const raw = localStorage.getItem(LS_KEY_MULTI);
  const tabs = safeParse(raw, z.array(watchlistTabSchema));
  if (tabs && tabs.length > 0) return tabs;

  // Migrate legacy single-list
  const legacyItems = safeParse(localStorage.getItem(LS_KEY_LEGACY), z.array(watchlistItemSchema));
  if (legacyItems && legacyItems.length > 0) {
    return [{ id: generateId(), name: "Watchlist 1", symbols: legacyItems }];
  }

  return [makeDefaultTab()];
}

/** Persist all watchlist tabs to localStorage. */
export function saveTabs(tabs: WatchlistTab[]): void {
  try {
    localStorage.setItem(LS_KEY_MULTI, JSON.stringify(tabs));
  } catch {
    // localStorage unavailable
  }
}
