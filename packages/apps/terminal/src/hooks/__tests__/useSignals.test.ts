/**
 * Tests for useSignals — mode-aware signal pipeline hooks.
 *
 * Verifies that:
 *   1. useRecentSignals returns sample signals in explore mode
 *   2. useRecentSignals calls API in live mode
 *   3. useSignalConfig returns sample config in explore mode
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mock modeStore
// ---------------------------------------------------------------------------

let currentMode: "explore" | "practice" | "live" = "explore";
const modeListeners = new Set<() => void>();

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => {
    const [, setState] = React.useState(0);
    React.useEffect(() => {
      const cb = () => setState((n) => n + 1);
      modeListeners.add(cb);
      return () => { modeListeners.delete(cb); };
    }, []);
    return selector({ mode: currentMode });
  },
}));

// ---------------------------------------------------------------------------
// Mock ftApi service
// ---------------------------------------------------------------------------

const mockApiSignals = {
  signals: [
    {
      timestamp: "2026-04-08T10:00:00Z",
      symbol: "NIFTY",
      signal_type: "BUY",
      indicator: "RSI",
      value: 25.0,
      threshold: 30,
      confidence: 0.8,
      message: "API signal",
    },
  ],
};

const mockApiConfig = {
  instruments: ["NIFTY"],
  indicators: [{ name: "RSI", params: { period: 14 } }],
  thresholds: { rsi_oversold: 30, rsi_overbought: 70 },
};

const getRecentSignalsMock = vi.fn((_limit?: number) => Promise.resolve(mockApiSignals));
const getSignalConfigMock = vi.fn(() => Promise.resolve(mockApiConfig));
const updateSignalConfigMock = vi.fn((_config: unknown) => Promise.resolve(mockApiConfig));

vi.mock("@/services/ftApi", () => ({
  getRecentSignals: (limit?: number) => getRecentSignalsMock(limit),
  getSignalConfig: () => getSignalConfigMock(),
  updateSignalConfig: (config: unknown) => updateSignalConfigMock(config),
}));

// ---------------------------------------------------------------------------
// Import hooks after mocks
// ---------------------------------------------------------------------------

import { signalEventSchema, useRecentSignals, useSignalConfig } from "../useSignals";

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  currentMode = "explore";
  modeListeners.clear();
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests: useRecentSignals
// ---------------------------------------------------------------------------

describe("useRecentSignals", () => {
  it("returns sample signals in explore mode", async () => {
    const { result } = renderHook(() => useRecentSignals(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    // In explore mode the queryFn resolves with sample data inline
    expect(result.current.data?.signals).toBeDefined();
    expect(result.current.data!.signals.length).toBeGreaterThan(0);
    expect(result.current.data!.signals[0].symbol).toBe("NIFTY");
    // Should NOT call the real API
    expect(getRecentSignalsMock).not.toHaveBeenCalled();
  });

  it("calls API in live mode", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useRecentSignals(10), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getRecentSignalsMock).toHaveBeenCalledWith(10);
    expect(result.current.data?.signals[0].message).toBe("API signal");
  });
});

// ---------------------------------------------------------------------------
// Tests: useSignalConfig
// ---------------------------------------------------------------------------

describe("useSignalConfig", () => {
  it("returns sample config in explore mode without API calls", async () => {
    const { result } = renderHook(() => useSignalConfig(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.data).toBeDefined();
    expect(result.current.data!.instruments).toContain("NIFTY");
    expect(getSignalConfigMock).not.toHaveBeenCalled();
  });

  it("calls API in live mode", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useSignalConfig(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getSignalConfigMock).toHaveBeenCalled();
    expect(result.current.data?.instruments).toEqual(["NIFTY"]);
  });
});

describe("signalEventSchema", () => {
  it("accepts source-tagged ML HOLD events", () => {
    const event = signalEventSchema.parse({
      event_id: 17,
      timestamp: "2026-07-10T09:20:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "HOLD",
      source: "ml",
      method: "ml_model",
      indicator: "LightGBM",
      value: 24500,
      threshold: 0,
      confidence: 0.61,
      message: "NIFTY scheduled ml model signal: HOLD",
      metadata: { turbulence_score: 0.2 },
    });

    expect(event.source).toBe("ml");
    expect(event.signal_type).toBe("HOLD");
    expect(event.event_id).toBe(17);
  });

  it("defaults new identity fields for an older live-rule frame", () => {
    const event = signalEventSchema.parse(mockApiSignals.signals[0]);

    expect(event.event_id).toBe(0);
    expect(event.source).toBe("rule");
    expect(event.exchange).toBe("");
    expect(event.metadata).toEqual({});
  });
});
