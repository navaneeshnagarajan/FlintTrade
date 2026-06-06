import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("@/services/ftApi.ai", () => ({ getLatestOptimiserReport: vi.fn() }));
import { getLatestOptimiserReport } from "@/services/ftApi.ai";
import { OptimizeSection } from "../OptimizeSection";

const mockGet = getLatestOptimiserReport as unknown as ReturnType<typeof vi.fn>;

function renderSection() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <OptimizeSection />
    </QueryClientProvider>,
  );
}

describe("OptimizeSection", () => {
  beforeEach(() => vi.clearAllMocks());

  it("shows an empty state (not a 'Coming soon' placeholder) when no reports exist", async () => {
    mockGet.mockResolvedValue({ report: null });
    renderSection();

    expect(await screen.findByTestId("overnight-report-empty")).toBeInTheDocument();
    expect(screen.queryByText(/coming soon/i)).not.toBeInTheDocument();
  });

  it("renders the latest overnight report's suggestions", async () => {
    mockGet.mockResolvedValue({
      report: {
        timestamp: "2026-06-06T02:00:00+00:00",
        strategies_seen: 2,
        strategies_optimised: 2,
        suggestions: [
          {
            strategy_name: "ema_cross",
            analysis: "Widen the stop-loss to lift the Sharpe.",
            suggested_params: { stop_loss_pct: 0.025 },
            reasoning: "Low risk-adjusted return",
            confidence: 0.72,
          },
        ],
        errors: [],
      },
    });
    renderSection();

    expect(await screen.findByText("ema_cross")).toBeInTheDocument();
    expect(screen.getByText(/Widen the stop-loss/i)).toBeInTheDocument();
    expect(screen.getByText(/confidence 72%/i)).toBeInTheDocument();
    expect(screen.getByText(/2 of 2/)).toBeInTheDocument();
  });
});
