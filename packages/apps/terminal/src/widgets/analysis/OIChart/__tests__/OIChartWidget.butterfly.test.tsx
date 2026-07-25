/**
 * OI Analytics — butterfly view (the retired OI Profile widget's presentation)
 * and the optional spot candlestick strip.
 *
 * The strip's label is the fix this merge carried: OI Profile called it the
 * "futures price chart" in its header and its aria-label while fetching
 * `getHistory(symbol, spotExchange)` with NSE_INDEX / BSE_INDEX — index spot.
 * The pane now says spot, and this file pins both the label and the exchange
 * it actually asks for.
 */

import { describe, it, expect, vi, beforeAll, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
  getHistory: vi.fn(),
}));

const mockMode = vi.hoisted(() => ({ current: "live" }));

const plotlyMocks = vi.hoisted(() => ({
  props: [] as Array<{
    data?: Array<{ name?: string; x?: Array<number | null>; y?: Array<number | null> }>;
    layout?: { yaxis?: Record<string, unknown>; annotations?: Array<Record<string, unknown>>; shapes?: Array<Record<string, unknown>> };
  }>,
}));

const chartMocks = vi.hoisted(() => ({
  crosshairCallbacks: [] as Array<(param: unknown) => void>,
  createChartOptions: [] as Array<Record<string, unknown>>,
  fitContent: vi.fn(),
  series: [] as Array<{ setData: ReturnType<typeof vi.fn>; applyOptions: ReturnType<typeof vi.fn> }>,
}));

vi.mock("@/services/api", () => ({
  getExpiry: apiMocks.getExpiry,
  getOptionChain: apiMocks.getOptionChain,
  getQuotes: apiMocks.getQuotes,
  getMaxPain: apiMocks.getMaxPain,
  getHistory: apiMocks.getHistory,
}));

vi.mock("@/services/ftApi", () => ({
  getOIChangeAnalysis: vi.fn().mockResolvedValue({ signals: [], summary: {} }),
  getUnusualOI: vi.fn().mockResolvedValue({ unusual: [], count: 0, threshold: 2 }),
}));

vi.mock("@/lib/market", () => ({ isMarketHours: () => false }));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: mockMode.current }),
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: (props: Record<string, unknown>) => {
    plotlyMocks.props.push(props);
    return <div data-testid="plotly-chart" />;
  },
}));

vi.mock("lightweight-charts", () => ({
  createChart: vi.fn((_el: unknown, options: Record<string, unknown>) => {
    chartMocks.createChartOptions.push(options ?? {});
    return {
      addSeries: vi.fn(() => {
        const series = { setData: vi.fn(), applyOptions: vi.fn() };
        chartMocks.series.push(series);
        return series;
      }),
      resize: vi.fn(),
      remove: vi.fn(),
      applyOptions: vi.fn(),
      priceScale: vi.fn(() => ({ applyOptions: vi.fn() })),
      subscribeCrosshairMove: (callback: (param: unknown) => void) => {
        chartMocks.crosshairCallbacks.push(callback);
      },
      timeScale: vi.fn(() => ({ fitContent: chartMocks.fitContent })),
    };
  }),
  CandlestickSeries: {},
  HistogramSeries: {},
  AreaSeries: {},
  LineSeries: {},
  createSeriesMarkers: vi.fn(() => ({ setMarkers: vi.fn() })),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { makeDockviewPanelProps } from "@/test-utils/dockviewPanelProps";
import OIChartWidget from "../OIChartWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

/** The butterfly view is what the retired `oiprofile` panel id resolves to. */
function renderButterfly(params: Record<string, unknown> = {}) {
  return render(
    <OIChartWidget {...makeDockviewPanelProps({ params: { view: "butterfly", ...params } })} />,
    { wrapper },
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

const LIVE_CHAIN = {
  underlying_ltp: 24_200,
  chain: [
    { strike: 24_000, ce: { oi: 50_000, oi_change: 1_000 }, pe: { oi: 30_000, oi_change: -500 } },
    { strike: 24_200, ce: { oi: 80_000, oi_change: 2_000 }, pe: { oi: 70_000, oi_change: 1_000 } },
    { strike: 24_400, ce: { oi: 60_000, oi_change: -1_000 }, pe: { oi: 20_000, oi_change: -200 } },
  ],
};

beforeAll(() => {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  plotlyMocks.props = [];
  chartMocks.crosshairCallbacks = [];
  chartMocks.createChartOptions = [];
  chartMocks.series = [];
  chartMocks.fitContent.mockReset();
  mockMode.current = "live";
  mockUseBrokerConnected.mockReturnValue(false);
  apiMocks.getExpiry.mockResolvedValue(["2026-03-27"]);
  apiMocks.getOptionChain.mockResolvedValue(LIVE_CHAIN);
  apiMocks.getQuotes.mockResolvedValue({ ltp: 24_200 });
  apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 24_200 });
  apiMocks.getHistory.mockResolvedValue([]);
});

describe("OI Analytics butterfly view", () => {
  it("renders the loading state while the first chain request is in flight", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    const pending = deferred<Record<string, unknown>>();
    apiMocks.getOptionChain.mockReturnValue(pending.promise);

    renderButterfly();

    expect(await screen.findByText(/loading open interest/i)).toBeInTheDocument();
  });

  it("renders the empty state when connected with no expiry to load", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue([]);

    renderButterfly();

    expect(await screen.findByText(/select an expiry to load oi data/i)).toBeInTheDocument();
  });

  it("renders the butterfly profile and the PCR / Max Pain readout from live data", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    expect(await screen.findByTestId("plotly-chart")).toBeInTheDocument();
    expect(screen.getByText(/PCR:/)).toBeInTheDocument();
    expect(screen.getByText("Max Pain: 24,200")).toBeInTheDocument();
  });

  it("draws CE OI to the right and PE OI to the left of the zero line", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    await waitFor(() => expect(plotlyMocks.props.length).toBeGreaterThan(0));
    const latest = plotlyMocks.props[plotlyMocks.props.length - 1];
    expect(latest.data?.[0]).toMatchObject({ name: "CE OI", x: [50_000, 80_000, 60_000] });
    expect(latest.data?.[1]).toMatchObject({ name: "PE OI", x: [-30_000, -70_000, -20_000] });
  });

  it("keeps OI Profile's max-pain arrow annotation alongside the ATM rule", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    await waitFor(() => expect(plotlyMocks.props.length).toBeGreaterThan(0));
    const layout = plotlyMocks.props[plotlyMocks.props.length - 1].layout;
    expect(layout?.annotations?.[0]).toMatchObject({
      text: "Max Pain 24200",
      showarrow: true,
      arrowhead: 2,
    });
    expect(layout?.shapes?.[0]).toMatchObject({ y0: 24_200, y1: 24_200 });
  });

  it("does not draw a max-pain arrow that the backend has not attested live", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: true, max_pain_strike: 24_200 });

    renderButterfly();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalled());
    await waitFor(() => expect(plotlyMocks.props.length).toBeGreaterThan(0));
    const layout = plotlyMocks.props[plotlyMocks.props.length - 1].layout;
    expect(layout?.annotations ?? []).toHaveLength(0);
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
  });

  it("renders the error banner when the chain request fails", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getOptionChain.mockRejectedValue(new Error("OI fetch failed"));

    renderButterfly();

    expect(await screen.findByText(/oi fetch failed/i)).toBeInTheDocument();
  });

  it("badges the sample profile when no broker is connected", async () => {
    mockUseBrokerConnected.mockReturnValue(false);

    renderButterfly();

    expect(screen.getByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(await screen.findByTestId("plotly-chart")).toBeInTheDocument();
    expect(screen.getByText(/PCR:/)).toBeInTheDocument();
  });

  it("caps butterfly strike ticks so compact widgets do not overlap labels", async () => {
    renderButterfly();

    await waitFor(() => expect(plotlyMocks.props.length).toBeGreaterThan(0));
    expect(plotlyMocks.props[0]?.layout?.yaxis?.nticks).toBe(8);
    expect(plotlyMocks.props[0]?.layout?.yaxis?.dtick).toBeUndefined();
  });
});

describe("OI Analytics spot price strip", () => {
  it("opens with the butterfly view, reproducing the retired panel's two-pane layout", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    expect(await screen.findByTestId("spot-price-pane")).toBeInTheDocument();
  });

  it("stays closed on the other views until it is asked for", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    render(
      <OIChartWidget {...makeDockviewPanelProps({ params: { view: "bars" } })} />,
      { wrapper },
    );

    expect(screen.queryByTestId("spot-price-pane")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Spot chart" }));
    expect(await screen.findByTestId("spot-price-pane")).toBeInTheDocument();
  });

  it("labels the strip as SPOT, which is what it actually fetches", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    const { container } = renderButterfly();

    const caption = await screen.findByTestId("spot-price-caption");
    expect(caption).toHaveTextContent("NIFTY spot · 15m");
    // The retired widget called this pane the "futures price chart" while
    // fetching NSE_INDEX spot. That word must not come back.
    expect(container.textContent).not.toMatch(/futures/i);
  });

  it("requests the index spot series, not an F&O contract", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    await screen.findByTestId("spot-price-pane");
    await waitFor(() => expect(apiMocks.getHistory).toHaveBeenCalled());
    const [symbol, exchange, resolution] = apiMocks.getHistory.mock.calls[0];
    expect(symbol).toBe("NIFTY");
    expect(exchange).toBe("NSE_INDEX");
    expect(resolution).toBe("15");
  });

  it("shows the shared OHLCV readout when the spot chart crosshair moves", async () => {
    mockUseBrokerConnected.mockReturnValue(true);

    renderButterfly();

    await screen.findByTestId("spot-price-pane");
    await waitFor(() => expect(chartMocks.crosshairCallbacks).toHaveLength(1));
    const [candleSeries, volumeSeries] = chartMocks.series;
    act(() => {
      chartMocks.crosshairCallbacks[0]?.({
        time: 1_779_811_200,
        seriesData: {
          get: (series: unknown) => {
            if (series === candleSeries) return { open: 24100, high: 24250, low: 24050, close: 24210 };
            if (series === volumeSeries) return { value: 1_250_000 };
            return undefined;
          },
        },
      });
    });

    expect(screen.getByText("24,100.00")).toBeInTheDocument();
    expect(screen.getByText("12.50L")).toBeInTheDocument();
  });
});
