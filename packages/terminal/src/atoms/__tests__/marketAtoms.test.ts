import { describe, it, expect } from "vitest";
import { createStore } from "jotai";
import {
  tickAtomFamily,
  niftyAtom,
} from "../marketAtoms";
import type { WsTick } from "@/types/api";

describe("marketAtoms", () => {
  it("tickAtomFamily creates unique atoms per instrument key", () => {
    const niftyTick = tickAtomFamily("NSE_INDEX:NIFTY");
    const bnfTick = tickAtomFamily("NSE_INDEX:BANKNIFTY");
    expect(niftyTick).not.toBe(bnfTick);
  });

  it("tickAtomFamily returns same atom for same key", () => {
    const a1 = tickAtomFamily("NSE_INDEX:NIFTY");
    const a2 = tickAtomFamily("NSE_INDEX:NIFTY");
    expect(a1).toBe(a2);
  });

  it("index atoms derive from tickAtomFamily", () => {
    const store = createStore();
    const tick: WsTick = {
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      ltp: 23581,
      change: 100,
      pct: 0.74,
    };
    store.set(tickAtomFamily("NSE_INDEX:NIFTY"), tick);
    const val = store.get(niftyAtom);
    expect(val?.ltp).toBe(23581);
  });
});
