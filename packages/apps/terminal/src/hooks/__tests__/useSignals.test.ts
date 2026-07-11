/**
 * Tests for useSignals — mode-aware signal pipeline hooks.
 *
 * Verifies that:
 *   1. useRecentSignals returns sample signals in explore mode
 *   2. useRecentSignals calls API in live mode
 *   3. useSignalConfig returns sample config in explore mode
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

type MarketHoursTarget = string | { exchange: string; symbol: string };
const marketMocks = vi.hoisted(() => ({
  state: { open: true },
  isMarketHours: vi.fn((_target?: MarketHoursTarget) => true),
}));

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

vi.mock("@/lib/market", () => ({
  isMarketHours: (target?: MarketHoursTarget) => marketMocks.isMarketHours(target),
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
  instruments: ["NSE_INDEX:NIFTY"],
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

import {
  signalEventSchema,
  useRecentSignals,
  useSignalConfig,
  useSignalStream,
} from "../useSignals";

// ---------------------------------------------------------------------------
// Wrapper
// ---------------------------------------------------------------------------

function createQueryClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
}

function createWrapper(queryClient = createQueryClient()) {
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return React.createElement(QueryClientProvider, { client: queryClient }, children);
  };
}

class FakeEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;
  static readonly instances: FakeEventSource[] = [];

  readonly CONNECTING = FakeEventSource.CONNECTING;
  readonly OPEN = FakeEventSource.OPEN;
  readonly CLOSED = FakeEventSource.CLOSED;
  readonly withCredentials = false;
  readyState = FakeEventSource.CONNECTING;
  closed = false;
  onopen: ((this: EventSource, event: Event) => unknown) | null = null;
  onerror: ((this: EventSource, event: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, event: MessageEvent) => unknown) | null = null;

  constructor(readonly url: string) {
    super();
    FakeEventSource.instances.push(this);
  }

  open() {
    this.readyState = FakeEventSource.OPEN;
    const event = new Event("open");
    this.onopen?.call(this as unknown as EventSource, event);
    this.dispatchEvent(event);
  }

  emit(type: string, data: string) {
    const event = new MessageEvent(type, { data });
    if (type === "message") {
      this.onmessage?.call(this as unknown as EventSource, event);
    }
    this.dispatchEvent(event);
  }

  close() {
    this.closed = true;
    this.readyState = FakeEventSource.CLOSED;
  }
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  currentMode = "explore";
  marketMocks.state.open = true;
  marketMocks.isMarketHours.mockReset().mockImplementation(() => marketMocks.state.open);
  mockApiConfig.instruments = ["NSE_INDEX:NIFTY"];
  modeListeners.clear();
  FakeEventSource.instances.length = 0;
  vi.clearAllMocks();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
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
    expect(new Set(result.current.data!.signals.map((signal) => signal.source))).toEqual(
      new Set(["rule", "ml", "fallback"]),
    );
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

  it("refetches against a separate cache entry when mode changes", async () => {
    const { result } = renderHook(() => useRecentSignals(10), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data?.signals[0].source).toBe("rule"));
    expect(getRecentSignalsMock).not.toHaveBeenCalled();

    act(() => {
      currentMode = "live";
      modeListeners.forEach((listener) => listener());
    });

    await waitFor(() => expect(result.current.data?.signals[0].message).toBe("API signal"));
    expect(getRecentSignalsMock).toHaveBeenCalledWith(10);
  });

  it("rechecks a closed market and adopts five-second polling after it opens", async () => {
    vi.useFakeTimers();
    currentMode = "live";
    marketMocks.state.open = false;
    renderHook(() => useRecentSignals(10), { wrapper: createWrapper() });

    await vi.waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledTimes(1));
    getRecentSignalsMock.mockClear();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalledTimes(1);

    marketMocks.state.open = true;
    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalled();

    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalled();
  });

  it.each([
    ["MCX:GOLD", { exchange: "MCX", symbol: "GOLD" }],
    ["CDS:USDINR29JUL26FUT", { exchange: "CDS", symbol: "USDINR29JUL26FUT" }],
    ["CDS:EURUSD29JUL26FUT", { exchange: "CDS", symbol: "EURUSD29JUL26FUT" }],
  ])("polls every five seconds while configured instrument %s is open", async (identity, openTarget) => {
    vi.useFakeTimers();
    currentMode = "live";
    mockApiConfig.instruments = ["NSE_INDEX:NIFTY", identity];
    marketMocks.isMarketHours.mockImplementation((target) => (
      typeof target === "object"
      && target.exchange === openTarget.exchange
      && target.symbol === openTarget.symbol
    ));

    renderHook(() => useRecentSignals(10), { wrapper: createWrapper() });

    await vi.waitFor(() => expect(getSignalConfigMock).toHaveBeenCalledTimes(1));
    await vi.waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledTimes(1));

    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalledTimes(1);
    expect(marketMocks.isMarketHours).toHaveBeenCalledWith(openTarget);

    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalledTimes(1);
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
    expect(result.current.data!.instruments).toContain("NSE_INDEX:NIFTY");
    expect(getSignalConfigMock).not.toHaveBeenCalled();
  });

  it("calls API in live mode", async () => {
    currentMode = "live";

    const { result } = renderHook(() => useSignalConfig(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(getSignalConfigMock).toHaveBeenCalled();
    expect(result.current.data?.instruments).toEqual(["NSE_INDEX:NIFTY"]);
  });

  it("refetches config against a separate cache entry when mode changes", async () => {
    const { result } = renderHook(() => useSignalConfig(), {
      wrapper: createWrapper(),
    });

    await waitFor(() => expect(result.current.data?.instruments).toContain("NSE_INDEX:BANKNIFTY"));
    expect(getSignalConfigMock).not.toHaveBeenCalled();

    act(() => {
      currentMode = "live";
      modeListeners.forEach((listener) => listener());
    });

    await waitFor(() => expect(result.current.data?.instruments).toEqual(["NSE_INDEX:NIFTY"]));
    expect(getSignalConfigMock).toHaveBeenCalled();
  });
});

describe("useSignalStream", () => {
  it("handles named replay-loss events, exposes clearable state, and reconciles recent signals", async () => {
    currentMode = "live";
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    const queryClient = createQueryClient();
    const onSignal = vi.fn();
    const { result, unmount } = renderHook(() => ({
      recent: useRecentSignals(10),
      stream: useSignalStream(onSignal),
    }), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(result.current.recent.isSuccess).toBe(true));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];
    expect(source.url).toBe("/ft-api/api/v1/signals/stream");

    act(() => source.open());
    expect(result.current.stream.connected).toBe(true);

    getRecentSignalsMock.mockClear();
    const replayLoss = {
      reason: "cursor_before_retained",
      requested_event_id: 12,
      oldest_available_event_id: 40,
      newest_available_event_id: 139,
    };
    act(() => source.emit("replay-loss", JSON.stringify(replayLoss)));

    await waitFor(() => expect(result.current.stream.replayLoss).toEqual(replayLoss));
    await waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledWith(10));
    expect(onSignal).not.toHaveBeenCalled();

    act(() => result.current.stream.clearReplayLoss());
    expect(result.current.stream.replayLoss).toBeNull();

    const signal = {
      event_id: 140,
      timestamp: "2026-07-11T10:00:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "BUY",
      source: "rule",
      method: "RSI",
      indicator: "RSI",
      value: 28,
      threshold: 30,
      confidence: 0.8,
      message: "NIFTY RSI below threshold",
      metadata: {},
    };
    act(() => source.emit("message", JSON.stringify(signal)));
    expect(onSignal).toHaveBeenCalledWith(signal);

    unmount();
    expect(source.closed).toBe(true);
  });

  it("rejects a late frame from the previous mode stream", async () => {
    currentMode = "live";
    vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
    const onSignal = vi.fn();
    renderHook(() => useSignalStream(onSignal), { wrapper: createWrapper() });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const liveSource = FakeEventSource.instances[0];

    act(() => {
      currentMode = "practice";
      modeListeners.forEach((listener) => listener());
    });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    const practiceSource = FakeEventSource.instances[1];
    const signal = {
      event_id: 141,
      timestamp: "2026-07-11T10:01:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "BUY",
      source: "rule",
      method: "RSI",
      indicator: "RSI",
      value: 28,
      threshold: 30,
      confidence: 0.8,
      message: "NIFTY RSI below threshold",
      metadata: {},
    };

    act(() => liveSource.emit("message", JSON.stringify(signal)));
    expect(onSignal).not.toHaveBeenCalled();

    act(() => practiceSource.emit("message", JSON.stringify(signal)));
    expect(onSignal).toHaveBeenCalledOnce();
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

  it("accepts source-tagged scheduled fallback events", () => {
    const event = signalEventSchema.parse({
      event_id: 18,
      timestamp: "2026-07-10T09:25:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "HOLD",
      source: "fallback",
      method: "ema_crossover_fallback+turbulence_override",
      indicator: "EMA_Cross",
      value: 24_500,
      threshold: 0,
      confidence: 0.5,
      message: "NIFTY scheduled EMA crossover fallback signal: HOLD",
      metadata: {},
    });

    expect(event.source).toBe("fallback");
  });

  it("normalises known scheduled methods from mixed-version source labels", () => {
    const fallback = signalEventSchema.parse({
      event_id: 19,
      timestamp: "2026-07-10T09:25:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "HOLD",
      source: "ml",
      method: "ema_crossover_fallback+turbulence_override",
      indicator: "EMA_Cross",
      value: 24_500,
      threshold: 0,
      confidence: 0.5,
      message: "Legacy fallback signal",
      metadata: {},
    });
    const trained = signalEventSchema.parse({
      event_id: 20,
      timestamp: "2026-07-10T09:30:00+05:30",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "BUY",
      method: "ml_model",
      indicator: "LightGBM",
      value: 24_510,
      threshold: 0,
      confidence: 0.8,
      message: "Legacy trained signal",
      metadata: {},
    });

    expect(fallback.source).toBe("fallback");
    expect(trained.source).toBe("ml");
  });

  it("defaults new identity fields for an older live-rule frame", () => {
    const event = signalEventSchema.parse(mockApiSignals.signals[0]);

    expect(event.event_id).toBe(0);
    expect(event.source).toBe("rule");
    expect(event.exchange).toBe("");
    expect(event.metadata).toEqual({});
  });
});
