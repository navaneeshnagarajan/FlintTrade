/**
 * OI Analytics — shell, bars view, race guards and provenance.
 *
 * The bars view is the canonical presentation, so this file carries the shared
 * shell's invariants: identity races, the in-flight-key rule, max-pain
 * independence, filtered-row aggregation and the sample-data badge. The other
 * three views have their own files (heat / butterfly / signals) because each
 * needs a different module mock.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
  getHistory: vi.fn(),
}));

const mockMode = vi.hoisted(() => ({ current: "live" }));

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
  useBrokerConnected: vi.fn().mockReturnValue(true),
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

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { makeWidgetPanelProps } from "@/test-utils/widgetPanelProps";
import OIChartWidget from "../OIChartWidget";

const mockUseBrokerConnected = useBrokerConnected as ReturnType<typeof vi.fn>;

function wrapper({ children }: { children: React.ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

function renderWidget(params: Record<string, unknown> = {}) {
  return render(<OIChartWidget {...makeWidgetPanelProps({ params })} />, { wrapper });
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

async function selectSymbol(label: string) {
  fireEvent.click(screen.getByTestId("symbol-select"));
  fireEvent.click(await screen.findByRole("option", { name: label }));
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OI Analytics — shell and bars view", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    plotlyMocks.reset();
    mockMode.current = "live";
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue([]);
    apiMocks.getOptionChain.mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
    apiMocks.getMaxPain.mockResolvedValue({});
    apiMocks.getHistory.mockResolvedValue([]);
  });

  it("renders without crashing", () => {
    const { container } = renderWidget();
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    renderWidget();
    expect(screen.getByTestId("symbol-select").textContent).toContain("NIFTY");
  });

  it("shows the exchange badge", () => {
    renderWidget();
    expect(screen.getByText("NFO")).toBeInTheDocument();
  });

  it("shows filter buttons (All, OI Increase, OI Decrease)", () => {
    renderWidget();
    expect(screen.getByRole("button", { name: "All" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OI Increase" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "OI Decrease" })).toBeInTheDocument();
  });

  it("offers all four views and opens on the view the panel params name", () => {
    renderWidget({ view: "bars" });
    for (const label of ["Bars", "Butterfly", "Heat", "Signals"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
    expect(screen.getByRole("button", { name: "Bars" })).toHaveAttribute("aria-pressed", "true");
  });

  it("falls back to the bars view for an unknown params.view", () => {
    renderWidget({ view: "nonsense" });
    expect(screen.getByRole("button", { name: "Bars" })).toHaveAttribute("aria-pressed", "true");
  });

  it("persists a view change into the panel params so a saved layout reopens on it", () => {
    const updateParameters = vi.fn();
    render(
      <OIChartWidget
        {...makeWidgetPanelProps({
          params: { view: "bars" },
          api: { updateParameters } as unknown as ReturnType<typeof makeWidgetPanelProps>["api"],
        })}
      />,
      { wrapper },
    );

    fireEvent.click(screen.getByRole("button", { name: "Heat" }));

    expect(updateParameters).toHaveBeenCalledWith({ view: "heat" });
  });

  it("shows spot placeholder when no data loaded", () => {
    renderWidget();
    expect(screen.getByText("Spot: —")).toBeInTheDocument();
  });

  it("plots native chain[] option legs", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      pcr: 1.3,
      chain: [
        { strike: 24950, ce: { oi: 10 }, pe: { oi: 15 } },
        { strike: 25000, ce: { oi: 40 }, pe: { oi: 50 } },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(screen.getByTestId("plotly-chart")).toBeInTheDocument();
    });
    expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ name: "CE OI", y: [10, 40] });
    expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ name: "PE OI", y: [15, 50] });
  });

  it("derives ATM from the strike nearest live spot instead of stale backend ATM", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25090 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } },
        { strike: 25100, ce: { oi: 30 }, pe: { oi: 40 } },
      ],
    });

    renderWidget();

    const atmLabel = await screen.findByText("ATM:");
    expect(atmLabel.parentElement).toHaveTextContent("25,100");
  });

  it("trims expiry payloads before enabling option analytics", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [null, "", "   ", " 2026-07-30 "] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    renderWidget();

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith("NIFTY", "NFO", "");
  });

  it("keeps missing OI and dependent totals unavailable while preserving explicit zero", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: {}, pe: { oi: 0 } },
        { strike: 25050, ce: { oi: 10 }, pe: { oi: 20 } },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [null, 10] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ y: [0, 20] });
    });
    expect(screen.getByText("CE --")).toBeInTheDocument();
    expect(screen.getByText("PE 20")).toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
  });

  it("withholds PCR when filtered call OI has a zero denominator even if the response says zero", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      pcr: 0,
      chain: [{ strike: 25000, ce: { oi: 0 }, pe: { oi: 100 } }],
    });

    renderWidget();

    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [0] }));
    expect(screen.getByText("CE 0")).toBeInTheDocument();
    expect(screen.getByText("PE 100")).toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
  });

  it("recomputes totals and PCR from the same filtered rows instead of using whole-chain PCR", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      pcr: 999,
      chain: [
        { strike: 25000, ce: { oi: 150, oi_change: 50 }, pe: { oi: 90, oi_change: -10 } },
        { strike: 25050, ce: { oi: 90, oi_change: -10 }, pe: { oi: 80, oi_change: -20 } },
      ],
    });

    renderWidget();
    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [150, 90] }));

    fireEvent.click(screen.getByRole("button", { name: "OI Increase" }));

    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ x: [25000], y: [150] }));
    expect(screen.getByText("CE 150")).toBeInTheDocument();
    expect(screen.getByText("PE 90")).toBeInTheDocument();
    expect(screen.getByText(/PCR: 0\.60/)).toBeInTheDocument();
    expect(screen.queryByText(/999/)).not.toBeInTheDocument();
  });

  it("filters on the backend's own OI change, not a diff of two client snapshots", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 100, oi_change: -5 }, pe: { oi: 100, oi_change: -5 } }],
      })
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 130, oi_change: 30 }, pe: { oi: 90, oi_change: -10 } }],
      });

    renderWidget();
    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [100] }));

    // The first snapshot reports a REDUCTION, so it must not match "increase"
    // even though it is the first snapshot the client has ever seen.
    fireEvent.click(screen.getByRole("button", { name: "OI Increase" }));
    expect(await screen.findByText("No strikes match the filter")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("refresh-btn"));

    await waitFor(() => {
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [130] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ y: [90] });
    });
    expect(screen.queryByText("No strikes match the filter")).not.toBeInTheDocument();
  });

  it("treats an absent OI change as unknown rather than as an increase or a decrease", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [{ strike: 25000, ce: { oi: 100 }, pe: { oi: 100 } }],
    });

    renderWidget();
    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [100] }));

    fireEvent.click(screen.getByRole("button", { name: "OI Increase" }));
    expect(await screen.findByText("No strikes match the filter")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "OI Decrease" }));
    expect(await screen.findByText("No strikes match the filter")).toBeInTheDocument();
  });

  it("withholds both max-OI markers when either side is incomplete", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: {}, pe: { oi: 10 } },
        { strike: 25050, ce: { oi: 20 }, pe: {} },
        { strike: 25100, ce: {}, pe: {} },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [null, 20, null] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ y: [10, null, null] });
    });
    expect(screen.queryByText(/^R /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^S /)).not.toBeInTheDocument();
  });

  it("marks only the complete positive OI side", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: {}, pe: { oi: 10 } },
        { strike: 25050, ce: { oi: 20 }, pe: { oi: 30 } },
      ],
    });

    renderWidget();

    expect(await screen.findByText("S 25,050")).toBeInTheDocument();
    expect(screen.queryByText(/^R /)).not.toBeInTheDocument();
  });

  it("drops legacy rows without a positive strike instead of plotting strike zero", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      calls: [
        { oi: 100 },
        { strike: 0, oi: 100 },
        { strike_price: 25000, oi: 0 },
      ],
      puts: [
        { strike_price: 25000, oi: 10 },
        { strike_price: 25100, oi: 20 },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ x: [25000, 25100], y: [0, null] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ x: [25000, 25100], y: [10, 20] });
    });
  });

  it("shows explicit zero OI without deriving max-OI or Max Pain markers from an all-zero chain", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { oi: 0 }, pe: { oi: 0 } },
        { strike: 25050, ce: { oi: 0 }, pe: { oi: 0 } },
      ],
    });

    renderWidget();

    await waitFor(() => {
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [0, 0] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ y: [0, 0] });
    });
    expect(screen.getByText("CE 0")).toBeInTheDocument();
    expect(screen.getByText("PE 0")).toBeInTheDocument();
    expect(screen.queryByText(/^R /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^S /)).not.toBeInTheDocument();
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
  });

  it("shows complete positive max-OI markers and explicitly live Max Pain", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [
        { strike: 25000, ce: { oi: 10 }, pe: { oi: 50 } },
        { strike: 25050, ce: { oi: 40 }, pe: { oi: 20 } },
      ],
    });

    renderWidget();

    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();
    expect(screen.getByText("R 25,050")).toBeInTheDocument();
    expect(screen.getByText("S 25,000")).toBeInTheDocument();
  });

  it("does not present sample Max Pain as live", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: true, max_pain_strike: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    renderWidget();

    await waitFor(() => expect(apiMocks.getMaxPain).toHaveBeenCalledOnce());
    expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
  });

  it("does not couple a manual chain refresh to Max Pain", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      atm_strike: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });
    apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 25000 });

    renderWidget();

    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("refresh-btn"));
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2));
    expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(1);
  });

  it("clears stale Max Pain when its independent 60-second refresh fails", async () => {
    vi.useFakeTimers();
    try {
      apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
      apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
      apiMocks.getOptionChain.mockResolvedValue({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
      });
      apiMocks.getMaxPain
        .mockResolvedValueOnce({ is_sample_data: false, max_pain_strike: 25000 })
        .mockRejectedValueOnce(new Error("Max Pain unavailable"));

      renderWidget();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByText("Max Pain: 25,000")).toBeInTheDocument();

      await act(async () => { await vi.advanceTimersByTimeAsync(60_000); });
      expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(2);
      expect(screen.queryByText(/Max Pain:/)).not.toBeInTheDocument();
    } finally {
      vi.useRealTimers();
    }
  });

  it("clears every displayed chain value immediately when expiry identity changes", async () => {
    const nextChain = deferred<Record<string, unknown>>();
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30", "2026-08-06"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockImplementation((_symbol: string, _exchange: string, expiry: string) => (
      expiry === "2026-07-30"
        ? Promise.resolve({
            atm_strike: 25000,
            chain: [{ strike: 25000, ce: { oi: 100 }, pe: { oi: 200 } }],
          })
        : nextChain.promise
    ));

    renderWidget();

    expect(await screen.findByTestId("plotly-chart")).toBeInTheDocument();
    expect(screen.getAllByText("25,000").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "6 Aug" }));

    expect(screen.queryByTestId("plotly-chart")).not.toBeInTheDocument();
    expect(screen.getByText("Spot: —")).toBeInTheDocument();
    expect(screen.queryByText("CE 100")).not.toBeInTheDocument();
    expect(screen.queryByText("ATM:")).not.toBeInTheDocument();
  });

  it("does not request a new symbol with the previous symbol's expiry", async () => {
    const bankExpiry = deferred<{ expiry: string[] }>();
    apiMocks.getExpiry.mockImplementation((symbol: string) => (
      symbol === "NIFTY"
        ? Promise.resolve({ expiry: ["2026-07-30"] })
        : bankExpiry.promise
    ));
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    renderWidget();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));

    await selectSymbol("BANKNIFTY");
    await act(async () => { await Promise.resolve(); });
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-07-30",
    );

    await act(async () => {
      bankExpiry.resolve({ expiry: ["2026-08-06"] });
      await bankExpiry.promise;
    });
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-08-06",
    ));
  });

  it("does not let an abandoned same-key request block a validated identity round trip", async () => {
    const hungNifty = deferred<Record<string, unknown>>();
    let niftyCalls = 0;
    apiMocks.getExpiry.mockImplementation((symbol: string) => Promise.resolve({
      expiry: [symbol === "NIFTY" ? "2026-07-30" : "2026-08-06"],
    }));
    apiMocks.getOptionChain.mockImplementation((symbol: string) => {
      if (symbol === "NIFTY" && niftyCalls++ === 0) return hungNifty.promise;
      return Promise.resolve({
        underlying_ltp: symbol === "NIFTY" ? 25000 : 55000,
        chain: [{ strike: symbol === "NIFTY" ? 25000 : 55000, ce: { oi: 10 }, pe: { oi: 20 } }],
      });
    });

    renderWidget();
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));

    await selectSymbol("BANKNIFTY");
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-08-06",
    ));

    await selectSymbol("NIFTY");
    await waitFor(() => expect(
      apiMocks.getOptionChain.mock.calls.filter(([symbol]) => symbol === "NIFTY"),
    ).toHaveLength(2));
  });

  it("polls Max Pain independently at 60 seconds, not with the chain loop", async () => {
    vi.useFakeTimers();
    try {
      apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
      apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
      apiMocks.getOptionChain.mockResolvedValue({
        underlying_ltp: 25000,
        chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
      });
      apiMocks.getMaxPain.mockResolvedValue({ is_sample_data: false, max_pain_strike: 25000 });

      renderWidget();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);
      expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
      expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getMaxPain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("skips an auto-refresh tick while the same identity request is pending", async () => {
    vi.useFakeTimers();
    try {
      const pendingChain = deferred<Record<string, unknown>>();
      apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
      apiMocks.getOptionChain.mockReturnValue(pendingChain.promise);
      apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });

      renderWidget();
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        pendingChain.resolve({
          atm_strike: 25000,
          chain: [{ strike: 25000, ce: { oi: 100 }, pe: { oi: 200 } }],
        });
        await pendingChain.promise;
      });
      await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps one ATM window for every view so their aggregates cannot disagree", async () => {
    // ±15 strikes each side of ATM, from the canonical bar chart. The heat grid
    // used to slice ±10 from the same payload, which gave the two panels
    // different totals, PCR and support/resistance for one snapshot.
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain.mockResolvedValue({
      chain: Array.from({ length: 61 }, (_, i) => ({
        strike: 24_400 + i * 20,
        ce: { oi: 10 },
        pe: { oi: 20 },
      })),
    });

    renderWidget();

    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]?.x).toHaveLength(31));
    const barStrikes = plotlyMocks.state.latestData?.[0]?.x;

    fireEvent.click(screen.getByRole("button", { name: "Heat" }));
    await waitFor(() => expect(screen.getAllByText("24700").length).toBeGreaterThan(0));
    // The heat grid renders one label per strike in the same window.
    expect(screen.getByText(String(barStrikes?.[0]))).toBeInTheDocument();
    expect(screen.getByText(String(barStrikes?.[30]))).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// Data provenance. The heat grid used to render fabricated open interest with
// no affordance at all: its FeatureTeaser wrapper said "In Development", which
// is a roadmap label, not a statement about the data. In Explore mode the
// broker reads as connected while the API serves a mock chain, so that case
// needs badging too.
// ---------------------------------------------------------------------------

describe("OI Analytics data provenance", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    plotlyMocks.reset();
    mockMode.current = "live";
    mockUseBrokerConnected.mockReturnValue(true);
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getMaxPain.mockResolvedValue({});
  });

  it("badges the sample chain when no broker is connected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("badges Explore mode even though a broker reads as connected", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockMode.current = "explore";
    renderWidget();
    expect(screen.getByRole("status", { name: /sample data/i })).toBeTruthy();
  });

  it("drops the badge on a live connected read", () => {
    mockUseBrokerConnected.mockReturnValue(true);
    mockMode.current = "live";
    renderWidget();
    expect(screen.queryByRole("status", { name: /sample data/i })).toBeNull();
  });

  it("does not reach the network at all while disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(apiMocks.getExpiry).not.toHaveBeenCalled();
    expect(apiMocks.getOptionChain).not.toHaveBeenCalled();
  });

  it("disables refresh while disconnected", () => {
    mockUseBrokerConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByTestId("refresh-btn")).toBeDisabled();
  });

  it("enables refresh once connected with a validated expiry", async () => {
    mockUseBrokerConnected.mockReturnValue(true);
    renderWidget();
    await waitFor(() => expect(screen.getByTestId("refresh-btn")).not.toBeDisabled());
  });
});
