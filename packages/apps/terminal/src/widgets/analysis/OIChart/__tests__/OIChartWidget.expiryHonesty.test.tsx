/**
 * FT-TRADE-007 — OI Chart expiry honesty.
 *
 * Option Chain and OI Chart must share one expiry list for a symbol/exchange.
 * Explore lists those sample expiries and badges Sample. An empty list or an
 * expiry with no OI is an honest empty — never “No expiries” over generic bars.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
  getHistory: vi.fn(),
}));

const mockMode = vi.hoisted(() => ({ current: "explore" }));
const dataScopeState = vi.hoisted(() => ({ current: "explore:mock" }));

const plotlyMocks = vi.hoisted(() => {
  const state = {
    latestData: null as Array<{ name?: string; x?: Array<number | null>; y?: Array<number | null> }> | null,
  };
  return {
    state,
    reset() {
      state.latestData = null;
    },
  };
});

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

vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useDataScope", () => ({
  useMarketDataScope: () => dataScopeState.current,
}));

vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (s: { mode: string }) => unknown) => selector({ mode: mockMode.current }),
}));

vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: ({ data }: { data: Array<{ name?: string; x?: Array<number | null>; y?: Array<number | null> }> }) => {
    plotlyMocks.state.latestData = data;
    return <div data-testid="plotly-chart" />;
  },
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import { optionExpiryIdentity, useOptionExpiryStore } from "@/stores/optionExpiryStore";
import OIChartWidget from "../OIChartWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

const SAMPLE_EXPIRIES = ["2026-09-17", "2026-09-24", "2026-10-01"];
const SAMPLE_CHAIN = {
  is_sample_data: true,
  underlying_ltp: 24_150,
  atm_strike: 24_150,
  pcr: 1.12,
  chain: [
    { strike: 24_100, ce: { oi: 80_000 }, pe: { oi: 95_000 } },
    { strike: 24_150, ce: { oi: 120_000 }, pe: { oi: 110_000 } },
    { strike: 24_200, ce: { oi: 70_000 }, pe: { oi: 60_000 } },
  ],
};

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderWidget(params: Record<string, unknown> = {}) {
  return render(<OIChartWidget {...makeWidgetPanelProps({ params })} />, { wrapper });
}

function resetSharedExpiry() {
  useOptionExpiryStore.setState({ selectedByIdentity: {} });
}

describe("OI Chart expiry honesty (FT-TRADE-007)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    plotlyMocks.reset();
    resetSharedExpiry();
    mockMode.current = "explore";
    dataScopeState.current = "explore:mock";
    mockUseBrokerConnected.mockReturnValue(false);
    apiMocks.getExpiry.mockResolvedValue({ expiry: SAMPLE_EXPIRIES });
    apiMocks.getOptionChain.mockResolvedValue(SAMPLE_CHAIN);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 24_150 });
    apiMocks.getMaxPain.mockResolvedValue({});
    apiMocks.getHistory.mockResolvedValue([]);
  });

  it("asks getExpiry with the same Option Chain identity and lists those sample expiries", async () => {
    renderWidget();

    await waitFor(() => expect(apiMocks.getExpiry).toHaveBeenCalledWith(
      "NIFTY", "NFO", "options", expect.any(AbortSignal), "explore:mock",
    ));
    const strip = await screen.findByTestId("expiry-strip");
    expect(strip).toHaveTextContent("17 Sept");
    expect(strip).toHaveTextContent("24 Sept");
    expect(strip).toHaveTextContent("1 Oct");
    expect(strip).not.toHaveTextContent("No expiries");
  });

  it("defaults to the nearest listed expiry and charts that expiry's sample OI", async () => {
    renderWidget();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-09-17", expect.any(AbortSignal), "explore:mock",
    ));
    expect(await screen.findByTestId("plotly-chart")).toBeInTheDocument();
    expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ name: "CE OI", y: [80_000, 120_000, 70_000] });
    expect(screen.getByText(/PCR:/)).toBeInTheDocument();
  });

  it("badges Explore sample expiries as Sample, not live", async () => {
    renderWidget();

    expect(await screen.findByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(screen.getByTestId("expiry-strip")).toHaveTextContent("17 Sept");
    expect(screen.queryByRole("status", { name: /^Live/ })).toBeNull();
  });

  it("follows Option Chain's selected expiry when both are open", async () => {
    useOptionExpiryStore.getState().setSelected(
      optionExpiryIdentity("explore:mock", "NIFTY", "NFO"),
      "2026-09-24",
    );

    renderWidget();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-09-24", expect.any(AbortSignal), "explore:mock",
    ));
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-09-17", expect.any(AbortSignal), "explore:mock",
    );
  });

  it("shows an honest empty with no bars or PCR when there are no expiries", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [] });

    renderWidget();

    expect(await screen.findByText("No expiries for this symbol")).toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
    expect(screen.queryByText("No expiries", { exact: true })).not.toBeInTheDocument();
    expect(apiMocks.getOptionChain).not.toHaveBeenCalled();
  });

  it("never pairs No expiries with generic sample bars", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [] });

    renderWidget();

    await screen.findByText("No expiries for this symbol");
    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
    expect(screen.queryByText("No expiries", { exact: true })).not.toBeInTheDocument();
  });

  it("shows an honest empty with no bars or stats when the expiry has no OI", async () => {
    apiMocks.getOptionChain.mockResolvedValue({
      is_sample_data: true,
      underlying_ltp: 24_150,
      chain: [
        { strike: 24_100, ce: { oi: 0 }, pe: { oi: 0 } },
        { strike: 24_150, ce: {}, pe: {} },
      ],
    });

    renderWidget();

    expect(await screen.findByText("No OI for this expiry")).toBeInTheDocument();
    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
    expect(screen.getByTestId("expiry-strip")).toHaveTextContent("17 Sept");
  });

  it("still lists sample expiries after the operator picks another sample expiry", async () => {
    renderWidget();
    await screen.findByTestId("plotly-chart");

    fireEvent.click(screen.getByRole("button", { name: "24 Sept" }));

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-09-24", expect.any(AbortSignal), "explore:mock",
    ));
    expect(screen.getByRole("status", { name: /sample data/i })).toBeInTheDocument();
    expect(useOptionExpiryStore.getState().selectedByIdentity[
      optionExpiryIdentity("explore:mock", "NIFTY", "NFO")
    ]).toBe("2026-09-24");
  });
});
