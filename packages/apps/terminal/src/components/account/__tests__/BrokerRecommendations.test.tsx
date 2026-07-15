/**
 * BrokerRecommendations.test — smart routing suggestions panel.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrokerRecommendations } from "../BrokerRecommendations";

vi.mock("@/services/ftApi.native", () => ({ listBrokerRecommendations: vi.fn() }));
import { listBrokerRecommendations } from "@/services/ftApi.native";

const mockListBrokerRecommendations = listBrokerRecommendations as unknown as ReturnType<typeof vi.fn>;

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

  it("renders every backend use-case with ready or unavailable state", async () => {
    mockListBrokerRecommendations.mockResolvedValue({
      status: "success",
      use_cases: {
        low_cost_execution: [
          {
            broker_id: "kotakneo",
            display_name: "Kotak Neo",
            connectable: false,
            score: 1,
            raw_score: 10,
            rationale: "Zero brokerage.",
          },
          {
            broker_id: "upstox",
            display_name: "Upstox",
            connectable: true,
            score: 0.5,
            raw_score: 5,
            rationale: "Free API access.",
          },
        ],
        market_depth: [
          {
            broker_id: "dhan",
            display_name: "Dhan",
            connectable: true,
            score: 0.9,
            raw_score: 9,
            rationale: "20-level depth.",
          },
        ],
        historical_data: [
          {
            broker_id: "indmoney",
            display_name: "INDmoney",
            connectable: false,
            score: 0.7,
            raw_score: 7,
            rationale: "REST token supports account reads.",
          },
        ],
        streaming: [
          {
            broker_id: "dhan",
            display_name: "Dhan",
            connectable: true,
            score: 0,
            raw_score: 0,
            rationale: "Feed not wired yet.",
          },
        ],
      },
    });
    renderPanel();
    expect(await screen.findByText("Upstox")).toBeInTheDocument();
    expect(screen.queryByText("Kotak Neo")).not.toBeInTheDocument();
    expect(screen.getByText("Dhan")).toBeInTheDocument();
    expect(screen.queryByText("INDmoney")).not.toBeInTheDocument();
    expect(screen.queryByText("IndMoney")).not.toBeInTheDocument();
    expect(screen.getByText("Lowest cost")).toBeInTheDocument();
    expect(screen.getByText("Free API access.")).toBeInTheDocument();
    expect(screen.getByText("Live streaming")).toBeInTheDocument();
    expect(screen.getAllByText("Not ready")).toHaveLength(2);
    expect(screen.getByText("Feed not wired yet.")).toBeInTheDocument();
    // Honest scope note: the rankings are capability-derived and default to
    // activation-evidence-cleared connectable native brokers.
    expect(screen.getByText(/capability-based suggestions/i)).toBeInTheDocument();
    expect(screen.getByText(/evidence-gated adapters stay hidden/i)).toBeInTheDocument();
  });

  it("shows an unavailable message on error", async () => {
    mockListBrokerRecommendations.mockRejectedValue(new Error("boom"));
    renderPanel();
    expect(await screen.findByText(/unavailable right now/i)).toBeInTheDocument();
  });

  it("shows an empty message when no brokers rank", async () => {
    mockListBrokerRecommendations.mockResolvedValue({ status: "success", use_cases: {} });
    renderPanel();
    expect(await screen.findByText(/no native brokers available/i)).toBeInTheDocument();
  });
});
