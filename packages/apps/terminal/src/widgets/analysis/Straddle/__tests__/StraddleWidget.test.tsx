/**
 * StraddleWidget.test.tsx
 *
 * Tests for the Straddle analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 *
 * This suite is the union of the old Straddle suite and the retired
 * ImpliedMove suite (merge 2.15). The ImpliedMove suite pinned that its
 * "Sample data" badge stayed visible EVEN WHEN CONNECTED, because the widget
 * had no live source at all. Those pins are obsolete by construction now that
 * the σ bands are computed from this widget's live chain, so they are rewritten
 * to pin the opposite: a live ATM straddle renders figures with no sample
 * badge, and the absence of one renders an honest "No live data" disclosure
 * instead of fabricated numbers. The σ arithmetic pins (move = CE + PE,
 * bounds = spot ± move, 2σ = 2 × 1σ) carry over verbatim in intent, but run
 * against `computeImpliedMove` on live inputs rather than a constant table.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import { useLayoutEffect } from "react";
import "@testing-library/jest-dom";
import type { AccountReadContext } from "@/hooks/useAccountReadsEnabled";
import {
  CONNECTED_NATIVE_READ_CONTEXT,
  EXPLORE_READ_CONTEXT,
  PRACTICE_READ_CONTEXT,
  UNCONFIGURED_LIVE_READ_CONTEXT,
} from "@/test-utils/accountReadFixtures";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const chartMocks = vi.hoisted(() => {
  const lineSeriesOptions: unknown[] = [];
  const localSeriesOptions: unknown[] = [];
  const createdLineSeries: Array<{
    setData: ReturnType<typeof vi.fn>;
    applyOptions: ReturnType<typeof vi.fn>;
  }> = [];

  const createSeries = () => ({
    setData: vi.fn(),
    applyOptions: vi.fn(),
  });

  const chart = {
    addSeries: vi.fn((_seriesType: unknown, options: unknown) => {
      localSeriesOptions.push(options);
      return createSeries();
    }),
    applyOptions: vi.fn(),
    priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
    remove: vi.fn(),
  };

  const shellRuntime = {
    createChart: vi.fn(() => chart),
  };

  const lineRuntime = {
    createChart: shellRuntime.createChart,
    addLineSeries: vi.fn((_chart: unknown, options: unknown) => {
      lineSeriesOptions.push(options);
      const series = createSeries();
      createdLineSeries.push(series);
      return series;
    }),
  };

  return {
    chart,
    shellRuntime,
    lineRuntime,
    lineSeriesOptions,
    localSeriesOptions,
    createdLineSeries,
    reset() {
      lineSeriesOptions.length = 0;
      localSeriesOptions.length = 0;
      createdLineSeries.length = 0;
    },
  };
});

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getPositionbook: vi.fn(),
}));

const accountReadState = vi.hoisted(() => {
  let current: AccountReadContext | undefined;
  const listeners = new Set<() => void>();
  return {
    get current() { return current; },
    set current(value: AccountReadContext | undefined) {
      current = value;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

const marketScopeState = vi.hoisted(() => {
  let current = "live:native:dhan:A1";
  const listeners = new Set<() => void>();
  return {
    get current() { return current; },
    set current(value: string) {
      current = value;
      listeners.forEach((listener) => listener());
    },
    subscribe(listener: () => void) {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
  };
});

// Mock API calls used by the widget
vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getPositionbook: apiMocks.getPositionbook,
}));

vi.mock("@/hooks/useAccountReadsEnabled", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useAccountReadContext: () => useSyncExternalStore(
      accountReadState.subscribe,
      () => accountReadState.current,
    ),
  };
});

vi.mock("@/hooks/useDataScope", async () => {
  const { useSyncExternalStore } = await import("react");
  return {
    useMarketDataScope: () => useSyncExternalStore(
      marketScopeState.subscribe,
      () => marketScopeState.current,
    ),
  };
});

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock lightweight-charts to avoid canvas issues in JSDOM
vi.mock("lightweight-charts", () => ({
  createChart: chartMocks.shellRuntime.createChart,
  LineSeries: "LineSeries",
}));

vi.mock("@/lib/lightweightChartRuntime", () => ({
  lightweightChartShellRuntime: chartMocks.shellRuntime,
  lightweightLineRuntime: chartMocks.lineRuntime,
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

// Mock chart theme hook
vi.mock("@/hooks/useChartTheme", () => ({
  useLightweightChartTheme: () => ({
    layout: {},
    grid: {},
    rightPriceScale: {},
    timeScale: {},
    // createFlintLineChart (real, from the design-system) reads
    // theme.crosshair.vertLine — the mock must carry the same shape.
    crosshair: { vertLine: {}, horzLine: {} },
  }),
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import StraddleWidget, { computeImpliedMove } from "../StraddleWidget";
import { useMarketDataScope } from "@/hooks/useDataScope";

const ACCOUNT_B_READ_CONTEXT = Object.freeze({
  identity: Object.freeze({
    mode: "live",
    scopeKey: "live:native:upstox:B2",
    brokerType: "upstox",
    accountId: "B2",
  }),
  enabled: true,
}) satisfies AccountReadContext;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const straddlePosition = (pnl: number) => ({
  symbol: "NIFTY25000CE",
  exchange: "NFO",
  quantity: 1,
  pnl,
});

/** Renders the widget with a Dockview panel-props stub and optional params. */
function renderWidget(params: Record<string, unknown> = {}) {
  return render(<StraddleWidget {...makeWidgetPanelProps({ params })} />);
}

/**
 * A live NIFTY chain whose ATM straddle produces round σ bands:
 *   move = 112.5 + 87.5 = 200 → ±1σ = 25,200 / 24,800, ±2σ = 25,400 / 24,600.
 */
function liveChainMocks() {
  apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
  apiMocks.getQuotes.mockResolvedValue({ ltp: 25000, prev_close: 24990 });
  apiMocks.getOptionChain.mockResolvedValue({
    atm_strike: 25000,
    chain: [{ strike: 25000, ce: { ltp: 112.5 }, pe: { ltp: 87.5 } }],
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StraddleWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
    marketScopeState.current = "live:native:dhan:A1";
    chartMocks.reset();
    apiMocks.getExpiry.mockReset().mockResolvedValue([]);
    apiMocks.getOptionChain.mockReset().mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockReset().mockResolvedValue({ ltp: 0 });
    apiMocks.getPositionbook.mockReset().mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    renderWidget();
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows headline price labels (Straddle, CE, PE)", () => {
    renderWidget();
    // "Straddle" appears in the headline, the overlay toggle and the view
    // toggle — use getAllByText
    const straddleElements = screen.getAllByText("Straddle");
    expect(straddleElements.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText("CE")).toBeInTheDocument();
    expect(screen.getByText("PE")).toBeInTheDocument();
  });

  it("shows overlay toggle buttons", () => {
    renderWidget();
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.getByText("Spot")).toBeInTheDocument();
    expect(screen.getByText("SynFut")).toBeInTheDocument();
  });

  it("routes overlay line series through the shared Flint line runtime", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-06-25"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 22510, prev_close: 22480 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 22500,
      calls: [{ strike_price: 22500, ltp: 112.5 }],
      puts: [{ strike_price: 22500, ltp: 98.25 }],
    });

    renderWidget();

    await waitFor(() => {
      expect(chartMocks.lineRuntime.addLineSeries).toHaveBeenCalledTimes(3);
    });
    expect(chartMocks.chart.addSeries).not.toHaveBeenCalled();
    expect(chartMocks.lineSeriesOptions).toEqual([
      expect.objectContaining({
        color: "#3b82f6",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      }),
      expect.objectContaining({
        color: "#eab308",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
      expect.objectContaining({
        color: "#a78bfa",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: true,
        visible: false,
      }),
    ]);
  });

  it("uses native chain[] option legs for headline prices", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000, prev_close: 24990 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        {
          strike: 25000,
          ce: { ltp: 112.5 },
          pe: { ltp: 98.25 },
        },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(screen.getByText("210.75")).toBeInTheDocument();
    });
    expect(screen.getByText("112.5")).toBeInTheDocument();
    expect(screen.getByText("98.25")).toBeInTheDocument();
    await waitFor(() => {
      expect(chartMocks.createdLineSeries[0]?.setData).toHaveBeenCalledWith(
        expect.arrayContaining([expect.objectContaining({ value: 210.75 })]),
      );
    });
  });

  it("pins expiry, chain and spot requests to the market scope with abort signals", async () => {
    liveChainMocks();
    renderWidget();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledOnce());
    expect(apiMocks.getExpiry).toHaveBeenCalledWith(
      "NIFTY", "NFO", "options", expect.any(AbortSignal), "live:native:dhan:A1",
    );
    expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), "live:native:dhan:A1",
    );
    expect(apiMocks.getQuotes).toHaveBeenCalledWith(
      "NIFTY", "NSE_INDEX", apiMocks.getOptionChain.mock.calls[0]?.[3], "live:native:dhan:A1",
    );
  });

  it.each(["straddle", "impliedmove"])("labels Example option figures in the %s view", async (view) => {
    accountReadState.current = EXPLORE_READ_CONTEXT;
    marketScopeState.current = "explore:mock";
    liveChainMocks();
    renderWidget({ view });

    expect(await screen.findByText("200")).toBeInTheDocument();
    expect(screen.getByRole("status", { name: "Example option quotes" })).toHaveTextContent("Example data");
    expect(screen.queryByText(/live ATM/i)).not.toBeInTheDocument();
    expect(apiMocks.getPositionbook).not.toHaveBeenCalled();
  });

  it.each(["live", "practice"])("shows unavailable straddle quotes after a %s provider failure", async (mode) => {
    accountReadState.current = mode === "practice" ? PRACTICE_READ_CONTEXT : CONNECTED_NATIVE_READ_CONTEXT;
    marketScopeState.current = `${mode}:native:dhan:A1`;
    liveChainMocks();
    apiMocks.getOptionChain.mockRejectedValue(new Error("Native option chain unavailable"));
    renderWidget({ view: "impliedmove" });

    expect(await screen.findByText("Chain error: Native option chain unavailable")).toBeInTheDocument();
    expect(screen.getByLabelText("No option quote — implied move is unavailable")).toBeInTheDocument();
    expect(screen.queryByText("200")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Implied move range bar")).not.toBeInTheDocument();
    expect(screen.queryByRole("status", { name: "Example option quotes" })).not.toBeInTheDocument();
  });

  it.each(["live", "practice"])(
    "hides account-A observations on the first %s render after the market source changes",
    async (mode) => {
      accountReadState.current = mode === "practice" ? PRACTICE_READ_CONTEXT : CONNECTED_NATIVE_READ_CONTEXT;
      marketScopeState.current = `${mode}:native:dhan:A1`;
      liveChainMocks();
      const pendingExpiryB = deferred<string[]>();
      apiMocks.getExpiry.mockResolvedValueOnce(["2026-07-30"]).mockImplementationOnce(() => pendingExpiryB.promise);
      const firstBRender: string[] = [];
      const props = makeWidgetPanelProps();
      function ScopeAudit() {
        const scope = useMarketDataScope();
        useLayoutEffect(() => {
          if (scope === `${mode}:native:upstox:B2`) firstBRender.push(document.body.textContent ?? "");
        }, [scope]);
        return <StraddleWidget {...props} />;
      }
      render(<ScopeAudit />);
      expect(await screen.findByText("200")).toBeInTheDocument();
      expect(screen.getByText("25,000")).toBeInTheDocument();
      expect(chartMocks.createdLineSeries.some((series) => series.setData.mock.calls.some(
        ([points]) => (points as Array<{ value: number }>).some((point) => point.value === 200),
      ))).toBe(true);

      act(() => { marketScopeState.current = `${mode}:native:upstox:B2`; });

      expect(firstBRender).toHaveLength(1);
      expect(firstBRender[0]).not.toContain("25,000");
      expect(firstBRender[0]).not.toContain("ATM 25,000");
      expect(firstBRender[0]).not.toContain("30 Jul");
      expect(screen.queryByText("200")).not.toBeInTheDocument();
      expect(screen.getByText("Select an expiry to load straddle data")).toBeInTheDocument();
      await waitFor(() => expect(apiMocks.getExpiry).toHaveBeenCalledTimes(2));
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);
    },
  );

  it("aborts and discards a late expiry list from the former market source", async () => {
    const pendingExpiryA = deferred<string[]>();
    apiMocks.getExpiry.mockImplementationOnce(() => pendingExpiryA.promise).mockResolvedValueOnce(["2026-08-27"]);
    liveChainMocks();
    renderWidget();
    await waitFor(() => expect(apiMocks.getExpiry).toHaveBeenCalledOnce());
    const signalA = apiMocks.getExpiry.mock.calls[0]?.[3] as AbortSignal;

    act(() => { marketScopeState.current = "live:native:upstox:B2"; });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledOnce());
    await act(async () => {
      pendingExpiryA.resolve(["2026-07-30"]);
      await pendingExpiryA.promise;
    });

    expect(signalA.aborted).toBe(true);
    expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-08-27", expect.any(AbortSignal), "live:native:upstox:B2",
    );
    expect(screen.queryByText("30 Jul")).not.toBeInTheDocument();
    expect(screen.getByText("27 Aug")).toBeInTheDocument();
  });

  it("discards late chain and spot responses when Practice switches native market accounts", async () => {
    accountReadState.current = PRACTICE_READ_CONTEXT;
    marketScopeState.current = "practice:native:dhan:A1";
    const pendingChainA = deferred<unknown>();
    const pendingSpotA = deferred<unknown>();
    liveChainMocks();
    apiMocks.getOptionChain.mockImplementationOnce(() => pendingChainA.promise).mockResolvedValue({
      atm_strike: 26000, chain: [{ strike: 26000, ce: { ltp: 180 }, pe: { ltp: 150 } }],
    });
    apiMocks.getQuotes.mockImplementationOnce(() => pendingSpotA.promise).mockResolvedValue({ ltp: 26000 });
    renderWidget();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledOnce());
    const signalA = apiMocks.getOptionChain.mock.calls[0]?.[3] as AbortSignal;

    act(() => { marketScopeState.current = "practice:native:upstox:B2"; });
    expect(await screen.findByText("330")).toBeInTheDocument();
    await act(async () => {
      pendingChainA.resolve({ atm_strike: 25000, chain: [{ strike: 25000, ce: { ltp: 112.5 }, pe: { ltp: 87.5 } }] });
      pendingSpotA.resolve({ ltp: 25000 });
      await Promise.all([pendingChainA.promise, pendingSpotA.promise]);
    });

    expect(signalA.aborted).toBe(true);
    expect(screen.getByText("330")).toBeInTheDocument();
    expect(screen.queryByText("200")).not.toBeInTheDocument();
    expect(screen.queryByText("25,000")).not.toBeInTheDocument();
    const plottedPoints = chartMocks.createdLineSeries.flatMap((series) => series.setData.mock.calls.flatMap(
      ([points]) => points as Array<{ value: number }>,
    ));
    expect(plottedPoints.some((point) => point.value === 330)).toBe(true);
    expect(plottedPoints.some((point) => point.value === 200 || point.value === 25000)).toBe(false);
    expect(apiMocks.getPositionbook.mock.calls.every(([context]) => context === PRACTICE_READ_CONTEXT)).toBe(true);
  });

  it("clears observations and expiry selection when the underlying symbol changes", async () => {
    const pendingBankExpiry = deferred<string[]>();
    liveChainMocks();
    apiMocks.getExpiry.mockResolvedValueOnce(["2026-07-30"]).mockImplementationOnce(() => pendingBankExpiry.promise);
    renderWidget();
    expect(await screen.findByText("200")).toBeInTheDocument();

    act(() => screen.getByRole("button", { name: "NIFTY" }).click());
    act(() => screen.getByRole("button", { name: "BANKNIFTY" }).click());

    expect(screen.queryByText("200")).not.toBeInTheDocument();
    expect(screen.queryByText("25,000")).not.toBeInTheDocument();
    expect(screen.queryByText("30 Jul")).not.toBeInTheDocument();
    expect(screen.getByText("Select an expiry to load straddle data")).toBeInTheDocument();
    expect(apiMocks.getExpiry).toHaveBeenLastCalledWith(
      "BANKNIFTY", "NFO", "options", expect.any(AbortSignal), "live:native:dhan:A1",
    );
    expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);
  });

  it("starts a fresh chart when the selected expiry changes", async () => {
    const pendingNextChain = deferred<unknown>();
    liveChainMocks();
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30", "2026-08-06"]);
    apiMocks.getOptionChain.mockResolvedValueOnce({
      atm_strike: 25000, chain: [{ strike: 25000, ce: { ltp: 112.5 }, pe: { ltp: 87.5 } }],
    }).mockImplementationOnce(() => pendingNextChain.promise);
    renderWidget();
    expect(await screen.findByText("200")).toBeInTheDocument();

    act(() => screen.getByRole("button", { name: "6 Aug" }).click());
    expect(screen.queryByText("200")).not.toBeInTheDocument();
    expect(screen.queryByText("25,000")).not.toBeInTheDocument();
    expect(screen.getByText("Loading straddle…")).toBeInTheDocument();
    await act(async () => {
      pendingNextChain.resolve({ atm_strike: 25000, chain: [{ strike: 25000, ce: { ltp: 180 }, pe: { ltp: 150 } }] });
      await pendingNextChain.promise;
    });

    expect(await screen.findByText("330")).toBeInTheDocument();
    expect(apiMocks.getOptionChain).toHaveBeenLastCalledWith(
      "NIFTY", "NFO", "2026-08-06", expect.any(AbortSignal), "live:native:dhan:A1",
    );
    const latestChart = chartMocks.createdLineSeries.slice(-3);
    const latestStraddlePoints = latestChart[0]?.setData.mock.calls.at(-1)?.[0] as Array<{ value: number }>;
    expect(latestStraddlePoints.map((point) => point.value)).toEqual([330]);
  });

  it("restores scope-pinned reads after root StrictMode replay and aborts on unmount", async () => {
    liveChainMocks();
    const pendingChain = deferred<unknown>();
    apiMocks.getOptionChain.mockReturnValue(pendingChain.promise);
    const { unmount } = render(<StraddleWidget {...makeWidgetPanelProps()} />, { reactStrictMode: true });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledOnce());
    expect(apiMocks.getExpiry).toHaveBeenCalledTimes(2);
    const firstExpirySignal = apiMocks.getExpiry.mock.calls[0]?.[3] as AbortSignal;
    const activeExpirySignal = apiMocks.getExpiry.mock.calls[1]?.[3] as AbortSignal;
    const dataSignal = apiMocks.getOptionChain.mock.calls[0]?.[3] as AbortSignal;
    expect(firstExpirySignal.aborted).toBe(true);
    expect(activeExpirySignal.aborted).toBe(false);
    expect(dataSignal.aborted).toBe(false);

    unmount();
    expect(activeExpirySignal.aborted).toBe(true);
    expect(dataSignal.aborted).toBe(true);
    await act(async () => {
      pendingChain.resolve({ atm_strike: 25000, chain: [{ strike: 25000, ce: { ltp: 112.5 }, pe: { ltp: 87.5 } }] });
      await pendingChain.promise;
    });
    expect(screen.queryByText("200")).not.toBeInTheDocument();
    expect(chartMocks.createdLineSeries).toHaveLength(0);
  });

  it("makes zero position requests when Live account reads are unconfigured", async () => {
    accountReadState.current = UNCONFIGURED_LIVE_READ_CONTEXT;
    liveChainMocks();

    renderWidget();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledOnce());

    expect(apiMocks.getPositionbook).not.toHaveBeenCalled();
  });

  it.each([
    ["native Live", CONNECTED_NATIVE_READ_CONTEXT],
    ["Practice", PRACTICE_READ_CONTEXT],
  ])("pins %s positions to the exact account context and an AbortSignal", async (_label, context) => {
    accountReadState.current = context;
    liveChainMocks();

    renderWidget();

    await waitFor(() => expect(apiMocks.getPositionbook).toHaveBeenCalledOnce());
    expect(apiMocks.getPositionbook).toHaveBeenCalledWith(context, expect.any(AbortSignal));
  });

  it("clears account-A P&L immediately when account B becomes active", async () => {
    const pendingB = deferred<ReturnType<typeof straddlePosition>[]>();
    liveChainMocks();
    apiMocks.getPositionbook
      .mockResolvedValueOnce([straddlePosition(111)])
      .mockImplementationOnce(() => pendingB.promise);
    const props = makeWidgetPanelProps();
    const { rerender } = render(<StraddleWidget {...props} />);
    expect(await screen.findByText("P&L +111")).toBeInTheDocument();

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<StraddleWidget {...props} />);

    await waitFor(() => expect(screen.queryByText("P&L +111")).not.toBeInTheDocument());
  });

  it("aborts and ignores a late account-A position response after switching to B", async () => {
    const pendingA = deferred<ReturnType<typeof straddlePosition>[]>();
    liveChainMocks();
    apiMocks.getPositionbook
      .mockImplementationOnce(() => pendingA.promise)
      .mockResolvedValueOnce([straddlePosition(222)]);
    const props = makeWidgetPanelProps();
    const { rerender } = render(<StraddleWidget {...props} />);
    await waitFor(() => expect(apiMocks.getPositionbook).toHaveBeenCalledTimes(1));
    const accountASignal = apiMocks.getPositionbook.mock.calls[0]?.[1] as AbortSignal | undefined;

    act(() => { accountReadState.current = ACCOUNT_B_READ_CONTEXT; });
    rerender(<StraddleWidget {...props} />);
    expect(await screen.findByText("P&L +222")).toBeInTheDocument();

    await act(async () => {
      pendingA.resolve([straddlePosition(111)]);
      await pendingA.promise;
    });
    expect(screen.getByText("P&L +222")).toBeInTheDocument();
    expect(screen.queryByText("P&L +111")).not.toBeInTheDocument();
    expect(accountASignal?.aborted).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Implied-move view (absorbed from the retired ImpliedMove widget, merge 2.15)
// ---------------------------------------------------------------------------

describe("StraddleWidget — implied-move view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    accountReadState.current = CONNECTED_NATIVE_READ_CONTEXT;
    marketScopeState.current = "live:native:dhan:A1";
    chartMocks.reset();
    apiMocks.getExpiry.mockReset().mockResolvedValue([]);
    apiMocks.getOptionChain.mockReset().mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockReset().mockResolvedValue({ ltp: 0 });
    apiMocks.getPositionbook.mockReset().mockResolvedValue([]);
  });

  it("opens on the σ-band view when params.view is impliedmove", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Implied move range bar")).toBeInTheDocument();
    });
    expect(screen.getByText("Expected Range")).toBeInTheDocument();
    // The chart plane's overlay toggles belong to the other view only.
    expect(screen.queryByText("Overlay")).not.toBeInTheDocument();
  });

  it("defaults to the straddle chart view when no params.view is given", () => {
    renderWidget();
    expect(screen.getByText("Overlay")).toBeInTheDocument();
    expect(screen.queryByLabelText("Implied move range bar")).not.toBeInTheDocument();
  });

  it("persists the chosen view into the panel params", async () => {
    const updateParameters = vi.fn();
    const props = makeWidgetPanelProps({ params: {} });
    render(<StraddleWidget {...props} api={{ ...props.api, updateParameters }} />);

    screen.getByRole("button", { name: "Implied Move" }).click();

    await waitFor(() => {
      expect(updateParameters).toHaveBeenCalledWith({ view: "impliedmove" });
    });
  });

  // REWRITTEN PIN (was: "keeps the Sample data badge visible even when
  // connected"). The retired widget had no live source, so its badge was
  // unconditional. The σ bands now come from the live chain, so a live chain
  // must produce figures and no sample badge at all.
  it("shows no sample badge once the live chain yields an ATM straddle", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Implied move range bar")).toBeInTheDocument();
    });
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText("No option quote — implied move is unavailable"),
    ).not.toBeInTheDocument();
  });

  // REWRITTEN PIN (was: "shows the Sample data badge when disconnected"). With
  // no live chain the view must disclose the absence rather than substitute a
  // sample — the same honesty the chart view's empty states carry.
  it("discloses the absence of live data instead of showing sample figures", () => {
    renderWidget({ view: "impliedmove" });

    const badge = screen.getByLabelText(
      "No option quote — implied move is unavailable",
    );
    expect(badge.textContent).toBe("No quote data");
    expect(screen.getByText("Implied move needs an ATM straddle quote")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Implied move range bar")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Probability zones table")).not.toBeInTheDocument();
  });

  it("renders the probability zones table from live bands", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByLabelText("Probability zones table")).toBeInTheDocument();
    });
    expect(screen.getByText("68%")).toBeInTheDocument();
    expect(screen.getByText("95%")).toBeInTheDocument();
    // move = 112.5 + 87.5 = 200 on a 25,000 spot
    expect(screen.getAllByText("25,200").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("24,800").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("25,400").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("24,600").length).toBeGreaterThanOrEqual(1);
  });

  it("renders the ATM straddle premium breakdown from live legs", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(screen.getByText("ATM CE Premium")).toBeInTheDocument();
    });
    expect(screen.getByText("ATM PE Premium")).toBeInTheDocument();
    expect(screen.getByText("Total (Implied Move)")).toBeInTheDocument();
    expect(screen.getByText("₹112.5")).toBeInTheDocument();
    expect(screen.getByText("₹87.5")).toBeInTheDocument();
    expect(screen.getByText("₹200")).toBeInTheDocument();
  });

  it("shows the implied move as a percentage of live spot", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    // 200 / 25,000 = 0.80%
    await waitFor(() => {
      expect(screen.getByText("±0.80% of spot")).toBeInTheDocument();
    });
    expect(screen.getByText("±₹200")).toBeInTheDocument();
  });

  // The retired widget's dropdown had 5 entries indexed into a 2-entry sample
  // array, so FINNIFTY rendered NIFTY's figures under a FINNIFTY label. Every
  // figure is now derived from the selected symbol's own live chain, so the
  // mislabel is unrepresentable — pinned here by the absence of any constant
  // table to index into.
  it("derives every figure from the fetched chain, never a symbol-indexed table", async () => {
    liveChainMocks();
    renderWidget({ view: "impliedmove" });

    await waitFor(() => {
      expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
        "NIFTY", "NFO", "2026-07-30", expect.any(AbortSignal), "live:native:dhan:A1",
      );
    });
    expect(apiMocks.getQuotes).toHaveBeenCalledWith(
      "NIFTY", "NSE_INDEX", expect.any(AbortSignal), "live:native:dhan:A1",
    );
  });
});

// ---------------------------------------------------------------------------
// σ arithmetic — ported from the retired ImpliedMove suite, now over the live
// derivation rather than a constant sample table.
// ---------------------------------------------------------------------------

describe("computeImpliedMove", () => {
  const live = { spot: 22350, atmStrike: 22350, cePremium: 142.5, pePremium: 138.2 };

  it("implied move equals CE + PE premium", () => {
    const data = computeImpliedMove(live);
    expect(data?.impliedMove).toBeCloseTo(live.cePremium + live.pePremium, 1);
  });

  it("upper bound equals spot + implied move", () => {
    const data = computeImpliedMove(live);
    expect(data?.upperBound).toBeCloseTo(live.spot + (data?.impliedMove ?? 0), 1);
  });

  it("lower bound equals spot - implied move", () => {
    const data = computeImpliedMove(live);
    expect(data?.lowerBound).toBeCloseTo(live.spot - (data?.impliedMove ?? 0), 1);
  });

  it("2 sigma bounds are twice as wide as 1 sigma bounds", () => {
    const data = computeImpliedMove(live);
    expect(data?.upper2Sigma).toBeCloseTo(live.spot + (data?.impliedMove ?? 0) * 2, 1);
    expect(data?.lower2Sigma).toBeCloseTo(live.spot - (data?.impliedMove ?? 0) * 2, 1);
  });

  it("implied move pct is the move as a percentage of spot", () => {
    const data = computeImpliedMove(live);
    expect(data?.impliedMovePct).toBeCloseTo(((142.5 + 138.2) / 22350) * 100, 4);
    expect(data?.impliedMovePct).toBeGreaterThan(0);
    expect(data?.impliedMovePct).toBeLessThan(10);
  });

  it("fails closed on missing or non-positive live inputs", () => {
    expect(computeImpliedMove({ ...live, spot: null })).toBeNull();
    expect(computeImpliedMove({ ...live, spot: 0 })).toBeNull();
    expect(computeImpliedMove({ ...live, atmStrike: undefined })).toBeNull();
    expect(computeImpliedMove({ ...live, cePremium: 0 })).toBeNull();
    expect(computeImpliedMove({ ...live, pePremium: null })).toBeNull();
    expect(computeImpliedMove({ ...live, spot: Number.NaN })).toBeNull();
  });
});
