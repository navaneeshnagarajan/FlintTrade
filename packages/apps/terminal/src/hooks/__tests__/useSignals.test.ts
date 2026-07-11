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
import { useAuthStore } from "@/stores/authStore";

type MarketHoursTarget = string | { exchange: string; symbol: string };
interface TestHoliday {
  date: string;
  description: string;
  holiday_type: string;
  closed_exchanges: string[];
  open_exchanges: Array<{ exchange: string; start_time: number; end_time: number }>;
}

const marketMocks = vi.hoisted(() => ({
  state: { open: true },
  isMarketHours: vi.fn((_target?: MarketHoursTarget, _holidays?: TestHoliday[]) => true),
}));

const holidayMocks = vi.hoisted(() => ({
  state: {
    data: undefined as TestHoliday[] | undefined,
    isPending: false,
  },
}));

const helperMocks = vi.hoisted(() => ({
  buildHeaders: vi.fn((_includeJson: boolean) => ({
    Authorization: "Bearer terminal-jwt",
    "X-API-Key": "terminal-api-key",
  })),
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
  isMarketHours: (target?: MarketHoursTarget, holidays?: TestHoliday[]) => (
    marketMocks.isMarketHours(target, holidays)
  ),
}));

vi.mock("@/hooks/useMarketStatus", () => ({
  useHolidays: () => holidayMocks.state,
}));

vi.mock("@/services/ftApi.helpers", () => ({
  getBase: () => "/ft-api",
  buildHeaders: (includeJson: boolean) => helperMocks.buildHeaders(includeJson),
}));

// ---------------------------------------------------------------------------
// Mock ftApi service
// ---------------------------------------------------------------------------

const mockApiSignals = {
  signals: [
    {
      event_id: 139,
      timestamp: "2026-04-08T10:00:00Z",
      symbol: "NIFTY",
      exchange: "NSE_INDEX",
      signal_type: "BUY",
      source: "rule",
      method: "RSI",
      indicator: "RSI",
      value: 25.0,
      threshold: 30,
      confidence: 0.8,
      message: "API signal",
      metadata: {},
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

interface TestSseStream {
  response: Response;
  enqueue: (frame: string) => void;
}

function createSseStream(initialFrames: string[] = []): TestSseStream {
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(nextController) {
      controller = nextController;
      initialFrames.forEach((frame) => nextController.enqueue(encoder.encode(frame)));
    },
  });

  return {
    response: {
      ok: true,
      status: 200,
      body,
      headers: new Headers({ "Content-Type": "text/event-stream" }),
    } as Response,
    enqueue: (frame) => controller?.enqueue(encoder.encode(frame)),
  };
}

const fetchMock = vi.fn<typeof fetch>();
const SIGNAL_CURSOR_KEY = "flinttrade:signals:sse-cursor:v1";

class DormantEventSource extends EventTarget {
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  onmessage: ((event: MessageEvent) => void) | null = null;

  close() {}
}

// ---------------------------------------------------------------------------
// Reset
// ---------------------------------------------------------------------------

beforeEach(() => {
  currentMode = "explore";
  marketMocks.state.open = true;
  marketMocks.isMarketHours.mockReset().mockImplementation(() => marketMocks.state.open);
  holidayMocks.state.data = undefined;
  holidayMocks.state.isPending = false;
  helperMocks.buildHeaders.mockClear();
  mockApiConfig.instruments = ["NSE_INDEX:NIFTY"];
  modeListeners.clear();
  vi.clearAllMocks();
  getRecentSignalsMock.mockImplementation((_limit?: number) => Promise.resolve(mockApiSignals));
  getSignalConfigMock.mockImplementation(() => Promise.resolve(mockApiConfig));
  updateSignalConfigMock.mockImplementation((_config: unknown) => Promise.resolve(mockApiConfig));
  localStorage.removeItem(SIGNAL_CURSOR_KEY);
  useAuthStore.setState({ token: null });
  vi.stubGlobal("EventSource", DormantEventSource);
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
    expect(marketMocks.isMarketHours).toHaveBeenCalledWith(openTarget, undefined);

    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalledTimes(1);
  });

  it("uses the holiday calendar to avoid five-second polling on a weekday closure", async () => {
    vi.useFakeTimers();
    currentMode = "live";
    holidayMocks.state.data = [{
      date: "2026-01-26",
      description: "Republic Day",
      holiday_type: "TRADING_HOLIDAY",
      closed_exchanges: ["NSE", "NSE_INDEX"],
      open_exchanges: [],
    }];
    marketMocks.isMarketHours.mockImplementation((_target, holidays) => !holidays?.length);

    renderHook(() => useRecentSignals(10), { wrapper: createWrapper() });
    await vi.waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledTimes(1));

    getRecentSignalsMock.mockClear();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5_000);
    });

    expect(getRecentSignalsMock).not.toHaveBeenCalled();
    expect(marketMocks.isMarketHours).toHaveBeenCalledWith(
      { exchange: "NSE_INDEX", symbol: "NIFTY" },
      holidayMocks.state.data,
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(55_000);
    });
    expect(getRecentSignalsMock).toHaveBeenCalledTimes(1);
  });

  it("does not let an older in-flight poll replace a newer cached SSE event", async () => {
    currentMode = "live";
    const queryClient = createQueryClient();
    let resolveRecent: ((value: { signals: typeof mockApiSignals.signals }) => void) | undefined;
    getRecentSignalsMock.mockImplementationOnce(() => new Promise((resolve) => {
      resolveRecent = resolve;
    }));

    const { result } = renderHook(() => useRecentSignals(10), {
      wrapper: createWrapper(queryClient),
    });
    await waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledOnce());

    const newerSignal = {
      ...mockApiSignals.signals[0],
      event_id: 140,
      timestamp: "2026-07-11T10:00:00+05:30",
      message: "newer SSE signal",
    };
    act(() => {
      queryClient.setQueryData(
        ["signals", "recent", "live", 10],
        { signals: [newerSignal] },
      );
    });

    await act(async () => {
      resolveRecent?.({
        signals: [{
          ...mockApiSignals.signals[0],
          event_id: 139,
          timestamp: "2026-07-11T09:59:00+05:30",
          message: "older poll signal",
        }],
      });
    });

    await waitFor(() => expect(result.current.fetchStatus).toBe("idle"));
    expect(result.current.data?.signals.map((signal) => signal.event_id)).toEqual([140, 139]);
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
  it("authenticates fetch SSE, resumes a boot-aware cursor, and persists the next frame ID", async () => {
    currentMode = "live";
    localStorage.setItem(SIGNAL_CURSOR_KEY, "prior-boot:139");
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
    const stream = createSseStream([
      `id: current-boot:140\ndata: ${JSON.stringify(signal)}\n\n`,
    ]);
    fetchMock.mockResolvedValue(stream.response);
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = createQueryClient();
    const onSignal = vi.fn();
    const { result, unmount } = renderHook(() => useSignalStream(onSignal), {
      wrapper: createWrapper(queryClient),
    });

    await waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());
    expect(fetchMock).toHaveBeenCalledWith(
      "/ft-api/api/v1/signals/stream",
      expect.objectContaining({
        headers: expect.objectContaining({
          Accept: "text/event-stream",
          Authorization: "Bearer terminal-jwt",
          "Last-Event-ID": "prior-boot:139",
          "X-API-Key": "terminal-api-key",
        }),
        signal: expect.any(AbortSignal),
      }),
    );
    expect(helperMocks.buildHeaders).toHaveBeenCalledWith(false);
    await waitFor(() => expect(onSignal).toHaveBeenCalledWith(signal));
    expect(localStorage.getItem(SIGNAL_CURSOR_KEY)).toBe("current-boot:140");
    expect(result.current.connected).toBe(true);

    const signalUsed = fetchMock.mock.calls[0][1]?.signal;
    unmount();
    expect(signalUsed?.aborted).toBe(true);
  });

  it("parses named replay-loss frames and refreshes recent signals", async () => {
    currentMode = "live";
    localStorage.setItem(SIGNAL_CURSOR_KEY, "prior-boot:12");
    const replayLoss = {
      reason: "cursor_before_retained",
      requested_event_id: 12,
      oldest_available_event_id: 40,
      newest_available_event_id: 139,
    };
    const stream = createSseStream([
      `event: replay-loss\ndata: ${JSON.stringify(replayLoss)}\n\n`,
    ]);
    fetchMock.mockResolvedValue(stream.response);
    vi.stubGlobal("fetch", fetchMock);
    const queryClient = createQueryClient();
    const onSignal = vi.fn();
    const { result } = renderHook(() => ({
      recent: useRecentSignals(10),
      stream: useSignalStream(onSignal),
    }), { wrapper: createWrapper(queryClient) });

    await waitFor(() => expect(result.current.stream.replayLoss).toEqual(replayLoss));
    await waitFor(() => expect(getRecentSignalsMock).toHaveBeenCalledWith(10));
    expect(localStorage.getItem(SIGNAL_CURSOR_KEY)).toBeNull();
    expect(onSignal).not.toHaveBeenCalled();

    act(() => result.current.stream.clearReplayLoss());
    expect(result.current.stream.replayLoss).toBeNull();
  });

  it("stops reconnecting after a terminal authentication response", async () => {
    vi.useFakeTimers();
    currentMode = "live";
    fetchMock.mockResolvedValue({
      ok: false,
      status: 401,
      body: null,
      headers: new Headers(),
    } as Response);
    vi.stubGlobal("fetch", fetchMock);

    renderHook(() => useSignalStream(vi.fn()), { wrapper: createWrapper() });
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledOnce());

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000);
    });
    expect(fetchMock).toHaveBeenCalledOnce();
  });

  it("drops the connected state while changed credentials establish a replacement stream", async () => {
    currentMode = "live";
    const firstStream = createSseStream();
    let resolveReplacement: ((response: Response) => void) | undefined;
    fetchMock
      .mockResolvedValueOnce(firstStream.response)
      .mockImplementationOnce(() => new Promise((resolve) => {
        resolveReplacement = resolve;
      }));
    vi.stubGlobal("fetch", fetchMock);

    const { result } = renderHook(() => useSignalStream(vi.fn()), {
      wrapper: createWrapper(),
    });
    await waitFor(() => expect(result.current.connected).toBe(true));

    act(() => useAuthStore.setState({ token: "replacement-token" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(result.current.connected).toBe(false);

    resolveReplacement?.(createSseStream().response);
    await waitFor(() => expect(result.current.connected).toBe(true));
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
    const event = signalEventSchema.parse({
      timestamp: "2026-04-08T10:00:00Z",
      symbol: "NIFTY",
      signal_type: "BUY",
      indicator: "RSI",
      value: 25,
      threshold: 30,
      confidence: 0.8,
      message: "Legacy API signal",
    });

    expect(event.event_id).toBe(0);
    expect(event.source).toBe("rule");
    expect(event.exchange).toBe("");
    expect(event.metadata).toEqual({});
  });
});
