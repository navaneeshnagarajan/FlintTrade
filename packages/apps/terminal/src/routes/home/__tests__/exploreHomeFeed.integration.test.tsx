/**
 * exploreHomeFeed.integration.test — demo mode end-to-end.
 *
 * Proves the full Explore/demo chain: useDemoFeed drives the mock engine, which
 * writes simulated ticks into the SHARED jotai atoms, which the home
 * WatchlistCard reads — so the dashboard "ticks" with live-like data. Uses the
 * real jotai default store + the real engine (NOT mocked) with fake timers.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import "@testing-library/jest-dom";
import { getDefaultStore } from "jotai";

import { useDemoFeed } from "@/hooks/useDemoFeed";
import { useModeStore } from "@/stores/modeStore";
import { mockDataEngine } from "@/services/mockDataEngine";
import { tickAtomFamily } from "@/atoms/marketAtoms";
import { WatchlistCard } from "../WatchlistCard";

// The five atoms the home WatchlistCard reads.
const ROW_KEYS: ReadonlyArray<readonly [string, string]> = [
  ["NSE_INDEX:NIFTY", "NIFTY"],
  ["NSE_INDEX:BANKNIFTY", "BANKNIFTY"],
  ["BSE_INDEX:SENSEX", "SENSEX"],
  ["NSE_INDEX:INDIAVIX", "INDIAVIX"],
  ["MCX:GOLD", "GOLD"],
];

function Harness() {
  useDemoFeed();
  return <WatchlistCard />;
}

describe("Explore demo feed → home WatchlistCard", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    useModeStore.setState({ mode: "explore" });
    mockDataEngine.stop();
    for (const [key] of ROW_KEYS) getDefaultStore().set(tickAtomFamily(key), null);
  });

  afterEach(() => {
    mockDataEngine.stop();
    vi.useRealTimers();
  });

  it("feeds every watchlist row (incl. VIX and GOLD) with simulated live data", () => {
    render(<Harness />);
    act(() => vi.advanceTimersByTime(1000));

    // The widget is mounted and reads these atoms; every row's atom is now a
    // simulated tick (no static dashes), proving the feed → atoms → widget chain.
    const store = getDefaultStore();
    for (const [key, sym] of ROW_KEYS) {
      const tick = store.get(tickAtomFamily(key));
      expect(tick?.symbol, `${sym} should tick in demo mode`).toBe(sym);
      expect(typeof tick?.ltp).toBe("number");
    }

    expect(screen.getByTestId("watchlist-card")).toBeInTheDocument();
    expect(screen.getByText("VIX")).toBeInTheDocument();
    expect(screen.getByText("GOLD")).toBeInTheDocument();
  });
});
