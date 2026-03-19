import { atom } from "jotai";
import { atomFamily } from "jotai/utils";
import type { WsTick, WsInstrument } from "@/types/api";

/**
 * Atom family for per-instrument tick data.
 * Key format: "{exchange}:{symbol}" e.g. "NSE_INDEX:NIFTY"
 */
export const tickAtomFamily = atomFamily(
  (_key: string) => atom<WsTick | null>(null)
);

// Derived index atoms (convenience)
export const niftyAtom = tickAtomFamily("NSE_INDEX:NIFTY");
export const sensexAtom = tickAtomFamily("BSE_INDEX:SENSEX");
export const bankniftyAtom = tickAtomFamily("NSE_INDEX:BANKNIFTY");
export const vixAtom = tickAtomFamily("NSE_INDEX:INDIAVIX");

/**
 * Derived atom: indices summary for TickerBar
 */
export const indicesSummaryAtom = atom((get) => {
  return [
    { name: "NIFTY 50", data: get(niftyAtom) },
    { name: "SENSEX", data: get(sensexAtom) },
    { name: "BANK NIFTY", data: get(bankniftyAtom) },
    { name: "VIX", data: get(vixAtom) },
  ];
});

/**
 * Selected symbol atom — set by WatchlistWidget when a row is clicked.
 * Other widgets (Chart, Depth, Greeks, etc.) can subscribe to react.
 */
export const selectedSymbolAtom = atom<WsInstrument | null>(null);
