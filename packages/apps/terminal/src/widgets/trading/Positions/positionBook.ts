/**
 * positionBook.ts — the one kernel behind all three Positions views.
 *
 * The table, the net view and the heat map are three renderings of ONE broker
 * position book (one `usePositions` read of one scope). Before the merge each
 * rendering normalised the wire rows itself and each answered the same two
 * questions differently:
 *
 *   - EXPOSURE was computed three ways — `qty × avgPrice` (Net Position),
 *     `|qty × ltp|` (Portfolio Allocation) and `|qty| × (ltp || entry)`
 *     (Position Heat Map).
 *   - P&L was computed two ways — the broker's `pnl` field summed (Positions,
 *     Heat Map) versus a local `(ltp − avg) × qty × lotSize` recomputation
 *     (Net Position), which disagree the moment a position is partially closed
 *     or the broker's `pnl` field is one of the wrong ones.
 *
 * Both are settled here, once:
 *
 *   P&L    → {@link positionMtm} from `lib/pnl.ts`, the repo-wide definition.
 *            It IS Net Position's recomputation `(ltp − avg) × qty` (the
 *            `lotSize` term is gone because broker quantities are already in
 *            units and Net Position forced `lotSize: 1` on every live row), plus
 *            a fail-safe: when LTP or average price is missing or non-positive
 *            it defers to the broker's figure instead of fabricating a loss.
 *            So there is no honest "two definitions" choice left to offer the
 *            operator — one is the other's bug.
 *
 *   EXPOSURE → |qty| × (ltp > 0 ? ltp : averagePrice). See
 *            {@link positionExposure}.
 */

import { positionMtm } from "@/lib/pnl";
import { isRestoredFromBackup } from "@/lib/restoredFills";
import { classifySector, symbolRoot } from "@/lib/sectors";
import type { Position } from "@/types/api";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * One broker position row, normalised. Extends {@link Position} so the shared
 * P&L helpers in `lib/pnl.ts` accept it directly.
 */
export interface PositionRow extends Position {
  /** The single mark-to-market figure for this row ({@link positionMtm}). */
  mtm: number;
  /** The single exposure figure for this row ({@link positionExposure}). */
  exposure: number;
  /** Sector from `lib/sectors.ts` — the single classification source. */
  sector: string;
  /** Instrument root: "NIFTY24APR22500CE" → "NIFTY". */
  underlying: string;
}

/**
 * One net-view row.
 *
 * A symbol whose quantity is still open across products is one aggregated row.
 * An offset symbol (legs that net to 0, with at least one open leg) is one row
 * per open leg — Indian brokers do not net MIS against NRML or CNC, so each
 * leg keeps its own quantity and margin.
 */
export interface NetPositionRow {
  symbol: string;
  underlying: string;
  exchange: string;
  netQty: number;
  avgPrice: number;
  ltp: number;
  /** Σ of the constituent rows' {@link PositionRow.mtm}, or this leg's own. */
  mtm: number;
  /** Exposure of the net quantity, or of this open leg when the symbol is offset. */
  exposure: number;
  /** How many broker rows were folded into this one. One for an offset leg. */
  legs: number;
  /** True on each open leg of a symbol whose legs net to 0. */
  offset?: boolean;
  /** Product of this offset leg. Absent on an aggregated row. */
  product?: string;
  /** Products of the open legs, in book order, for the Offset tooltip. */
  offsetProducts?: readonly string[];
}

/** How a symbol's legs sit at the broker. */
export type SymbolLegClass = "flat" | "offset" | "open";

/** Stable key for one broker row, shared by the table and the heat map. */
export function positionRowKey(row: { symbol: string; product: string; exchange: string }): string {
  return `${row.symbol}:${row.product}:${row.exchange}`;
}

// ---------------------------------------------------------------------------
// Wire normalisation
// ---------------------------------------------------------------------------

/** Coerce a possibly string-typed, possibly absent broker numeric. */
function num(value: unknown): number {
  if (value === null || value === undefined || value === "") return 0;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function str(value: unknown): string {
  return value === null || value === undefined ? "" : String(value);
}

/**
 * Exposure — the market value currently at risk in a position.
 *
 * `|qty| × LTP`, falling back to the average price only when LTP is missing or
 * non-positive. Chosen over Net Position's `|qty| × avgPrice` because exposure
 * asks what the position is worth NOW, not what it cost; cost basis does not
 * move when the market does, so a position that has doubled would have gone on
 * reporting its entry-day risk. The fallback is not cosmetic: several brokers
 * report `ltp: 0` on an open position (illiquid option, pre-market, or a
 * positionbook that simply never populates LTP), and a 0 exposure would
 * silently shrink a real position out of the heat map and out of the totals.
 *
 * @param quantity - Signed position quantity, in units.
 * @param ltp - Last traded price (0 or negative means "not available").
 * @param averagePrice - Entry price, used only as the fallback mark.
 * @returns Exposure in rupees, always non-negative.
 */
export function positionExposure(quantity: number, ltp: number, averagePrice: number): number {
  const mark = ltp > 0 ? ltp : Math.max(averagePrice, 0);
  return Math.abs(quantity) * mark;
}

/**
 * Normalise one positionbook row.
 *
 * Real adapters send numerics as strings and mix snake_case with camelCase, so
 * every field is resolved through both spellings before any arithmetic.
 */
export function normalisePosition(raw: unknown): PositionRow {
  const wire = (raw ?? {}) as Record<string, unknown>;
  const symbol = str(wire["symbol"]);
  const quantity = num(wire["quantity"] ?? wire["qty"]);
  const averagePrice = num(wire["averagePrice"] ?? wire["average_price"] ?? wire["avgPrice"]);
  const ltp = num(wire["ltp"]);

  const base: Position = {
    symbol,
    exchange: str(wire["exchange"]),
    product: str(wire["product"]),
    quantity,
    averagePrice,
    ltp,
    pnl: num(wire["pnl"]),
    pnlPercent: num(wire["pnlPercent"] ?? wire["pnl_percent"]),
  };

  // Derive P&L% only when the broker sent none AND both legs of the division
  // are real. The heat map used to guard on `entry > 0` alone, so a row with
  // `ltp: 0` was painted a fabricated −100%.
  const pnlPercent =
    base.pnlPercent !== 0
      ? base.pnlPercent
      : averagePrice > 0 && ltp > 0 && quantity !== 0
        ? ((ltp - averagePrice) / averagePrice) * 100 * Math.sign(quantity)
        : 0;

  return {
    ...base,
    pnlPercent,
    mtm: positionMtm(base),
    exposure: positionExposure(quantity, ltp, averagePrice),
    sector: classifySector(symbol),
    underlying: underlyingOf(symbol),
    restored: wire["restored"] === true || isRestoredFromBackup(str(wire["strategy"])),
  };
}

/** Normalise a whole positionbook payload, dropping rows without a symbol. */
export function normalisePositions(raw: readonly unknown[] | undefined | null): PositionRow[] {
  return (raw ?? []).map(normalisePosition).filter((row) => row.symbol.length > 0);
}

// ---------------------------------------------------------------------------
// Netting
// ---------------------------------------------------------------------------

/**
 * The underlying a row belongs to, used as the net view's group key.
 *
 * Shares `lib/sectors.ts`'s {@link symbolRoot} so a symbol cannot be grouped
 * under one root and classified under another. The retired widget split on
 * whitespace alone, which worked on its own sample ("NIFTY 22200 CE 10APR")
 * and was a no-op on every real broker symbol ("NIFTY24APR22500CE"), so live
 * grouping never actually grouped anything.
 */
export function underlyingOf(symbol: string): string {
  return symbolRoot(symbol) || symbol;
}

/** Legs of one symbol, in the order the book listed them. */
function legsBySymbol(rows: readonly PositionRow[]): Map<string, PositionRow[]> {
  const map = new Map<string, PositionRow[]>();
  for (const row of rows) {
    const bucket = map.get(row.symbol);
    if (bucket) bucket.push(row);
    else map.set(row.symbol, [row]);
  }
  return map;
}

/**
 * Classify one symbol's legs the way an Indian broker carries them.
 *
 * Flat means every leg is at quantity 0 — nothing is still open. Offset means
 * the quantities net to 0 but at least one leg is still open: MIS does not
 * cancel NRML or CNC, and each open leg keeps its own margin. Anything else
 * is a single open net.
 *
 * @param legs - Broker rows for one symbol.
 * @returns `flat`, `offset`, or `open`.
 */
export function classifySymbolLegs(legs: readonly PositionRow[]): SymbolLegClass {
  if (!legs.some((leg) => leg.quantity !== 0)) return "flat";
  const net = legs.reduce((sum, leg) => sum + leg.quantity, 0);
  return net === 0 ? "offset" : "open";
}

/** Open-leg products in book order, each product once. */
export function offsetProductsOf(legs: readonly PositionRow[]): string[] {
  const products: string[] = [];
  for (const leg of legs) {
    if (leg.quantity === 0) continue;
    const name = leg.product.trim();
    if (name.length === 0 || products.includes(name)) continue;
    products.push(name);
  }
  return products;
}

/**
 * Tooltip for an Offset tag.
 *
 * Names the products in book order. When one of them is MIS and another
 * product is still open, says which leg the intraday square-off leaves
 * behind. Two non-MIS products get only the first sentence.
 *
 * @param products - Open-leg products in book order.
 * @returns The operator-facing sentence.
 */
export function offsetLegTooltip(products: readonly string[]): string {
  const unique: string[] = [];
  for (const product of products) {
    const name = product.trim();
    if (name.length === 0 || unique.includes(name)) continue;
    unique.push(name);
  }
  const [first, second] = unique;
  const intro = second
    ? `${first} and ${second} legs don't cancel at your broker.`
    : `${first ?? "These"} legs don't cancel at your broker.`;
  const other = unique.find((product) => product !== "MIS");
  if (unique.includes("MIS") && other) {
    return `${intro} At intraday square-off the MIS leg closes and the ${other} leg stays open.`;
  }
  return intro;
}

/** How many symbols in the book are flat, and how many are offset. */
export function countSymbolClasses(rows: readonly PositionRow[]): { flatSymbols: number; offsetSymbols: number } {
  let flatSymbols = 0;
  let offsetSymbols = 0;
  for (const legs of legsBySymbol(rows).values()) {
    const kind = classifySymbolLegs(legs);
    if (kind === "flat") flatSymbols += 1;
    else if (kind === "offset") offsetSymbols += 1;
  }
  return { flatSymbols, offsetSymbols };
}

function aggregateOpenLegs(symbol: string, legs: readonly PositionRow[]): NetPositionRow {
  let underlying = legs[0]?.underlying ?? symbol;
  let exchange = legs[0]?.exchange ?? "";
  let qtyWeightedPrice = 0;
  let netQty = 0;
  let ltp = 0;
  let mtm = 0;
  for (const leg of legs) {
    underlying = leg.underlying;
    exchange = leg.exchange;
    qtyWeightedPrice += leg.quantity * leg.averagePrice;
    netQty += leg.quantity;
    if (leg.ltp > 0) ltp = leg.ltp;
    mtm += leg.mtm;
  }
  const avgPrice = netQty === 0 ? 0 : qtyWeightedPrice / netQty;
  return {
    symbol,
    underlying,
    exchange,
    netQty,
    avgPrice,
    ltp,
    mtm,
    exposure: positionExposure(netQty, ltp, avgPrice),
    legs: legs.length,
  };
}

/**
 * Net a position book per symbol.
 *
 * Long 2 + short 1 of one symbol, when the net quantity is still open, is one
 * net long. A symbol whose legs are all at quantity 0 is flat and dropped.
 * A symbol whose legs net to 0 but still has an open leg is offset: each open
 * leg stays as its own row, with its own quantity and margin. Brokers do not
 * net MIS against NRML or CNC, and an intraday square-off closes only the MIS
 * leg.
 *
 * Strategy attribution is not available at this boundary, so an open (non-zero)
 * net still folds products of one symbol into one row. Offset never does.
 *
 * @param rows - Normalised position rows.
 * @returns Net rows ordered by underlying then symbol, offset legs in book order.
 */
export function netPositions(rows: readonly PositionRow[]): NetPositionRow[] {
  const out: NetPositionRow[] = [];
  for (const [symbol, legs] of legsBySymbol(rows)) {
    const kind = classifySymbolLegs(legs);
    if (kind === "flat") continue;
    if (kind === "offset") {
      const products = offsetProductsOf(legs);
      for (const leg of legs) {
        if (leg.quantity === 0) continue;
        out.push({
          symbol: leg.symbol,
          underlying: leg.underlying,
          exchange: leg.exchange,
          netQty: leg.quantity,
          avgPrice: leg.averagePrice,
          ltp: leg.ltp,
          mtm: leg.mtm,
          exposure: leg.exposure,
          legs: 1,
          offset: true,
          product: leg.product,
          offsetProducts: products,
        });
      }
      continue;
    }
    out.push(aggregateOpenLegs(symbol, legs));
  }

  return out.sort(
    (a, b) => a.underlying.localeCompare(b.underlying) || a.symbol.localeCompare(b.symbol),
  );
}

/** Group net rows by underlying, preserving the sorted order. */
export function groupByUnderlying(rows: readonly NetPositionRow[]): Map<string, NetPositionRow[]> {
  const map = new Map<string, NetPositionRow[]>();
  for (const row of rows) {
    const bucket = map.get(row.underlying) ?? [];
    bucket.push(row);
    map.set(row.underlying, bucket);
  }
  return map;
}

// ---------------------------------------------------------------------------
// Formatting — shared by all three views so one book reads the same everywhere
// ---------------------------------------------------------------------------

const INR = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 2 });

/**
 * Signed rupee P&L. A loss carries its minus sign: the table used to render
 * `Math.abs(pnl)` for negatives, so a ₹800 loss displayed as "₹800".
 */
export function fmtPnl(value: number): string {
  return `${value >= 0 ? "+" : "-"}₹${INR.format(Math.abs(value))}`;
}

/** Price with two decimals, Indian digit grouping. */
export function fmtPrice(value: number): string {
  return value.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Compact rupee exposure — ₹1.2L / ₹12.3K / ₹450. */
export function fmtExposure(value: number): string {
  if (value >= 1_000_000) return `₹${(value / 100_000).toFixed(1)}L`;
  if (value >= 1_000) return `₹${(value / 1_000).toFixed(1)}K`;
  return `₹${value.toFixed(0)}`;
}

/** Signed percentage, two decimals. */
export function fmtPnlPct(value: number): string {
  return `${value >= 0 ? "+" : ""}${value.toFixed(2)}%`;
}

/** Time-of-day in IST, used by the last-updated chip. */
export function fmtUpdatedAt(ms: number): string {
  return new Date(ms).toLocaleTimeString("en-IN", { timeZone: "Asia/Kolkata", hour12: false });
}
