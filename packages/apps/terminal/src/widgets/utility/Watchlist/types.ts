/**
 * WatchlistWidget — shared types, constants, and helpers.
 */

import type { Quote } from "@/types/api";
import { z } from "zod";
import { safeParse } from "@/lib/safeParse";
import { compileFormula, type CompiledFormula } from "./formulaEngine";

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

export type WatchlistColumnId =
  | "symbol"
  | "sparkline"
  | "price"
  | "changePct"
  | "changeAbs"
  | "volume"
  | "formula";

export type WatchlistFormulaId = "rangePct" | "openGapPct";

export interface WatchlistColumnDef {
  id: WatchlistColumnId;
  label: string;
  fixed?: boolean;
}

export interface WatchlistFormulaDef {
  id: WatchlistFormulaId;
  label: string;
}

/** A user-defined formula: a name plus an arithmetic expression over quote fields. */
export interface WatchlistCustomFormula {
  id: string;        // "custom:<generated>"
  name: string;
  expression: string;
}

export interface WatchlistViewSettings {
  visibleColumns: WatchlistColumnId[];
  /** Built-in formula id ("rangePct"/"openGapPct") or a custom formula id. */
  formula: string;
  /** User-defined formulas available for the formula column. */
  customFormulas: WatchlistCustomFormula[];
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

export const LS_KEY_MULTI  = "flinttrade:watchlists";
export const LS_KEY_LEGACY = "flinttrade:watchlist";
export const LS_KEY_VIEW   = "flinttrade:watchlist:view";

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

export const WATCHLIST_COLUMNS: WatchlistColumnDef[] = [
  { id: "symbol", label: "Symbol", fixed: true },
  { id: "sparkline", label: "Sparkline" },
  { id: "price", label: "LTP" },
  { id: "changePct", label: "% change" },
  { id: "changeAbs", label: "Net change" },
  { id: "volume", label: "Volume" },
  { id: "formula", label: "Formula" },
];

export const WATCHLIST_FORMULAS: WatchlistFormulaDef[] = [
  { id: "rangePct", label: "Range %" },
  { id: "openGapPct", label: "Open gap %" },
];

export const DEFAULT_VIEW_SETTINGS: WatchlistViewSettings = {
  visibleColumns: ["symbol", "sparkline", "price", "changePct"],
  formula: "rangePct",
  customFormulas: [],
};

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

export function fmtCompact(v: number | null | undefined): string {
  if (v == null || isNaN(v)) return "—";
  const n = Number(v);
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (Math.abs(n) >= 100_000) return `${(n / 100_000).toFixed(1)}L`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

export function formulaLabel(
  id: string,
  customFormulas: WatchlistCustomFormula[] = [],
): string {
  const builtin = WATCHLIST_FORMULAS.find((formula) => formula.id === id);
  if (builtin) return builtin.label;
  const custom = customFormulas.find((formula) => formula.id === id);
  return custom?.name ?? "Formula";
}

// Compile cache keyed by expression so each custom formula parses once, not per
// row render. ``null`` marks an expression that failed to compile.
const _formulaCache = new Map<string, CompiledFormula | null>();

function compileCached(expression: string): CompiledFormula | null {
  if (_formulaCache.has(expression)) return _formulaCache.get(expression) ?? null;
  const result = compileFormula(expression);
  const compiled = result.ok ? result.formula : null;
  _formulaCache.set(expression, compiled);
  return compiled;
}

export function evaluateFormula(
  quote: PartialQuote | null,
  formula: string,
  customFormulas: WatchlistCustomFormula[] = [],
): number | null {
  if (!quote) return null;
  const ltp = quote.ltp ?? quote.close ?? null;
  if (formula === "rangePct") {
    if (quote.high == null || quote.low == null || !ltp) return null;
    return ((Number(quote.high) - Number(quote.low)) / Number(ltp)) * 100;
  }
  if (formula === "openGapPct") {
    const prevClose = quote.prev_close ?? quote.close ?? null;
    if (quote.open == null || !prevClose) return null;
    return ((Number(quote.open) - Number(prevClose)) / Number(prevClose)) * 100;
  }
  // Custom user-defined formula, evaluated via the safe arithmetic engine.
  const custom = customFormulas.find((f) => f.id === formula);
  if (custom) {
    return compileCached(custom.expression)?.evaluate(quote) ?? null;
  }
  return null;
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

const watchlistColumnIdSchema = z.enum([
  "symbol",
  "sparkline",
  "price",
  "changePct",
  "changeAbs",
  "volume",
  "formula",
]);

const watchlistCustomFormulaSchema = z.object({
  id: z.string(),
  name: z.string(),
  expression: z.string(),
}) satisfies z.ZodType<WatchlistCustomFormula>;

const watchlistViewSchema = z.object({
  visibleColumns: z.array(watchlistColumnIdSchema),
  formula: z.string(),
  // Older persisted settings predate custom formulas; default to none.
  customFormulas: z.array(watchlistCustomFormulaSchema).optional(),
});

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

/**
 * Add a symbol to the operator's first watchlist tab.
 *
 * The single entry point for other widgets (the Scanner's "Add to watchlist"
 * button) to put a symbol on the watchlist. It exists because the Scanner
 * used to write straight to `LS_KEY_LEGACY`, which `loadTabs` only reads when
 * the canonical multi-tab key is absent — so on any already-migrated install
 * the write vanished while the button still flipped to a green "Added" badge.
 *
 * @returns true when the symbol is on the list afterwards (added or already
 *          present), false when persistence is unavailable — so the caller can
 *          avoid claiming success it cannot vouch for.
 */
export function addSymbolToWatchlist(item: WatchlistItem): boolean {
  try {
    const tabs = loadTabs();
    if (tabs.length === 0) return false;
    const target = tabs[0];
    const exists = target.symbols.some(
      (s) => s.symbol === item.symbol && s.exchange === item.exchange,
    );
    if (!exists) {
      const next = tabs.map((tab, i) =>
        i === 0 ? { ...tab, symbols: [...tab.symbols, item] } : tab,
      );
      saveTabs(next);
      // saveTabs swallows quota errors, so confirm the write landed.
      return localStorage.getItem(LS_KEY_MULTI) !== null;
    }
    return true;
  } catch {
    return false;
  }
}

export function loadViewSettings(): WatchlistViewSettings {
  const parsed = safeParse(localStorage.getItem(LS_KEY_VIEW), watchlistViewSchema);
  if (!parsed) return DEFAULT_VIEW_SETTINGS;
  const columns: WatchlistColumnId[] = parsed.visibleColumns.includes("symbol")
    ? parsed.visibleColumns
    : ["symbol", ...parsed.visibleColumns];
  return {
    visibleColumns: Array.from(new Set(columns)),
    formula: parsed.formula,
    customFormulas: parsed.customFormulas ?? [],
  };
}

export function saveViewSettings(settings: WatchlistViewSettings): void {
  try {
    localStorage.setItem(LS_KEY_VIEW, JSON.stringify(settings));
  } catch {
    // localStorage unavailable
  }
}
