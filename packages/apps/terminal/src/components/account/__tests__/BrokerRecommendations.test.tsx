/**
 * BrokerRecommendations.test — smart routing suggestions panel.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrokerRecommendations } from "../BrokerRecommendations";

vi.mock("@/services/ftApi", () => ({ get: vi.fn() }));
import { get } from "@/services/ftApi";

const mockGet = get as unknown as ReturnType<typeof vi.fn>;

function renderPanel() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <BrokerRecommendations />
    </QueryClientProvider>,
  );
}

describe("BrokerRecommendations", () => {
  beforeEach(() => vi.clearAllMocks());

  it("renders the top broker + rationale per use-case", async () => {
    mockGet.mockResolvedValue({
      status: "success",
      use_cases: {
        low_cost_execution: [
          { broker_id: "kotakneo", score: 1, raw_score: 10, rationale: "Zero brokerage." },
        ],
        market_depth: [
          { broker_id: "dhan", score: 0.9, raw_score: 9, rationale: "20-level depth." },
        ],
      },
    });
    renderPanel();
    expect(await screen.findByText("Kotak Neo")).toBeInTheDocument();
    expect(screen.getByText("Dhan")).toBeInTheDocument();
    expect(screen.getByText("Lowest cost")).toBeInTheDocument();
    expect(screen.getByText("Zero brokerage.")).toBeInTheDocument();
    // Honest scope note: the rankings are capability-derived, and native
    // execution needs SDK activation (orders route via the OpenAlgo bridge).
    expect(screen.getByText(/capability-based suggestions/i)).toBeInTheDocument();
    expect(screen.getByText(/route via the OpenAlgo/i)).toBeInTheDocument();
  });

  it("shows an unavailable message on error", async () => {
    mockGet.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText(/unavailable right now/i)).toBeInTheDocument();
  });

  it("shows an empty message when no brokers rank", async () => {
    mockGet.mockResolvedValue({ status: "success", use_cases: {} });
    renderPanel();
    expect(await screen.findByText(/no native brokers available/i)).toBeInTheDocument();
  });
});
