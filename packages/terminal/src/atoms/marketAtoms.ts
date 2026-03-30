import { atom } from "jotai";
import type { WsTick, WsInstrument } from "@/types/api";

/**
 * Atom cache for per-instrument tick data.
 * Key format: "{exchange}:{symbol}" e.g. "NSE_INDEX:NIFTY"
 *
 * Using a plain Map instead of atomFamily (deprecated in jotai/utils, removed in v3).
 * Interface is identical — callers use tickAtomFamily("NSE_INDEX:NIFTY") unchanged.
 */
const _tickAtomCache = new Map<string, ReturnType<typeof atom<WsTick | null>>>();

export function tickAtomFamily(key: string): ReturnType<typeof atom<WsTick | null>> {
  let existing = _tickAtomCache.get(key);
  if (!existing) {
    existing = atom<WsTick | null>(null);
    _tickAtomCache.set(key, existing);
  }
  return existing;
}

// Derived index atoms (convenience)
export const niftyAtom = tickAtomFamily("NSE_INDEX:NIFTY");
export const sensexAtom = tickAtomFamily("BSE_INDEX:SENSEX");
export const bankniftyAtom = tickAtomFamily("NSE_INDEX:BANKNIFTY");
export const vixAtom = tickAtomFamily("NSE_INDEX:INDIAVIX");

// MCX commodity atoms
export const goldAtom = tickAtomFamily("MCX:GOLD");
export const silverAtom = tickAtomFamily("MCX:SILVER");
export const crudeOilAtom = tickAtomFamily("MCX:CRUDEOIL");
export const naturalGasAtom = tickAtomFamily("MCX:NATURALGAS");

/**
 * Derived atom: indices + MCX summary for TickerBar
 * Matches Groww 915 ticker: NIFTY, SENSEX, BANKNIFTY, VIX + GOLD, SILVER, CRUDEOIL, NATURALGAS
 */
export const indicesSummaryAtom = atom((get) => {
  return [
    { name: "NIFTY 50", data: get(niftyAtom) },
    { name: "SENSEX", data: get(sensexAtom) },
    { name: "BANK NIFTY", data: get(bankniftyAtom) },
    { name: "VIX", data: get(vixAtom) },
    { name: "GOLD", data: get(goldAtom) },
    { name: "SILVER", data: get(silverAtom) },
    { name: "CRUDEOIL", data: get(crudeOilAtom) },
    { name: "NATGAS", data: get(naturalGasAtom) },
  ];
});

/**
 * Selected symbol atom — set by WatchlistWidget when a row is clicked.
 * Other widgets (Chart, Depth, Greeks, etc.) can subscribe to react.
 */
export const selectedSymbolAtom = atom<WsInstrument | null>(null);
