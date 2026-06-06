import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi", () => ({
  runPortfolioBacktest: vi.fn(),
}));
import { runPortfolioBacktest } from "@/services/ftApi";
import { PortfolioBacktestSection } from "../PortfolioBacktestSection";

const mockRun = runPortfolioBacktest as unknown as ReturnType<typeof vi.fn>;

const RESULT = {
  result: {
    total_return: 0.18,
    annual_return: 0.18,
    sharpe_ratio: 1.4,
    sortino_ratio: 1.9,
    max_drawdown: -0.12,
    calmar_ratio: 1.5,
    volatility: 0.15,
    var_95: -0.03,
    final_equity: 1_180_000,
    equity_curve: [1_000_000, 1_050_000, 1_180_000],
    drawdown_curve: [0, -0.02, 0],
    rebalance_log: [],
  },
};

function renderSection() {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <PortfolioBacktestSection />
    </QueryClientProvider>,
  );
}

describe("PortfolioBacktestSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockRun.mockResolvedValue(RESULT);
  });

  it("runs a multi-instrument portfolio backtest and renders performance metrics", async () => {
    renderSection();
    fireEvent.click(screen.getByRole("button", { name: /run portfolio backtest/i }));

    expect(await screen.findByText("Performance")).toBeInTheDocument();
    expect(screen.getByText("Total Return")).toBeInTheDocument();
    expect(screen.getByText("Final Equity")).toBeInTheDocument();

    // TanStack passes (variables, context); assert on the config (first arg).
    await waitFor(() => expect(mockRun).toHaveBeenCalled());
    expect(mockRun.mock.calls[0][0]).toMatchObject({
      symbols: ["RELIANCE", "TCS", "INFY", "HDFCBANK"],
      allocation_strategy: "equal_weight",
      rebalance_freq: "monthly",
    });
  });

  it("disables the run button with fewer than two symbols", () => {
    renderSection();
    fireEvent.change(screen.getByLabelText("Portfolio symbols"), { target: { value: "RELIANCE" } });
    expect(screen.getByRole("button", { name: /run portfolio backtest/i })).toBeDisabled();
    expect(mockRun).not.toHaveBeenCalled();
  });
});
