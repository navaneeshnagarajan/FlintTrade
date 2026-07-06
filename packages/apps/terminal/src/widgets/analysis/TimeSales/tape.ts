/**
 * tape.ts — pure tape-building logic for the Time & Sales widget (W3).
 *
 * The OpenAlgo WebSocket carries quote ticks (LTP + cumulative volume), not
 * per-trade prints, so prints are INFERRED: a new print is emitted whenever the
 * LTP moves or cumulative volume increases, sized by the volume delta, with the
 * aggressor side inferred by the standard tick rule (uptick → buy, downtick →
 * sell, unchanged → previous side). The widget labels this honestly.
 */

import type { WsTick } from "@/types/api";

export type TapeSide = "buy" | "sell" | "neutral";

export interface TapePrint {
  id: number;
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
