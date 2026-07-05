/**
 * OIChartWidget.test.tsx
 *
 * Tests for the OI Chart analysis widget.
 * Verifies rendering, loading states, and key UI elements.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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
    latestData: null as Array<{ name?: string; y?: number[] }> | null,
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
  PlotlyChart: ({ data }: { data: Array<{ name?: string; y?: number[] }> }) => {
    plotlyMocks.state.latestData = data;
    return <div data-testid="plotly-chart" />;
  },
}));

// ---------------------------------------------------------------------------
// Import component under test (after mocks)
// ---------------------------------------------------------------------------

import OIChartWidget from "../OIChartWidget";

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
    apiMocks.getMaxPain.mockResolvedValue({ max_pain_strike: 25000 });
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
});
