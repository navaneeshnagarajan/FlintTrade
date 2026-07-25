/**
 * Market-depth normalisation shared by every level-2 surface.
 *
 * Broker bridges disagree about depth field names: a level may arrive as
 * `{ price, quantity, orders }`, `{ p, qty, num_orders }`, or `{ price, q, o }`,
 * and the two sides may be keyed `bids`/`asks` or `buy`/`sell`. Only the Depth
 * widget ever handled those aliases; the DOM Heatmap assumed the typed shape
 * and therefore rendered an empty heatmap — silently, with no error — against
 * any bridge that emitted the short field names.
 *
 * Extracting this makes the alias handling one implementation that every depth
 * consumer gets, rather than a capability that happened to live in one widget.
 */

/** A normalised depth level: finite numbers, canonical field names. */
export interface DepthLevel {
  price: number;
  qty: number;
  orders: number;
}

/** Normalised two-sided book. */
export interface NormalisedDepth {
  bids: DepthLevel[];
  asks: DepthLevel[];
}

/** Raw level shape off the wire — field names vary across brokers. */
export interface RawDepthLevel {
  price?: number | string;
  p?: number | string;
  quantity?: number | string;
  qty?: number | string;
  q?: number | string;
  orders?: number | string;
  num_orders?: number | string;
  o?: number | string;
}

/** Raw depth response off the wire. */
export interface RawDepth {
  bids?: RawDepthLevel[];
  asks?: RawDepthLevel[];
  buy?: RawDepthLevel[];
  sell?: RawDepthLevel[];
}

/** Coerce a possibly string-typed wire numeric to a finite number, else 0. */
function num(value: unknown): number {
  if (value === null || value === undefined || value === "") return 0;
  const n = Number(value);
  return Number.isFinite(n) ? n : 0;
}

/**
 * Normalise a raw depth payload into canonical bid/ask ladders.
 *
 * @param raw - The broker's depth payload, in any of the known shapes.
 * @param levels - Maximum levels to keep per side (default 5, the usual L2 depth).
 * @returns Canonical bids and asks; empty arrays when the payload is absent
 *          or malformed, never a partially-coerced level.
 */
export function normaliseDepth(
  raw: RawDepth | null | undefined,
  levels = 5,
): NormalisedDepth {
  if (!raw) return { bids: [], asks: [] };

  const rawBids: RawDepthLevel[] = raw.bids ?? raw.buy ?? [];
  const rawAsks: RawDepthLevel[] = raw.asks ?? raw.sell ?? [];

  const norm = (arr: RawDepthLevel[]): DepthLevel[] =>
    Array.isArray(arr)
      ? arr.map((lvl) => ({
          price: num(lvl.price ?? lvl.p),
          qty: num(lvl.quantity ?? lvl.qty ?? lvl.q),
          orders: num(lvl.orders ?? lvl.num_orders ?? lvl.o),
        }))
      : [];

  return {
    bids: norm(rawBids).slice(0, levels),
    asks: norm(rawAsks).slice(0, levels),
  };
}

/**
 * Signed order-book imbalance in the range −1 … +1.
 *
 * Positive means bid-heavy. Four different formulations of this metric existed
 * across the depth family (a 0–100 percentage, a signed ratio, a 0–1 fraction,
 * and one computed over traded rather than resting volume), so three widgets
 * could show three different numbers for the same book. This is the signed
 * definition; render it as a percentage where a percentage is wanted.
 *
 * @returns The imbalance, or 0 when there is no resting volume on either side.
 */
export function bookImbalance(bids: DepthLevel[], asks: DepthLevel[]): number {
  const bidQty = bids.reduce((sum, l) => sum + l.qty, 0);
  const askQty = asks.reduce((sum, l) => sum + l.qty, 0);
  const total = bidQty + askQty;
  if (total <= 0) return 0;
  return (bidQty - askQty) / total;
}
