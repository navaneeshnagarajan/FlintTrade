/**
 * ResultsSection.test.tsx — the Results tab's multi-run comparison card.
 *
 * Pins the /backtest/compare wiring: two session runs enable Compare, the
 * comparison renders best-overall + per-strategy metrics + the suggested
 * blend, and a single run shows the enable hint instead.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

const mockCompare = vi.fn();
vi.mock("@/services/ftApi", () => ({
  compareBacktests: (...a: unknown[]) => mockCompare(...a),
}));
vi.mock("../BacktestResultDisplay", () => ({
  BacktestResultDisplay: () => <div data-testid="result-display" />,
}));

import { ResultsSection } from "../ResultsSection";
import type { BacktestResult } from "@/services/ftApi.backtest";

function wrapper() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(QueryClientProvider, { client: qc }, children);
}

function fakeRun(seed: number): BacktestResult {
  return {
    trades: [],
    equity_curve: Array.from({ length: 10 }, (_, i) => ({
      timestamp: `2026-01-${String(i + 1).padStart(2, "0")}`,
      equity: 100000 + seed * 1000 + i * 100,
    })),
    metrics: {
      total_return: 5 + seed,
      cagr: 0.1 + seed / 100,
      sharpe_ratio: 1.0 + seed / 10,
      sortino_ratio: 1.5,
      max_drawdown: -4.2,
      win_rate: 0.6,
      profit_factor: 1.8,
      total_trades: 12,
      expectancy: 0.4,
    },
    final_equity: 105000,
    total_bars: 10,
  };
}

const COMPARISON = {
  strategies: ["sma_cross", "rsi_revert"],
  metrics: {
    sma_cross: { sharpe: 1.1, cagr: 11, max_drawdown: -4.2, win_rate: 60, profit_factor: 1.8 },
    rsi_revert: { sharpe: 1.4, cagr: 14, max_drawdown: -3.1, win_rate: 64, profit_factor: 2.1 },
  },
  rankings: { sharpe: ["rsi_revert", "sma_cross"] },
  best_overall: "rsi_revert",
  equity_curves: { sma_cross: [1, 2], rsi_revert: [1, 3] },
  correlation_matrix: [[1, 0.4], [0.4, 1]],
  optimal_blend: { rsi_revert: 0.6, sma_cross: 0.4 },
};

beforeEach(() => {
  mockCompare.mockReset();
  mockCompare.mockResolvedValue(COMPARISON);
});

describe("ResultsSection comparison", () => {
  it("compares two session runs and shows winner, table, and blend", async () => {
    const runs = { sma_cross: fakeRun(1), rsi_revert: fakeRun(4) };
    render(<ResultsSection lastResult={runs.rsi_revert} sessionRuns={runs} />, {
      wrapper: wrapper(),
    });

    const button = screen.getByRole("button", { name: /compare/i });
    expect(button).toBeEnabled();
    fireEvent.click(button);

    // the mutation maps the SESSION RUNS map straight through
    await waitFor(() => expect(mockCompare).toHaveBeenCalledTimes(1));
    expect(Object.keys(mockCompare.mock.calls[0][0] as object).sort()).toEqual([
      "rsi_revert", "sma_cross",
    ]);

    // winner callout + starred row + blend chips
    expect(await screen.findByText(/best overall/i)).toBeInTheDocument();
    expect(screen.getAllByText("rsi_revert").length).toBeGreaterThan(1);
    expect(screen.getByText(/suggested blend/i)).toBeInTheDocument();
    expect(screen.getByText(/rsi_revert 60%/)).toBeInTheDocument();
  });

  it("disables Compare and hints when only one run exists", () => {
    const runs = { sma_cross: fakeRun(1) };
    render(<ResultsSection lastResult={runs.sma_cross} sessionRuns={runs} />, {
      wrapper: wrapper(),
    });

    expect(screen.getByRole("button", { name: /compare/i })).toBeDisabled();
    expect(screen.getByText(/run a second strategy/i)).toBeInTheDocument();
    expect(mockCompare).not.toHaveBeenCalled();
  });

  it("shows no compare card with zero runs (empty state)", () => {
    render(<ResultsSection lastResult={null} sessionRuns={{}} />, {
      wrapper: wrapper(),
    });
    expect(screen.queryByRole("button", { name: /compare/i })).not.toBeInTheDocument();
    expect(screen.getByText(/No data yet/i)).toBeInTheDocument();
  });

  it("surfaces a comparison failure honestly", async () => {
    mockCompare.mockRejectedValue(new Error("comparator unavailable"));
    const runs = { sma_cross: fakeRun(1), rsi_revert: fakeRun(4) };
    render(<ResultsSection lastResult={runs.rsi_revert} sessionRuns={runs} />, {
      wrapper: wrapper(),
    });

    fireEvent.click(screen.getByRole("button", { name: /compare/i }));
    expect(await screen.findByText(/comparison failed: comparator unavailable/i)).toBeInTheDocument();
  });
});
