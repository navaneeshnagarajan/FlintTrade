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

/** One symbol's netted position, aggregated across the rows the broker split. */
export interface NetPositionRow {
  symbol: string;
  underlying: string;
  exchange: string;
  netQty: number;
  avgPrice: number;
  ltp: number;
  /** Σ of the constituent rows' {@link PositionRow.mtm}. */
  mtm: number;
  /** Exposure of the NET quantity, same formula as a single row. */
  exposure: number;
  /** How many broker rows were folded into this one. */
  legs: number;
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

/**
 * Net a position book per symbol: long 2 + short 1 of one symbol is a net long
 * 1, and a symbol that nets flat is dropped — nothing of it is still at risk.
 *
 * The multi-row case is real even though the broker book is "already netted":
 * an intraday MIS leg and a delivery CNC leg of the same scrip arrive as two
 * rows, and a closed intraday position arrives as a `quantity: 0` row. Strategy
 * attribution is NOT available at this boundary (OpenAlgo does not tag
 * positions by strategy), so this nets across products and exchanges, never
 * across strategies.
 *
 * Row P&L is the SUM of the constituents' {@link PositionRow.mtm}, so the net
 * view and the table view can never report different money for the same book.
 *
 * @param rows - Normalised position rows.
 * @returns Net rows with a non-zero quantity, ordered by underlying then symbol.
 */
export function netPositions(rows: readonly PositionRow[]): NetPositionRow[] {
  interface Agg {
    underlying: string;
    exchange: string;
    qtyWeightedPrice: number;
    netQty: number;
    ltp: number;
    mtm: number;
    legs: number;
  }
  const map = new Map<string, Agg>();

  for (const row of rows) {
    const existing = map.get(row.symbol);
    if (!existing) {
      map.set(row.symbol, {
        underlying: row.underlying,
        exchange: row.exchange,
        qtyWeightedPrice: row.quantity * row.averagePrice,
        netQty: row.quantity,
        ltp: row.ltp,
        mtm: row.mtm,
        legs: 1,
      });
      continue;
    }
    existing.qtyWeightedPrice += row.quantity * row.averagePrice;
    existing.netQty += row.quantity;
    // Prefer any usable mark over a broker's zero.
    if (row.ltp > 0) existing.ltp = row.ltp;
    existing.mtm += row.mtm;
    existing.legs += 1;
  }

  const out: NetPositionRow[] = [];
  for (const [symbol, agg] of map) {
    if (agg.netQty === 0) continue; // flat — netted out
    const avgPrice = agg.qtyWeightedPrice / agg.netQty;
    out.push({
      symbol,
      underlying: agg.underlying,
      exchange: agg.exchange,
      netQty: agg.netQty,
      avgPrice,
      ltp: agg.ltp,
      mtm: agg.mtm,
      exposure: positionExposure(agg.netQty, agg.ltp, avgPrice),
      legs: agg.legs,
    });
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
