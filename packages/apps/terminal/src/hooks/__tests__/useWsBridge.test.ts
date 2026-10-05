import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTickSubscription, useWsBridge } from "../useWsBridge";
import { getWsService } from "@/services/websocket";
import { channelInstrumentAtoms } from "@/services/fdc3/channels";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";
import type { BrokerAccount } from "@/types/broker";
const expiry = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({ getExpiry: expiry }));
function harness() {
  const store = createStore();
  return { store, wrapper: ({ children }: { children: ReactNode }) => createElement(Provider, { store }, children) };
}
const accountA: BrokerAccount = {
  source: "native", broker: "dhan", account_id: "shared", label: "A", status: "connected",
  connected_at: null, error_message: null, is_primary: false,
};
const accountB: BrokerAccount = { ...accountA, broker: "upstox", label: "B" };
function deferredExpiries() {
  const requests: Array<{ signal: AbortSignal; scope: string; resolve: (result: { expiry: string[] }) => void }> = [];
  expiry.mockImplementation((_symbol, _exchange, _type, signal, scope) => new Promise((resolve) => {
    requests.push({ signal, scope, resolve });
  }));
  const complete = async (start: number, date: string) => {
    await act(async () => {
      requests.slice(start, start + 4).forEach((request) => request.resolve({ expiry: [date] }));
    });
  };
  return { requests, complete };
}
beforeEach(() => {
  expiry.mockResolvedValue([]);
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ accounts: [accountA, accountB], activeAccountId: brokerAccountKey(accountA) });
});
afterEach(() => {
  vi.clearAllMocks();
  const feed = getWsService();
  for (const { instrument, mode } of feed.getAllSubscriptions()) feed.unsubscribe([instrument], mode);
});
describe("native polling interests", () => {
  it("registers the index strip and releases its own interests on unmount", () => {
    const { wrapper } = harness();
    const { unmount } = renderHook(() => useWsBridge(), { wrapper });
    expect(getWsService().getSubscriptions("ltp")).toEqual(expect.arrayContaining([
      { symbol: "NIFTY", exchange: "NSE_INDEX" }, { symbol: "SENSEX", exchange: "BSE_INDEX" },
    ]));
    unmount(); expect(getWsService().getAllSubscriptions()).toEqual([]);
  });
  it("gates brokerless sessions and does not open a socket", () => {
    const socket = vi.fn(); vi.stubGlobal("WebSocket", socket);
    const { wrapper } = harness();
    const { unmount } = renderHook(() => useWsBridge(false), { wrapper });
    expect(getWsService().getAllSubscriptions()).toEqual([]);
    expect(expiry).not.toHaveBeenCalled(); expect(socket).not.toHaveBeenCalled();
    unmount(); vi.unstubAllGlobals();
  });
  it("tracks each channel selection and removes the previous instrument", () => {
    const { store, wrapper } = harness();
    const { unmount } = renderHook(() => useWsBridge(), { wrapper });
    act(() => store.set(channelInstrumentAtoms["fdc3.channel.red"], { symbol: "INFY", exchange: "NSE" }));
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "INFY", exchange: "NSE" });
    act(() => store.set(channelInstrumentAtoms["fdc3.channel.red"], { symbol: "RELIANCE", exchange: "NSE" }));
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual({ symbol: "INFY", exchange: "NSE" });
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "RELIANCE", exchange: "NSE" });
    unmount(); expect(getWsService().getAllSubscriptions()).toEqual([]);
  });
  it("resolves and registers nearest commodity futures without owning a socket", async () => {
    expiry.mockResolvedValue(["02-APR-26"]);
    const { wrapper } = harness();
    const { unmount } = renderHook(() => useWsBridge(), { wrapper });
    await waitFor(() => expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" }));
    unmount(); expect(getWsService().getAllSubscriptions()).toEqual([]);
  });
  it("does not add late commodity interests after unmount", async () => {
    let resolve!: (value: string[]) => void;
    expiry.mockReturnValue(new Promise<string[]>((done) => { resolve = done; }));
    const { wrapper } = harness();
    const { unmount } = renderHook(() => useWsBridge(), { wrapper });
    unmount(); await act(async () => { resolve(["02-APR-26"]); });
    expect(getWsService().getAllSubscriptions()).toEqual([]);
  });
  it("re-resolves futures for the exact new native account while remaining enabled", async () => {
    const { requests, complete } = deferredExpiries();
    const { wrapper } = harness();
    const hook = renderHook(() => useWsBridge(), { wrapper });
    await complete(0, "02-APR-26");
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" });

    act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB)));
    expect(requests).toHaveLength(8);
    expect(requests.slice(0, 4).every((request) => request.signal.aborted)).toBe(true);
    expect(requests.slice(4).every((request) => request.scope === "live:native:upstox:shared")).toBe(true);
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" });
    await complete(4, "04-MAY-26");
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD04MAY26FUT", exchange: "MCX" });
    hook.unmount();
    expect(getWsService().getAllSubscriptions()).toEqual([]);
  });

  it.each(["practice", "explore"] as const)("retires pending Live resolution on the first %s scope", async (mode) => {
    const { requests, complete } = deferredExpiries();
    const { wrapper } = harness();
    const hook = renderHook(() => useWsBridge(), { wrapper });
    act(() => useModeStore.getState().setMode(mode));
    expect(requests).toHaveLength(8);
    expect(requests.slice(4).every((request) => request.scope === (mode === "explore" ? "explore:mock" : "practice:native:dhan:shared"))).toBe(true);
    await complete(4, "04-MAY-26");
    await complete(0, "02-APR-26");
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" });
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD04MAY26FUT", exchange: "MCX" });
    hook.unmount();
  });

  it("rejects a retired A resolution after a batched A → B → A return", async () => {
    const { requests, complete } = deferredExpiries();
    const { wrapper } = harness();
    const hook = renderHook(() => useWsBridge(), { wrapper });
    act(() => {
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB));
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountA));
    });
    expect(requests).toHaveLength(8);
    await complete(0, "02-APR-26");
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" });
    await complete(4, "03-JUN-26");
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD03JUN26FUT", exchange: "MCX" });
    hook.unmount();
  });

  it("refuses cancelled StrictMode resolutions and balances the surviving interests", async () => {
    const { requests, complete } = deferredExpiries();
    const { wrapper } = harness();
    const hook = renderHook(() => useWsBridge(), { wrapper, reactStrictMode: true });
    expect(requests).toHaveLength(8);
    expect(requests.slice(0, 4).every((request) => request.signal.aborted)).toBe(true);
    await complete(0, "02-APR-26");
    expect(getWsService().getSubscriptions("ltp")).not.toContainEqual({ symbol: "GOLD02APR26FUT", exchange: "MCX" });
    await complete(4, "04-MAY-26");
    expect(getWsService().getSubscriptions("ltp")).toContainEqual({ symbol: "GOLD04MAY26FUT", exchange: "MCX" });
    hook.unmount();
    expect(requests.slice(4).every((request) => request.signal.aborted)).toBe(true);
    expect(getWsService().getAllSubscriptions()).toEqual([]);
  });
  it("balances overlapping widget interests and ignores empty instruments", () => {
    const one = renderHook(() => useTickSubscription("INFY", "NSE"));
    const two = renderHook(() => useTickSubscription("INFY", "NSE"));
    const blank = renderHook(() => useTickSubscription(null, "NSE"));
    one.unmount(); expect(getWsService().getSubscriptions("ltp")).toEqual([{ symbol: "INFY", exchange: "NSE" }]);
    two.unmount(); blank.unmount(); expect(getWsService().getSubscriptions("ltp")).toEqual([]);
  });
});
