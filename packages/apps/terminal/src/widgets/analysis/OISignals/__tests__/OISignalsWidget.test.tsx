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

const mockAnalysis = vi.fn();
const mockUnusual = vi.fn();
vi.mock("@/services/ftApi", () => ({
  getOIChangeAnalysis: (...a: unknown[]) => mockAnalysis(...a),
  getUnusualOI: (...a: unknown[]) => mockUnusual(...a),
}));

import OISignalsWidget from "../OISignalsWidget";

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

beforeEach(() => {
  state.connected = false;
  mockAnalysis.mockReset();
  mockUnusual.mockReset();
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("OISignalsWidget", () => {
  it("renders the header", () => {
    render(<OISignalsWidget />, { wrapper: wrapper() });
    expect(screen.getByText("OI Signals")).toBeInTheDocument();
  });

  it("shows the Sample data badge and sample signals when disconnected", () => {
    render(<OISignalsWidget />, { wrapper: wrapper() });
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    // a sample strike from sampleData renders
    expect(screen.getAllByText("24500").length).toBeGreaterThan(0);
    // the queries are gated off while disconnected
    expect(mockAnalysis).not.toHaveBeenCalled();
    expect(mockUnusual).not.toHaveBeenCalled();
  });

  it("shows Live signals from the backend when connected", async () => {
    state.connected = true;
    mockAnalysis.mockResolvedValue({
      signals: [
        { strike: 25000, option_type: "CE", oi: 1_000_000, oi_change: 200_000, price_change: "up", signal: "Long Build-up", signal_short: "LB" },
      ],
      long_buildups: [25000],
      short_coverings: [],
      short_buildups: [],
      long_unwindings: [],
      summary: { "Long Build-up": 1 },
    });
    mockUnusual.mockResolvedValue({
      unusual: [
        { strike: 25000, option_type: "CE", oi: 1_000_000, oi_change: 200_000, change_pct: 25, z_score: 3.1, direction: "addition" },
      ],
      count: 1,
      threshold: 2.0,
    });

    render(<OISignalsWidget />, { wrapper: wrapper() });

    expect(await screen.findByText("Live")).toBeInTheDocument();
    // the live strike replaces the sample
    expect(await screen.findByText("25000")).toBeInTheDocument();
    await waitFor(() => expect(mockAnalysis).toHaveBeenCalledWith("NIFTY", "NFO", "", "flat"));
    expect(mockUnusual).toHaveBeenCalled();
  });
});
