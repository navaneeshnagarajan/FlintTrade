/**
 * OIChartWidget.test.tsx
 *
 * Tests for the OI Chart analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks — must be defined before component import
// ---------------------------------------------------------------------------

const apiMocks = vi.hoisted(() => ({
  getExpiry: vi.fn(),
  getOptionChain: vi.fn(),
  getQuotes: vi.fn(),
  getMaxPain: vi.fn(),
}));

const plotlyMocks = vi.hoisted(() => {
  const state = {
    latestData: null as Array<{ name?: string; x?: number[]; y?: Array<number | null> }> | null,
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
}));

// Mock market hours helper
vi.mock("@/lib/market", () => ({
  isMarketHours: () => false,
}));

// Mock PlotlyChart lazy import
vi.mock("@/components/charts/PlotlyChart", () => ({
  PlotlyChart: ({ data }: { data: Array<{ name?: string; x?: number[]; y?: Array<number | null> }> }) => {
    plotlyMocks.state.latestData = data;
    return <div data-testid="plotly-chart" />;
  },
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import OIChartWidget, { getOIChange } from "../OIChartWidget";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("OIChartWidget", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    plotlyMocks.reset();
    apiMocks.getExpiry.mockResolvedValue([]);
    apiMocks.getOptionChain.mockResolvedValue({ calls: [], puts: [] });
    apiMocks.getQuotes.mockResolvedValue({ ltp: 0 });
    apiMocks.getMaxPain.mockResolvedValue({});
  });

  it("renders without crashing", () => {
    const { container } = render(<OIChartWidget />);
    expect(container.firstChild).toBeInTheDocument();
  });

  it("shows the default symbol (NIFTY) in the selector", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("NIFTY")).toBeInTheDocument();
  });

  it("shows the exchange badge", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("NFO")).toBeInTheDocument();
  });

  it("shows filter buttons (All, OI Increase, OI Decrease)", () => {
    render(<OIChartWidget />);
    expect(screen.getByText("All")).toBeInTheDocument();
    expect(screen.getByText("OI Increase")).toBeInTheDocument();
    expect(screen.getByText("OI Decrease")).toBeInTheDocument();
  });

  it("shows spot placeholder when no data loaded", () => {
    render(<OIChartWidget />);
    // Spot shows dash when no data
    expect(screen.getByText(/Spot/)).toBeInTheDocument();
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

    render(<OIChartWidget />);

    await waitFor(() => {
      expect(screen.getByTestId("plotly-chart")).toBeInTheDocument();
    });
    expect(plotlyMocks.state.latestData?.[0]).toMatchObject({
      name: "CE OI",
      y: [10, 40],
    });
    expect(plotlyMocks.state.latestData?.[1]).toMatchObject({
      name: "PE OI",
      y: [15, 50],
    });
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

    render(<OIChartWidget />);

    const atmLabel = await screen.findByText("ATM:");
    expect(atmLabel.parentElement).toHaveTextContent("25,100");
  });

  it("trims expiry payloads before enabling option analytics", async () => {
    apiMocks.getExpiry.mockResolvedValue({ expiry: [null, "", "   ", " 2026-07-30 "] });
    apiMocks.getOptionChain.mockResolvedValue({
      underlying_ltp: 25000,
      chain: [{ strike: 25000, ce: { oi: 10 }, pe: { oi: 20 } }],
    });

    render(<OIChartWidget />);

    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));
    expect(apiMocks.getOptionChain).not.toHaveBeenCalledWith("NIFTY", "NFO", "");
  });

  it("keeps first-snapshot OI change unavailable", () => {
    expect(getOIChange(100, undefined)).toBeNull();
    expect(getOIChange(100, 100)).toBe(0);
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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [0] }));
    expect(screen.getByText("CE 0")).toBeInTheDocument();
    expect(screen.getByText("PE 100")).toBeInTheDocument();
    expect(screen.queryByText(/PCR:/)).not.toBeInTheDocument();
  });

  it("recomputes totals and PCR from the same filtered rows instead of using whole-chain PCR", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain
      .mockResolvedValueOnce({
        atm_strike: 25000,
        pcr: 999,
        chain: [
          { strike: 25000, ce: { oi: 100 }, pe: { oi: 100 } },
          { strike: 25050, ce: { oi: 100 }, pe: { oi: 100 } },
        ],
      })
      .mockResolvedValueOnce({
        atm_strike: 25000,
        pcr: 999,
        chain: [
          { strike: 25000, ce: { oi: 150 }, pe: { oi: 90 } },
          { strike: 25050, ce: { oi: 90 }, pe: { oi: 80 } },
        ],
      });

    render(<OIChartWidget />);
    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [100, 100] }));

    fireEvent.click(screen.getByTitle("Refresh"));
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2));
    fireEvent.click(screen.getByRole("button", { name: "OI Increase" }));

    await waitFor(() => expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ x: [25000], y: [150] }));
    expect(screen.getByText("CE 150")).toBeInTheDocument();
    expect(screen.getByText("PE 90")).toBeInTheDocument();
    expect(screen.getByText(/PCR: 0\.60/)).toBeInTheDocument();
    expect(screen.queryByText(/999/)).not.toBeInTheDocument();
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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);

    expect(await screen.findByText("Max Pain: 25,000")).toBeInTheDocument();
    fireEvent.click(screen.getByTitle("Refresh"));
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

      render(<OIChartWidget />);
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

    render(<OIChartWidget />);

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

    render(<OIChartWidget />);
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));

    fireEvent.click(screen.getByRole("button", { name: "NIFTY" }));
    fireEvent.click(screen.getByRole("button", { name: "BANKNIFTY" }));
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

    render(<OIChartWidget />);
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "NIFTY", "NFO", "2026-07-30",
    ));

    fireEvent.click(screen.getByRole("button", { name: "NIFTY" }));
    fireEvent.click(screen.getByRole("button", { name: "BANKNIFTY" }));
    await waitFor(() => expect(apiMocks.getOptionChain).toHaveBeenCalledWith(
      "BANKNIFTY", "NFO", "2026-08-06",
    ));

    fireEvent.click(screen.getByRole("button", { name: "BANKNIFTY" }));
    fireEvent.click(screen.getByRole("button", { name: "NIFTY" }));
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

      render(<OIChartWidget />);
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

      render(<OIChartWidget />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(1);

      await act(async () => {
        pendingChain.resolve({
          atm_strike: 25000,
          chain: [{ strike: 25000, ce: { oi: 100 }, pe: { oi: 200 } }],
        });
        await pendingChain.promise;
      });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(30_000);
      });
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("compares a refresh with the retained previous snapshot", async () => {
    apiMocks.getExpiry.mockResolvedValue(["2026-07-30"]);
    apiMocks.getQuotes.mockResolvedValue({ ltp: 25000 });
    apiMocks.getOptionChain
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 100 }, pe: { oi: 100 } }],
      })
      .mockResolvedValueOnce({
        atm_strike: 25000,
        chain: [{ strike: 25000, ce: { oi: 130 }, pe: { oi: 90 } }],
      });

    render(<OIChartWidget />);

    await waitFor(() => {
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [100] });
    });

    fireEvent.click(screen.getByRole("button", { name: "OI Increase" }));
    expect(await screen.findByText("No strikes match the filter")).toBeInTheDocument();

    fireEvent.click(screen.getByTitle("Refresh"));

    await waitFor(() => {
      expect(apiMocks.getOptionChain).toHaveBeenCalledTimes(2);
      expect(plotlyMocks.state.latestData?.[0]).toMatchObject({ y: [130] });
      expect(plotlyMocks.state.latestData?.[1]).toMatchObject({ y: [90] });
    });
    expect(screen.queryByText("No strikes match the filter")).not.toBeInTheDocument();
  });
});
