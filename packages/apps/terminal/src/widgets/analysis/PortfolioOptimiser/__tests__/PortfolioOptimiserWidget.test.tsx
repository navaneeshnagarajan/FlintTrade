import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const state = vi.hoisted(() => ({ connected: false }));
vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: () => state.connected,
}));

const mockGetHistory = vi.fn();
const mockOptimise = vi.fn();
vi.mock("@/services/api", () => ({
  getHistory: (...a: unknown[]) => mockGetHistory(...a),
}));
vi.mock("@/services/ftApi", () => ({
  optimisePortfolio: (...a: unknown[]) => mockOptimise(...a),
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

beforeEach(() => {
  state.connected = false;
  mockGetHistory.mockReset();
  mockOptimise.mockReset();
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
});

const SAMPLE_NOT_USED = {
  weights: {}, expected_return: 0, expected_volatility: 0, sharpe_ratio: 0, diversification_ratio: 0,
};
