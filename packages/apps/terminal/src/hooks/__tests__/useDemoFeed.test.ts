/**
 * useDemoFeed.test — the simulated-live Explore-mode market feed.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { getDefaultStore } from "jotai";
import { useDemoFeed } from "../useDemoFeed";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { useModeStore } from "@/stores/modeStore";
import { mockDataEngine } from "@/services/mockDataEngine";

const NIFTY_KEY = "NSE_INDEX:NIFTY";

describe("useDemoFeed", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useModeStore.setState({ mode: "explore" });
    mockDataEngine.stop();
    getDefaultStore().set(tickAtomFamily(NIFTY_KEY), null);
  });

  afterEach(() => {
    mockDataEngine.stop();
    vi.useRealTimers();
  });

  it("starts the mock engine in explore mode", () => {
    renderHook(() => useDemoFeed());
    expect(mockDataEngine.isRunning).toBe(true);
  });

  it("writes simulated ticks into the shared market atoms", () => {
    renderHook(() => useDemoFeed());
    vi.advanceTimersByTime(1000);
    const tick = getDefaultStore().get(tickAtomFamily(NIFTY_KEY));
    expect(tick).not.toBeNull();
    expect(tick?.symbol).toBe("NIFTY");
    expect(typeof tick?.ltp).toBe("number");
  });

  it("ticks the dashboard watchlist's VIX and GOLD rows in demo mode", () => {
    // Previously the engine emitted no INDIAVIX/GOLD, so those WatchlistCard
    // rows sat on a static dash in Explore. They must now tick too.
    const store = getDefaultStore();
    store.set(tickAtomFamily("NSE_INDEX:INDIAVIX"), null);
    store.set(tickAtomFamily("MCX:GOLD"), null);

    renderHook(() => useDemoFeed());
    vi.advanceTimersByTime(1000);

    const vix = store.get(tickAtomFamily("NSE_INDEX:INDIAVIX"));
    const gold = store.get(tickAtomFamily("MCX:GOLD"));
    expect(vix?.symbol).toBe("INDIAVIX");
    expect(typeof vix?.ltp).toBe("number");
    expect(gold?.symbol).toBe("GOLD");
    expect(typeof gold?.ltp).toBe("number");
  });

  it("does not run outside explore mode", () => {
    useModeStore.setState({ mode: "live" });
    renderHook(() => useDemoFeed());
    expect(mockDataEngine.isRunning).toBe(false);
  });

  it("stops the engine on unmount", () => {
    const { unmount } = renderHook(() => useDemoFeed());
    expect(mockDataEngine.isRunning).toBe(true);
    unmount();
    expect(mockDataEngine.isRunning).toBe(false);
  });

  it("clears the simulated atoms when leaving explore mode", () => {
    renderHook(() => useDemoFeed());
    vi.advanceTimersByTime(1000);
    expect(getDefaultStore().get(tickAtomFamily(NIFTY_KEY))).not.toBeNull();

    // Switching away from explore re-runs the effect; cleanup must null the
    // demo-written atoms so no stale simulated price persists.
    act(() => {
      useModeStore.setState({ mode: "live" });
    });
    expect(getDefaultStore().get(tickAtomFamily(NIFTY_KEY))).toBeNull();
    expect(mockDataEngine.isRunning).toBe(false);
  });
});
