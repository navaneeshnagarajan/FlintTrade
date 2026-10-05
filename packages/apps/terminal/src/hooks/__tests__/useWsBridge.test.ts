import { createElement, type ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import { createStore, Provider } from "jotai";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useTickSubscription, useWsBridge } from "../useWsBridge";
import { getWsService } from "@/services/websocket";
import { channelInstrumentAtoms } from "@/services/fdc3/channels";
const expiry = vi.hoisted(() => vi.fn());
vi.mock("@/services/api", () => ({ getExpiry: expiry }));
function harness() {
  const store = createStore();
  return { store, wrapper: ({ children }: { children: ReactNode }) => createElement(Provider, { store }, children) };
}
beforeEach(() => expiry.mockResolvedValue([]));
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
  it("balances overlapping widget interests and ignores empty instruments", () => {
    const one = renderHook(() => useTickSubscription("INFY", "NSE"));
    const two = renderHook(() => useTickSubscription("INFY", "NSE"));
    const blank = renderHook(() => useTickSubscription(null, "NSE"));
    one.unmount(); expect(getWsService().getSubscriptions("ltp")).toEqual([{ symbol: "INFY", exchange: "NSE" }]);
    two.unmount(); blank.unmount(); expect(getWsService().getSubscriptions("ltp")).toEqual([]);
  });
});
