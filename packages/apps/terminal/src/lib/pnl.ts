/**
 * Realised-P&L helpers shared by the P&L dashboard and the Intraday P&L widget.
 *
 * The single source of truth for booked realised P&L is a per-symbol FIFO
 * pairing of BUY↔SELL legs from the tradebook. Both surfaces previously
 * carried their own copy of this loop; extracting it keeps them consistent.
 */

import type { Trade } from "@/types/api";

/**
 * Booked realised P&L from a set of trades, pairing BUY↔SELL legs per symbol in
 * tradebook (FIFO) order.
 *
 * Intraday-accurate only: a position opened on a prior day and closed today has
 * no matching buy leg among today's trades, so its realised is understated —
 * the same known limitation the P&L dashboard's daily series carries. Callers
 * that need a single day should pass only that day's trades.
 *
 * @param trades - Executed trades (numeric `quantity`/`price`, `action`).
 * @returns The net realised P&L across all matched round-trips.
 */
export function realisedFromTrades(trades: Trade[]): number {
  const bySymbol: Record<string, Trade[]> = {};
  for (const t of trades) {
    (bySymbol[t.symbol] ??= []).push(t);
  }

  let realised = 0;
  for (const legs of Object.values(bySymbol)) {
    const buys = legs
      .filter((t) => t.action === "BUY")
      .map((t) => ({ qty: t.quantity, price: t.price }));
    const sells = legs
      .filter((t) => t.action === "SELL")
      .map((t) => ({ qty: t.quantity, price: t.price }));

    let bi = 0;
    let si = 0;
    while (bi < buys.length && si < sells.length) {
      const matched = Math.min(buys[bi].qty, sells[si].qty);
      realised += (sells[si].price - buys[bi].price) * matched;
      buys[bi] = { ...buys[bi], qty: buys[bi].qty - matched };
      sells[si] = { ...sells[si], qty: sells[si].qty - matched };
      if (buys[bi].qty === 0) bi++;
      if (sells[si].qty === 0) si++;
    }
  }
  return realised;
}

/**
 * Booked realised P&L per symbol from a set of trades.
 *
 * Same FIFO pairing as {@link realisedFromTrades}, but keyed by symbol so a
 * caller can attribute realised amounts to individual open positions (e.g. the
 * partial closes already booked against a still-open intraday position).
 *
 * @param trades - Executed trades.
 * @returns A map of `symbol` → net realised P&L for that symbol.
 */
export function realisedBySymbol(trades: Trade[]): Map<string, number> {
  const bySymbol: Record<string, Trade[]> = {};
  for (const t of trades) {
    (bySymbol[t.symbol] ??= []).push(t);
  }
  const out = new Map<string, number>();
  for (const [symbol, legs] of Object.entries(bySymbol)) {
    out.set(symbol, realisedFromTrades(legs));
  }
  return out;
}
