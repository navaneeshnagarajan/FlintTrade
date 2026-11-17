/**
 * PortfolioRRGView — example-data labelling.
 *
 * The portfolio plot fails closed on provenance: only an explicit
 * `is_sample_data: false` drops the Example data badge.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

vi.stubGlobal(
  "ResizeObserver",
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
);

const ftApiMocks = vi.hoisted(() => ({
  getPortfolioRRGData: vi.fn(),
  getSectorConstituents: vi.fn(),
}));

vi.mock("@/services/ftApi", () => ({
  getPortfolioRRGData: ftApiMocks.getPortfolioRRGData,
  getSectorConstituents: ftApiMocks.getSectorConstituents,
}));

import { useModeStore } from "@/stores/modeStore";
import { PortfolioRRGView } from "../PortfolioRRGView";

function rrgPayload(provenance: { is_sample_data?: boolean }) {
  return {
    benchmark: "NIFTY 50",
    tail_length: 2,
    sectors: [
      {
        symbol: "RELIANCE",
        name: "Reliance Industries",
        current_quadrant: "leading",
        tail: [
          { date: "2026-07-17", rs_ratio: 100.4, rs_momentum: 100.2 },
          { date: "2026-07-18", rs_ratio: 100.9, rs_momentum: 100.6 },
        ],
      },
    ],
    ...provenance,
  };
}

function renderView() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <PortfolioRRGView />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  localStorage.setItem("flinttrade_portfolio_rrg_symbols", JSON.stringify(["RELIANCE"]));
  HTMLCanvasElement.prototype.getContext = vi.fn().mockReturnValue(null);
  useModeStore.setState({ mode: "practice" });
});

afterEach(() => {
  useModeStore.setState({ mode: "practice" });
});

describe("PortfolioRRGView — example-data badge", () => {
  it("badges a sample-flagged portfolio plot in Practice", async () => {
    ftApiMocks.getPortfolioRRGData.mockResolvedValue(rrgPayload({ is_sample_data: true }));
    renderView();
    expect(await screen.findByTestId("example-data-badge")).toHaveTextContent("Example data");
  });

  it("fails closed when the response omits the provenance flag", async () => {
    ftApiMocks.getPortfolioRRGData.mockResolvedValue(rrgPayload({}));
    renderView();
    expect(await screen.findByTestId("example-data-badge")).toBeInTheDocument();
  });

  it("shows no badge for an explicitly live plot", async () => {
    ftApiMocks.getPortfolioRRGData.mockResolvedValue(rrgPayload({ is_sample_data: false }));
    renderView();
    expect(await screen.findByLabelText("Refresh portfolio RRG")).toBeInTheDocument();
    await vi.waitFor(() => expect(ftApiMocks.getPortfolioRRGData).toHaveBeenCalledTimes(1));
    await Promise.resolve();
    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });

  it("shows no badge before any symbol has been plotted", () => {
    localStorage.clear();
    renderView();
    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
    expect(ftApiMocks.getPortfolioRRGData).not.toHaveBeenCalled();
  });

  it("stays hidden in Explore, where the Mode line already says Example data", async () => {
    useModeStore.setState({ mode: "explore" });
    ftApiMocks.getPortfolioRRGData.mockResolvedValue(rrgPayload({ is_sample_data: true }));
    renderView();
    await vi.waitFor(() => expect(ftApiMocks.getPortfolioRRGData).toHaveBeenCalledTimes(1));
    await Promise.resolve();
    expect(screen.queryByTestId("example-data-badge")).not.toBeInTheDocument();
  });
});
