/**
 * Realised-P&L helpers shared by the P&L dashboard and the Intraday P&L widget.
 *
 * The single source of truth for booked realised P&L is a per-symbol FIFO
 * pairing of BUY↔SELL legs from the tradebook. Both surfaces previously
 * carried their own copy of this loop; extracting it keeps them consistent.
 */

import type { Position, Trade } from "@/types/api";

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

/**
 * One closed round trip reconstructed from FIFO-paired fills.
 *
 * Aggregated per symbol from the first pairing fill to the moment the FIFO
 * queues exhaust one side — good enough for session statistics (win rate,
 * average hold, equity progression), not an accounting record.
 */
export interface RoundTrip {
  symbol: string;
  pnl: number;
  isWin: boolean;
  entryTime: string;
  exitTime: string;
  holdMinutes: number;
}

function timeLabel(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return iso;
  return parsed.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: false });
}

function minutesBetween(fromIso: string, toIso: string): number {
  const from = new Date(fromIso).getTime();
  const to = new Date(toIso).getTime();
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return 0;
  return Math.round((to - from) / 60_000);
}

/**
 * Reconstruct closed round trips from a session's fills.
 *
 * Same FIFO pairing as {@link realisedFromTrades}, one {@link RoundTrip} per
 * symbol whose fills produced at least one matched close-out. Symbols with
 * only opens (still-running positions) contribute nothing — this reports
 * CLOSED trades only.
 *
 * @param trades - Executed fills (any order; sorted internally by timestamp).
 * @returns Closed round trips ordered by exit time.
 */
export function roundTripsFromTrades(trades: Trade[]): RoundTrip[] {
  const bySymbol: Record<string, Trade[]> = {};
  for (const t of trades) {
    (bySymbol[t.symbol] ??= []).push(t);
  }

  const roundTrips: RoundTrip[] = [];
  for (const [symbol, legs] of Object.entries(bySymbol)) {
    const sorted = [...legs].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
    const buys = sorted
      .filter((t) => t.action === "BUY")
      .map((t) => ({ qty: t.quantity, price: t.price, ts: t.timestamp }));
    const sells = sorted
      .filter((t) => t.action === "SELL")
      .map((t) => ({ qty: t.quantity, price: t.price, ts: t.timestamp }));

    let pnl = 0;
    let matchedAny = false;
    let entryTs = "";
    let exitTs = "";
    let bi = 0;
    let si = 0;
    while (bi < buys.length && si < sells.length) {
      const matched = Math.min(buys[bi].qty, sells[si].qty);
      pnl += (sells[si].price - buys[bi].price) * matched;
      if (!matchedAny) {
        entryTs = buys[bi].ts < sells[si].ts ? buys[bi].ts : sells[si].ts;
        matchedAny = true;
      }
      exitTs = buys[bi].ts > sells[si].ts ? buys[bi].ts : sells[si].ts;
      buys[bi] = { ...buys[bi], qty: buys[bi].qty - matched };
      sells[si] = { ...sells[si], qty: sells[si].qty - matched };
      if (buys[bi].qty === 0) bi++;
      if (sells[si].qty === 0) si++;
    }

    if (matchedAny) {
      roundTrips.push({
        symbol,
        pnl,
        isWin: pnl > 0,
        entryTime: timeLabel(entryTs),
        exitTime: timeLabel(exitTs),
        holdMinutes: minutesBetween(entryTs, exitTs),
      });
    }
  }

  roundTrips.sort((a, b) => a.exitTime.localeCompare(b.exitTime));
  return roundTrips;
}

// ---------------------------------------------------------------------------
// Open-position mark-to-market
// ---------------------------------------------------------------------------

/**
 * Positionbook rows arrive unnormalised from the wire: real adapters send
 * numerics as strings and some use snake_case field names.
 */
type WirePosition = Position & {
  average_price?: string | number;
  avgPrice?: string | number;
  qty?: string | number;
};

/** Coerce a possibly string-typed broker numeric to a finite number, else null. */
function toFiniteNumber(value: unknown): number | null {
  if (value === null || value === undefined || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

/**
 * Effective P&L for a single position.
 *
 * OpenAlgo's `pnl` field is wrong for some brokers (CLAUDE.md quirk 4), so for
 * an open position this computes the mark-to-market locally as
 * `(ltp − averagePrice) × quantity` whenever those inputs are genuinely
 * available, and falls back to the broker-supplied `pnl` when the local
 * computation is impossible or untrustworthy.
 *
 * Fall-back cases (all defer to the broker figure, never fabricate one):
 *   - closed position (quantity === 0);
 *   - LTP or average price missing;
 *   - LTP ≤ 0 or average price ≤ 0 — several brokers report `ltp: 0` for an
 *     open position (an illiquid option with no trade yet, pre-market, or a
 *     positionbook that simply does not populate LTP). Treating that literal
 *     zero as valid produced a fabricated `(0 − avg) × qty` loss that overrode
 *     the correct broker figure, so non-positive inputs count as missing.
 *
 * Scope: this is the *unrealised* P&L on the currently open quantity only. A
 * position partially closed earlier in the session has booked realised P&L
 * that the positionbook cannot separate from unrealised; restore that from the
 * tradebook via {@link realisedBySymbol}.
 *
 * Extracted from the Intraday P&L widget because MTM Monitor and the P&L
 * dashboard summed the raw broker `pnl` instead, so two widgets open side by
 * side reported different totals for the same book.
 *
 * @param position - One positionbook row, possibly string-typed off the wire.
 * @returns The position's effective P&L in rupees.
 */
export function positionMtm(position: Position): number {
  // Every spelling adapters actually send. This accepted only `quantity` and
  // `averagePrice`/`average_price`, so a row shaped `qty`/`avgPrice` silently
  // fell through to the broker `pnl` field — reintroducing the very
  // disagreement this helper exists to end, but only for some adapters and
  // only in the widgets that pass raw rows.
  const wire = position as WirePosition;
  const qty = toFiniteNumber(wire.quantity ?? wire.qty) ?? 0;
  const ltp = toFiniteNumber(position.ltp);
  const avg = toFiniteNumber(wire.averagePrice ?? wire.average_price ?? wire.avgPrice);
  if (qty !== 0 && ltp !== null && ltp > 0 && avg !== null && avg > 0) {
    return (ltp - avg) * qty;
  }
  return toFiniteNumber(position.pnl) ?? 0;
}

/**
 * Total mark-to-market across a position book, using {@link positionMtm} per
 * row. The single definition of "what is my P&L right now".
 */
export function totalPositionMtm(positions: Position[]): number {
  return positions.reduce((sum, p) => sum + positionMtm(p), 0);
}
