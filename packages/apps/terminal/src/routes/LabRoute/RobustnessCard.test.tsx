import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi", () => ({
  runPermutationTest: vi.fn(),
}));
import { runPermutationTest, type BacktestResult } from "@/services/ftApi";
import { RobustnessCard } from "./RobustnessCard";

const mockRun = runPermutationTest as unknown as ReturnType<typeof vi.fn>;

function curve(n: number): BacktestResult["equity_curve"] {
  return Array.from({ length: n }, (_, i) => ({
    timestamp: `2025-01-${String(i + 1).padStart(2, "0")}T00:00:00Z`,
    equity: 100_000 + i * 500,
  }));
}

function makeResult(points: number): BacktestResult {
  return {
    equity_curve: curve(points),
    trades: [],
    metrics: {},
    final_equity: 0,
    total_bars: 0,
  } as unknown as BacktestResult;
}

function renderCard(result: BacktestResult) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <RobustnessCard result={result} />
    </QueryClientProvider>,
  );
}

describe("RobustnessCard", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("runs the permutation test and shows a significance verdict", async () => {
    mockRun.mockResolvedValue({
      original_metric: 1.8,
      permutation_mean: 0.1,
      permutation_std: 0.4,
      p_value: 0.012,
      is_significant: true,
      confidence_level: 0.95,
      n_permutations: 1000,
      percentile_rank: 98.8,
    });

    renderCard(makeResult(20)); // 19 returns -> enough

    const btn = screen.getByRole("button", { name: /run permutation test/i });
    expect(btn).toBeEnabled();
    fireEvent.click(btn);

    expect(await screen.findByText(/Statistically significant edge/i)).toBeInTheDocument();
    expect(screen.getByText("0.0120")).toBeInTheDocument(); // p-value formatted
    // The real return series was derived from the equity curve and posted.
    await waitFor(() => expect(mockRun).toHaveBeenCalledTimes(1));
    expect(mockRun.mock.calls[0][0]).toHaveLength(19);
  });

  it("disables the test and explains when the curve is too short", () => {
    renderCard(makeResult(4)); // 3 returns -> not enough
    expect(screen.getByRole("button", { name: /run permutation test/i })).toBeDisabled();
    expect(screen.getByText(/needs at least 10 equity points/i)).toBeInTheDocument();
    expect(mockRun).not.toHaveBeenCalled();
  });

  it("surfaces an error when the engine rejects the request", async () => {
    mockRun.mockRejectedValue(new Error("returns must be a non-empty list of numbers"));
    renderCard(makeResult(15));
    fireEvent.click(screen.getByRole("button", { name: /run permutation test/i }));
    expect(await screen.findByText(/Permutation test failed/i)).toBeInTheDocument();
  });
});
