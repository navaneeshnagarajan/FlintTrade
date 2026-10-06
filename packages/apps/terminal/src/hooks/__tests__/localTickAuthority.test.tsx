import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { WsTick } from "@/types/api";
import type { BrokerAccount } from "@/types/broker";

const registry = vi.hoisted(() => ({
  callbacks: [] as Array<(tick: WsTick) => void>,
  release: vi.fn(),
  subscribe: vi.fn(),
  unsubscribe: vi.fn(),
  onTick: vi.fn(),
}));
vi.mock("@/services/websocket", () => ({ getWsService: () => registry }));

import useWebSocket from "../useWebSocket";
import { useTape } from "@/widgets/analysis/TimeSales/useTape";
import { brokerAccountKey, useBrokerStore } from "@/stores/brokerStore";
import { useModeStore } from "@/stores/modeStore";

const infy = { symbol: "INFY", exchange: "NSE" };
const reliance = { symbol: "RELIANCE", exchange: "NSE" };
const accountA: BrokerAccount = {
  source: "native", broker: "dhan", account_id: "shared", label: "A", status: "connected",
  connected_at: null, error_message: null, is_primary: false,
};
const accountB: BrokerAccount = { ...accountA, broker: "upstox", label: "B" };
const frames = new Map<number, FrameRequestCallback>();
const cancelFrame = vi.fn();
let nextFrame = 0;
function emit(callback: number, price: number, volume = 100, instrument = infy) {
  act(() => registry.callbacks[callback]({ ...instrument, ltp: price, volume }));
}
function flush(frame = nextFrame) {
  // Keep cancelled callbacks callable to model a frame already queued for delivery.
  act(() => frames.get(frame)!(0));
}
function switchAccount(account: BrokerAccount) {
  act(() => useBrokerStore.getState().setActiveAccount(brokerAccountKey(account)));
}

beforeEach(() => {
  vi.clearAllMocks();
  registry.callbacks.length = 0;
  registry.onTick.mockImplementation((callback: (tick: WsTick) => void) => {
    registry.callbacks.push(callback);
    return registry.release;
  });
  frames.clear();
  nextFrame = 0;
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    frames.set(++nextFrame, callback);
    return nextFrame;
  });
  vi.stubGlobal("cancelAnimationFrame", cancelFrame);
  useModeStore.setState({ mode: "live" });
  useBrokerStore.setState({ accounts: [accountA, accountB], activeAccountId: brokerAccountKey(accountA) });
});
afterEach(() => vi.unstubAllGlobals());

describe("local native tick batch authority", () => {
  it("retires A observations across a batched A → B → A transition before React commits", () => {
    const hook = renderHook(() => useWebSocket([infy]));
    emit(0, 101); flush(); emit(0, 102);
    const retiredFrame = nextFrame;
    act(() => {
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB));
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountA));
      registry.callbacks[0]({ ...infy, ltp: 999 });
      frames.get(retiredFrame)!(0);
    });
    expect(hook.result.current.ticks).toEqual({});
    emit(1, 103); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(103);
  });

  it("clears A ticks and refuses its queued frame and retired callback after selecting B", () => {
    const hook = renderHook(() => useWebSocket([infy]));
    emit(0, 101); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(101);
    emit(0, 102);
    const retiredFrame = nextFrame;
    switchAccount(accountB);
    expect(hook.result.current.ticks).toEqual({});
    expect(cancelFrame).toHaveBeenCalledWith(retiredFrame);
    flush(retiredFrame); emit(0, 999);
    expect(hook.result.current.ticks).toEqual({});
    emit(1, 202); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(202);
    switchAccount(accountA);
    expect(hook.result.current.ticks).toEqual({});
    emit(0, 999);
    expect(hook.result.current.ticks).toEqual({});
    emit(2, 103); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(103);
  });

  it.each(["practice", "explore"] as const)("discards queued Live ticks on the first %s render", (mode) => {
    const hook = renderHook(() => useWebSocket([infy]));
    emit(0, 101); flush(); emit(0, 102);
    const retiredFrame = nextFrame;
    act(() => useModeStore.getState().setMode(mode));
    expect(hook.result.current.ticks).toEqual({});
    flush(retiredFrame); emit(0, 999);
    expect(hook.result.current.ticks).toEqual({});
    emit(1, 203); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(203);
  });

  it("resets interests and disabled state without admitting another symbol", () => {
    const hook = renderHook(({ instrument, enabled }) => useWebSocket([instrument], "quote", enabled), {
      initialProps: { instrument: infy, enabled: true },
    });
    emit(0, 101); flush();
    hook.rerender({ instrument: reliance, enabled: true });
    expect(hook.result.current.ticks).toEqual({});
    expect(registry.unsubscribe).toHaveBeenCalledWith([infy], "quote");
    const frameCount = frames.size;
    emit(1, 999);
    expect(frames.size).toBe(frameCount);
    emit(1, 202, 100, reliance); flush();
    expect(hook.result.current.ticks).toEqual({ "NSE:RELIANCE": { ...reliance, ltp: 202, volume: 100 } });
    hook.rerender({ instrument: reliance, enabled: false });
    expect(hook.result.current.ticks).toEqual({});
    emit(1, 999, 100, reliance);
    expect(hook.result.current.ticks).toEqual({});
    expect(registry.unsubscribe).toHaveBeenCalledWith([reliance], "quote");
  });

  it("accepts only the surviving root StrictMode subscription and cancels its frame on unmount", () => {
    const hook = renderHook(() => useWebSocket([infy]), { reactStrictMode: true });
    expect(registry.callbacks).toHaveLength(2);
    expect(registry.release).toHaveBeenCalledTimes(1);
    emit(0, 999);
    expect(frames.size).toBe(0);
    emit(1, 101); flush();
    expect(hook.result.current.ticks["NSE:INFY"].ltp).toBe(101);
    emit(1, 102);
    const retiredFrame = nextFrame;
    hook.unmount();
    expect(cancelFrame).toHaveBeenCalledWith(retiredFrame);
    expect(registry.release).toHaveBeenCalledTimes(2);
    flush(retiredFrame); emit(1, 999);
    expect(frames.size).toBe(retiredFrame);
  });
});

describe("inferred tape authority", () => {
  it("retires A's baseline across batched account return before React commits", () => {
    const hook = renderHook(() => useTape(infy, true));
    emit(0, 101, 100); emit(0, 102, 120);
    act(() => {
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountB));
      useBrokerStore.getState().setActiveAccount(brokerAccountKey(accountA));
      registry.callbacks[0]({ ...infy, ltp: 999, volume: 999 });
    });
    expect(hook.result.current).toEqual([]);
    emit(1, 103, 130);
    expect(hook.result.current[0]).toMatchObject({ id: 1, qty: 0, side: "neutral" });
  });

  it("clears A prints and starts B volume and direction from an independent baseline", () => {
    const hook = renderHook(() => useTape(infy, true));
    emit(0, 101, 100); emit(0, 102, 120);
    expect(hook.result.current[0]).toMatchObject({ id: 2, price: 102, qty: 20, side: "buy" });
    switchAccount(accountB);
    expect(hook.result.current).toEqual([]);
    emit(0, 999, 999);
    expect(hook.result.current).toEqual([]);
    emit(1, 200, 50);
    expect(hook.result.current).toHaveLength(1);
    expect(hook.result.current[0]).toMatchObject({ id: 1, price: 200, qty: 0, side: "neutral" });
    emit(1, 199, 60);
    expect(hook.result.current[0]).toMatchObject({ id: 2, price: 199, qty: 10, side: "sell" });
    switchAccount(accountA);
    expect(hook.result.current).toEqual([]);
    emit(0, 999, 999); emit(1, 999, 999);
    expect(hook.result.current).toEqual([]);
    emit(2, 103, 130);
    expect(hook.result.current[0]).toMatchObject({ id: 1, qty: 0, side: "neutral" });
  });

  it.each(["practice", "explore"] as const)("clears Live prints and rejects the retired source in %s", (mode) => {
    const hook = renderHook(() => useTape(infy, true));
    emit(0, 101, 100); emit(0, 102, 120);
    act(() => useModeStore.getState().setMode(mode));
    expect(hook.result.current).toEqual([]);
    emit(0, 999, 999);
    expect(hook.result.current).toEqual([]);
    emit(1, 50, 10);
    expect(hook.result.current[0]).toMatchObject({ id: 1, price: 50, qty: 0, side: "neutral" });
  });

  it("resets the fold when the instrument changes and releases interests when disabled", () => {
    const hook = renderHook(({ instrument, enabled }) => useTape(instrument, enabled), {
      initialProps: { instrument: infy, enabled: true },
    });
    emit(0, 101, 100); emit(0, 102, 120);
    hook.rerender({ instrument: reliance, enabled: true });
    expect(hook.result.current).toEqual([]);
    expect(registry.unsubscribe).toHaveBeenCalledWith([infy], "quote");
    emit(0, 999, 999, reliance); emit(1, 999, 999);
    expect(hook.result.current).toEqual([]);
    emit(1, 200, 50, reliance);
    expect(hook.result.current[0]).toMatchObject({ id: 1, price: 200, qty: 0, side: "neutral" });
    hook.rerender({ instrument: reliance, enabled: false });
    expect(hook.result.current).toEqual([]);
    emit(1, 201, 60, reliance);
    expect(hook.result.current).toEqual([]);
    expect(registry.unsubscribe).toHaveBeenCalledWith([reliance], "quote");
  });

  it("refuses retired StrictMode and unmounted callbacks while preserving the survivor's fold", () => {
    const hook = renderHook(() => useTape(infy, true), { reactStrictMode: true });
    expect(registry.callbacks).toHaveLength(2);
    expect(registry.release).toHaveBeenCalledTimes(1);
    emit(0, 999, 999);
    expect(hook.result.current).toEqual([]);
    emit(1, 101, 100); emit(1, 102, 120);
    expect(hook.result.current[0]).toMatchObject({ id: 2, qty: 20, side: "buy" });
    hook.unmount();
    expect(registry.release).toHaveBeenCalledTimes(2);
    const retiredSnapshot = hook.result.current;
    emit(1, 999, 999);
    expect(hook.result.current).toBe(retiredSnapshot);
  });
});
