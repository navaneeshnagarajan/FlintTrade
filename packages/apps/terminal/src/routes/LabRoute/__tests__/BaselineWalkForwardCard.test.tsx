/**
 * BaselineWalkForwardCard.test.tsx — the honest buy-and-hold walk-forward UI.
 *
 * Pins: the card states plainly it does NOT test the user's strategy; Run
 * fetches real history and posts it to /v1/backtest/walkforward; results
 * render stability verdict + per-split table; short history fails honestly.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const mockGetHistory = vi.fn();
const mockWalkForward = vi.fn();
vi.mock("@/services/api", () => ({
  getHistory: (...a: unknown[]) => mockGetHistory(...a),
}));
vi.mock("@/services/ftApi", () => ({
  runBaselineWalkForward: (...a: unknown[]) => mockWalkForward(...a),
}));

import { BaselineWalkForwardCard } from "../BaselineWalkForwardCard";

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BaselineWalkForwardCard />
    </QueryClientProvider>,
  );
}

const BARS = Array.from({ length: 120 }, (_, i) => ({
  close: 100 + i, open: 99 + i, high: 101 + i, low: 98 + i, volume: 1000, timestamp: "",
}));

const RESULT = {
  splits: [
    {
      split_index: 0, train_start: 0, train_end: 59, test_start: 60, test_end: 89,
      n_train_bars: 60, n_test_bars: 30, train_metric: 1.2, test_metric: 1.0,
      degradation_pct: 16.7,
    },
  ],
  avg_train_metric: 1.2,
  avg_test_metric: 1.0,
  degradation_pct: 16.7,
  is_robust: true,
  n_splits_run: 1,
};

beforeEach(() => {
  mockGetHistory.mockReset();
  mockWalkForward.mockReset();
  mockGetHistory.mockResolvedValue(BARS);
  mockWalkForward.mockResolvedValue(RESULT);
});

describe("BaselineWalkForwardCard", () => {
  it("states plainly that it does not test the user's strategy", () => {
    renderCard();
    expect(screen.getByText(/buy-and-hold baseline/i)).toBeInTheDocument();
    expect(screen.getByText(/does/)).toBeInTheDocument();
    expect(screen.getByText(/not/)).toBeInTheDocument();
    expect(screen.getByText(/use the Robustness panel/i)).toBeInTheDocument();
  });

  it("runs: fetches history and posts the bars to the walk-forward route", async () => {
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    await waitFor(() => expect(mockWalkForward).toHaveBeenCalledTimes(1));
    // bars pass through untouched; sharpe metric + the chosen split count
    expect(mockWalkForward.mock.calls[0][0]).toHaveLength(120);
    expect(mockWalkForward.mock.calls[0][1]).toBe("sharpe_ratio");
    expect(mockWalkForward.mock.calls[0][2]).toEqual({ n_splits: 5 });

    // results: stat tiles + stability verdict + split row
    expect(await screen.findByText(/in-sample sharpe/i)).toBeInTheDocument();
    expect(screen.getByText(/stable — baseline holds/i)).toBeInTheDocument();
    expect(screen.getByText("#1")).toBeInTheDocument();
  });

  it("shows the unstable verdict when the baseline degrades", async () => {
    mockWalkForward.mockResolvedValue({ ...RESULT, is_robust: false, degradation_pct: 55 });
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByText(/unstable — baseline degrades/i)).toBeInTheDocument();
  });

  it("fails honestly when there is not enough history", async () => {
    mockGetHistory.mockResolvedValue(BARS.slice(0, 10));
    renderCard();
    fireEvent.click(screen.getByRole("button", { name: /run/i }));

    expect(await screen.findByText(/not enough history/i)).toBeInTheDocument();
    expect(mockWalkForward).not.toHaveBeenCalled();
  });
});
