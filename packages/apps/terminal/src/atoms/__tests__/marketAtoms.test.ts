import { describe, it, expect, beforeEach } from "vitest";
import { createStore } from "jotai";
import { useModeStore } from "@/stores/modeStore";
import { useBrokerStore } from "@/stores/brokerStore";
import {
  tickAtomFamily,
  niftyAtom,
} from "../marketAtoms";
import type { WsTick } from "@/types/api";

describe("marketAtoms", () => {
  function select(accountId: string, mode: "practice" | "live" = "live") {
    useModeStore.setState({ mode });
    useBrokerStore.setState({ accounts: [{ account_id: accountId, broker: "dhan", source: "native", label: "Test", status: "connected", connected_at: null, error_message: null, is_primary: true }], activeAccountId: `native:dhan:${accountId}` });
  }
  beforeEach(() => { select("A1"); });
  const observation: WsTick = { symbol: "NIFTY", exchange: "NSE_INDEX", ltp: 23581 };

  it("retires an unmounted cached observation synchronously and cannot resurrect it on return to A", () => {
    const store = createStore();
    store.set(niftyAtom, observation, "live:native:dhan:A1");
    expect(store.get(niftyAtom)).toEqual(observation);
    select("B1");
    expect(store.get(niftyAtom)).toBeNull();
    select("A1");
    expect(store.get(niftyAtom)).toBeNull();
    store.set(niftyAtom, { ...observation, ltp: 24000 }, "live:native:dhan:A1");
    expect(store.get(niftyAtom)?.ltp).toBe(24000);
  });
  it("notifies mounted readers before the first B render and rejects a late A publication", () => {
    const store = createStore();
    const values: Array<WsTick | null> = [];
    const stop = store.sub(niftyAtom, () => values.push(store.get(niftyAtom)));
    store.set(niftyAtom, observation, "live:native:dhan:A1");
    select("B1");
    expect(values.at(-1)).toBeNull();
    store.set(niftyAtom, observation, "live:native:dhan:A1");
    expect(store.get(niftyAtom)).toBeNull();
    stop();
  });
  it("never merges an old-account prior close into a fresh B price", () => {
    const store = createStore();
    store.set(niftyAtom, { ...observation, prevClose: 23000 }, "live:native:dhan:A1");
    select("B1");
    store.set(niftyAtom, (previous) => ({ ...observation, prevClose: previous?.prevClose }), "live:native:dhan:B1");
    expect(store.get(niftyAtom)?.prevClose).toBeUndefined();
  });
  it("keeps Example ticks in Example and refuses their late Practice publication", () => {
    const store = createStore();
    useModeStore.setState({ mode: "explore" });
    store.set(niftyAtom, observation, "explore:mock");
    expect(store.get(niftyAtom)).toEqual(observation);
    select("A1", "practice");
    expect(store.get(niftyAtom)).toBeNull();
    store.set(niftyAtom, observation, "explore:mock");
    expect(store.get(niftyAtom)).toBeNull();
    useModeStore.setState({ mode: "explore" });
    expect(store.get(niftyAtom)).toBeNull();
  });
  it("keeps separate Jotai stores while retiring both stores' old authority", () => {
    const first = createStore();
    const second = createStore();
    first.set(niftyAtom, observation, "live:native:dhan:A1");
    second.set(niftyAtom, { ...observation, ltp: 24100 }, "live:native:dhan:A1");
    expect(first.get(niftyAtom)?.ltp).toBe(23581);
    expect(second.get(niftyAtom)?.ltp).toBe(24100);
    select("B1");
    expect(first.get(niftyAtom)).toBeNull();
    expect(second.get(niftyAtom)).toBeNull();
  });
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
