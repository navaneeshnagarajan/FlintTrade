/**
 * tape.ts — pure tape-building and microstructure logic for the Tape &
 * Microstructure widget (W3).
 *
 * The OpenAlgo WebSocket carries quote ticks (LTP + cumulative volume), not
 * per-trade prints, so prints are INFERRED: a new print is emitted whenever the
 * LTP moves or cumulative volume increases, sized by the volume delta, with the
 * aggressor side inferred by the standard tick rule (uptick → buy, downtick →
 * sell, unchanged → previous side). The widget labels this honestly.
 *
 * `computeTapeStats` is the retired Market Microstructure widget's statistics
 * kernel, re-sourced onto these real prints. That widget generated its own
 * ticks with `Math.random()` on a 500 ms interval, so every number it displayed
 * was fabricated; the arithmetic was sound, only the input was invented. The
 * one statistic that could NOT be re-sourced here is bid/ask imbalance — the
 * quote feed carries no resting bid/ask sizes (which is precisely why the old
 * widget had to invent them), so imbalance comes from the depth endpoint via
 * `lib/depth.ts` `bookImbalance` and is omitted, never guessed, when the depth
 * feed is unavailable.
 */

import type { WsTick } from "@/types/api";

export type TapeSide = "buy" | "sell" | "neutral";

export interface TapePrint {
  id: number;
  /** Epoch milliseconds — the clock the microstructure windows are measured on. */
  ts: number;
  time: string;      // HH:MM:SS local
  price: number;
  qty: number;       // volume delta (0 when the feed gives no volume)
  side: TapeSide;
}

export interface TapeState {
  lastPrice: number | null;
  lastVolume: number | null;
  lastSide: TapeSide;
  nextId: number;
}

export function initialTapeState(): TapeState {
  return { lastPrice: null, lastVolume: null, lastSide: "neutral", nextId: 1 };
}

/**
 * Fold one quote tick into the tape. Returns the new print (or null when the
 * tick carries no new information) and the updated fold state.
 */
export function foldTick(
  state: TapeState,
  tick: Pick<WsTick, "ltp" | "volume">,
  now: Date,
): { print: TapePrint | null; state: TapeState } {
  const price = Number(tick.ltp);
  if (!Number.isFinite(price) || price <= 0) return { print: null, state };

  const cumVolume = tick.volume != null && Number.isFinite(Number(tick.volume))
    ? Number(tick.volume)
    : null;

  const priceChanged = state.lastPrice === null || price !== state.lastPrice;
  const volumeDelta = cumVolume !== null && state.lastVolume !== null
    ? Math.max(0, cumVolume - state.lastVolume)
    : 0;

  // No price move and no traded volume → nothing printed.
  if (!priceChanged && volumeDelta === 0) {
    return { print: null, state };
  }

  // Tick rule: uptick → buy aggressor, downtick → sell, flat → carry forward.
  let side: TapeSide = state.lastSide;
  if (state.lastPrice !== null) {
    if (price > state.lastPrice) side = "buy";
    else if (price < state.lastPrice) side = "sell";
  } else {
    side = "neutral";
  }

  const print: TapePrint = {
    id: state.nextId,
    ts: now.getTime(),
    time: now.toTimeString().slice(0, 8),
    price,
    qty: volumeDelta,
    side,
  };

  return {
    print,
    state: {
      lastPrice: price,
      lastVolume: cumVolume ?? state.lastVolume,
      lastSide: side,
      nextId: state.nextId + 1,
    },
  };
}

/** Prepend a print, capping the tape length (newest first). */
export function pushPrint(tape: TapePrint[], print: TapePrint, cap = 200): TapePrint[] {
  const next = [print, ...tape];
  return next.length > cap ? next.slice(0, cap) : next;
}

// ---------------------------------------------------------------------------
// Microstructure statistics (absorbed from the retired Market Microstructure
// widget, re-sourced onto real prints)
// ---------------------------------------------------------------------------

/** One-second buckets behind the velocity sparkline. */
export const VELOCITY_BUCKETS = 60;

/** Window the direction/size statistics are measured over. */
const STATS_WINDOW_MS = VELOCITY_BUCKETS * 1_000;

/** Window the headline prints-per-second rate is measured over. */
const RATE_WINDOW_MS = 10_000;

export interface TapeStats {
  /** Prints per second over the last 10 s, to one decimal place. */
  velocity: number;
  /** Prints per one-second bucket over the last 60 s; index 59 is the newest. */
  velocityHistory: number[];
  /** Share of the 60 s window whose tick-rule aggressor was a buy (uptick). */
  uptickPct: number;
  /** Share of the 60 s window whose tick-rule aggressor was a sell (downtick). */
  downtickPct: number;
  /**
   * Mean size over prints that CARRIED a size. Prints whose volume delta is 0
   * mean "the feed gave no size", not "a zero-sized trade", so folding them in
   * would report a fictitiously small average.
   */
  avgTradeSize: number;
  /** Sized prints larger than twice {@link avgTradeSize}. */
  largeOrderCount: number;
  /** Prints in the window that carried a size — 0 means sizes are unavailable. */
  sizedCount: number;
  /** Prints in the 60 s window. */
  printCount: number;
}

/** All-zero statistics — an empty tape, not a quiet one. */
export function emptyTapeStats(): TapeStats {
  return {
    velocity: 0,
    velocityHistory: new Array<number>(VELOCITY_BUCKETS).fill(0),
    uptickPct: 0,
    downtickPct: 0,
    avgTradeSize: 0,
    largeOrderCount: 0,
    sizedCount: 0,
    printCount: 0,
  };
}

/**
 * Summarise the recent tape: rate, tick-rule direction split, and trade sizes.
 *
 * Single-pass over the prints, bucketing each one by its age. The retired
 * widget re-filtered the whole tick array once per sparkline bucket — 60 full
 * scans plus four more for the aggregates — which is the same shape of mistake
 * the Tick Speed widget avoids with an O(1) counter. Here each print is touched
 * once and dropped into its bucket, so the cost is O(n) in the tape length.
 *
 * @param prints - The tape, newest first (the order {@link pushPrint} keeps).
 * @param now - Epoch milliseconds the windows are measured back from.
 * @returns Statistics over the last 60 seconds of the tape.
 */
export function computeTapeStats(
  prints: readonly TapePrint[],
  now: number = Date.now(),
): TapeStats {
  const stats = emptyTapeStats();
  if (prints.length === 0) return stats;

  const sizes: number[] = [];
  let recentCount = 0;
  let ups = 0;
  let downs = 0;
  let sizeTotal = 0;

  for (const print of prints) {
    // Clamp rather than drop: a print stamped a hair in the future (clock skew
    // between the tick arriving and this call) belongs in the newest bucket.
    const age = Math.max(0, now - print.ts);
    if (age >= STATS_WINDOW_MS) continue;

    stats.velocityHistory[VELOCITY_BUCKETS - 1 - Math.floor(age / 1_000)] += 1;
    stats.printCount += 1;
    if (age < RATE_WINDOW_MS) recentCount += 1;
    if (print.side === "buy") ups += 1;
    else if (print.side === "sell") downs += 1;
    if (print.qty > 0) {
      sizes.push(print.qty);
      sizeTotal += print.qty;
    }
  }

  if (stats.printCount === 0) return stats;

  stats.velocity = Math.round((recentCount / (RATE_WINDOW_MS / 1_000)) * 10) / 10;
  stats.uptickPct = (ups / stats.printCount) * 100;
  stats.downtickPct = (downs / stats.printCount) * 100;
  stats.sizedCount = sizes.length;

  if (sizes.length > 0) {
    stats.avgTradeSize = sizeTotal / sizes.length;
    const threshold = stats.avgTradeSize * 2;
    stats.largeOrderCount = sizes.reduce((n, qty) => (qty > threshold ? n + 1 : n), 0);
  }

  return stats;
}
