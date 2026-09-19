/**
 * FT-TRADE-011 — one shared symbol source of truth.
 *
 * Watchlist broadcasts on the FDC3 red user channel. That atom IS
 * `selectedSymbolAtom`, so Chart, Option Chain, and Scalper follow the
 * same instrument without a second bus. An empty watchlist never writes,
 * so followers keep their local defaults.
 */

import { describe, expect, it } from "vitest";
import { createStore } from "jotai";
import { selectedSymbolAtom } from "@/atoms/marketAtoms";
import {
  broadcastInstrument,
  channelInstrumentAtoms,
  DEFAULT_CHANNEL_ID,
} from "../channels";

const BANKNIFTY = { symbol: "BANKNIFTY", exchange: "NSE_INDEX" };

describe("FT-TRADE-011 shared symbol bus", () => {
  it("uses one source of truth: the red channel aliases selectedSymbolAtom", () => {
    expect(channelInstrumentAtoms[DEFAULT_CHANNEL_ID]).toBe(selectedSymbolAtom);
  });

  it("starts empty so an empty watchlist cannot silently retarget followers", () => {
    const store = createStore();
    expect(store.get(selectedSymbolAtom)).toBeNull();
    expect(store.get(channelInstrumentAtoms[DEFAULT_CHANNEL_ID])).toBeNull();
  });

  it("a Watchlist-style broadcast is readable from either name", () => {
    const store = createStore();
    broadcastInstrument(store, DEFAULT_CHANNEL_ID, BANKNIFTY);
    expect(store.get(selectedSymbolAtom)).toEqual(BANKNIFTY);
    expect(store.get(channelInstrumentAtoms[DEFAULT_CHANNEL_ID])).toEqual(BANKNIFTY);
  });
});
