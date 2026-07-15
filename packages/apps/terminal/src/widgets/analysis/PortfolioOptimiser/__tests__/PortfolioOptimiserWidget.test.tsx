import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const state = vi.hoisted(() => ({
  connected: false,
  mode: "live" as "explore" | "practice" | "live",
}));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => state.connected,
}));
vi.mock("@/hooks/useDataScope", () => ({
  useDataScope: () => `${state.mode}:test-scope`,
}));
vi.mock("@/stores/modeStore", () => ({
  useModeStore: (selector: (value: { mode: typeof state.mode }) => unknown) => selector({ mode: state.mode }),
}));

const mockGetHistory = vi.fn();
const mockOptimise = vi.fn();
const mockFrontier = vi.fn();
vi.mock("@/services/api", () => ({
  getHistory: (...a: unknown[]) => mockGetHistory(...a),
}));
vi.mock("@/services/ftApi", () => ({
  optimisePortfolio: (...a: unknown[]) => mockOptimise(...a),
  getPortfolioFrontier: (...a: unknown[]) => mockFrontier(...a),
}));

import PortfolioOptimiserWidget from "../PortfolioOptimiserWidget";

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

// 120 ascending closes per symbol → > MIN_POINTS, enough to optimise.
const bars = (base: number) =>
  Array.from({ length: 120 }, (_, i) => ({ close: base + i, high: 0, low: 0, open: 0, volume: 0, timestamp: "" }));

const FRONTIER_ROWS = Array.from({ length: 5 }, (_, i) => ({
  weights: {},
  expected_return: 0.08 + i * 0.03,
  expected_volatility: 0.12 + i * 0.04,
  sharpe_ratio: 0.3 + i * 0.05,
  diversification_ratio: 1.3,
}));

beforeEach(() => {
  state.connected = false;
  state.mode = "live";
  mockGetHistory.mockReset();
  mockOptimise.mockReset();
  mockFrontier.mockReset();
  mockFrontier.mockResolvedValue(FRONTIER_ROWS);
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("PortfolioOptimiserWidget", () => {
  it("renders the header", () => {
    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });
    expect(screen.getByText("Portfolio Optimiser")).toBeInTheDocument();
  });

  it("shows the Sample data badge and sample weights when disconnected", () => {
    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.getByText("RELIANCE")).toBeInTheDocument();
    expect(mockGetHistory).not.toHaveBeenCalled();
    expect(mockOptimise).not.toHaveBeenCalled();
    expect(mockFrontier).not.toHaveBeenCalled();
    // the frontier chart renders with the sample curve
    expect(
      screen.getByRole("img", { name: /efficient frontier/i }),
    ).toBeInTheDocument();
  });

  it("does not reuse connected Live results while Explore is active", async () => {
    state.connected = true;
    state.mode = "explore";

    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });

    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(mockGetHistory).not.toHaveBeenCalled();
      expect(mockOptimise).not.toHaveBeenCalled();
      expect(mockFrontier).not.toHaveBeenCalled();
    });
  });

  it("labels successful sandbox-scoped optimisation as Practice", async () => {
    state.mode = "practice";
    mockGetHistory.mockResolvedValue(bars(100));
    mockOptimise.mockResolvedValue({
      weights: { RELIANCE: 0.5, TCS: 0.5 },
      expected_return: 0.2,
      expected_volatility: 0.15,
      sharpe_ratio: 0.9,
      diversification_ratio: 1.4,
    });

    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });

    expect(await screen.findByText("Practice")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("optimises the basket from real history when connected", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue(bars(100));
    mockOptimise.mockResolvedValue({
      weights: { RELIANCE: 0.5, TCS: 0.5 },
      expected_return: 0.2,
      expected_volatility: 0.15,
      sharpe_ratio: 0.9,
      diversification_ratio: 1.4,
    });

    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });

    expect(await screen.findByText("Live")).toBeInTheDocument();
    // optimise called with equal-length return series (120 closes → 119 returns)
    await waitFor(() => expect(mockOptimise).toHaveBeenCalledTimes(1));
    const returnsArg = mockOptimise.mock.calls[0][0] as Record<string, number[]>;
    const lengths = Object.values(returnsArg).map((r) => r.length);
    expect(new Set(lengths).size).toBe(1); // all aligned to one length
    expect(lengths[0]).toBe(119);

    // the frontier is requested with the SAME aligned return series
    await waitFor(() => expect(mockFrontier).toHaveBeenCalledTimes(1));
    expect(mockFrontier.mock.calls[0][0]).toEqual(returnsArg);
    expect(
      screen.getByRole("img", { name: /efficient frontier/i }),
    ).toBeInTheDocument();
  });

  it("falls back to sample when too few symbols return history", async () => {
    state.connected = true;
    // Only one symbol returns usable history → < 2 valid → optimise never called
    mockGetHistory.mockImplementation((sym: string) =>
      Promise.resolve(sym === "RELIANCE" ? bars(100) : []),
    );
    mockOptimise.mockResolvedValue(SAMPLE_NOT_USED);

    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });

    expect(await screen.findByText("Sample data")).toBeInTheDocument();
    await waitFor(() => expect(mockOptimise).not.toHaveBeenCalled());
  });

  it("does not place a sample frontier under a Live badge", async () => {
    state.connected = true;
    mockGetHistory.mockResolvedValue(bars(100));
    mockOptimise.mockResolvedValue({
      weights: { LIVE_ONLY: 1 },
      expected_return: 0.2,
      expected_volatility: 0.15,
      sharpe_ratio: 0.9,
      diversification_ratio: 1.4,
    });
    mockFrontier.mockResolvedValue([]);

    render(<PortfolioOptimiserWidget />, { wrapper: wrapper() });

    expect(await screen.findByText(/Live optimisation unavailable/i)).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
    expect(screen.queryByText("LIVE_ONLY")).not.toBeInTheDocument();
  });
});

const SAMPLE_NOT_USED = {
  weights: {}, expected_return: 0, expected_volatility: 0, sharpe_ratio: 0, diversification_ratio: 0,
};
