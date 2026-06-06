import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@testing-library/jest-dom";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------
//
// When connected, the widget fetches daily bars per leg (`getHistory`) and runs
// the pair-correlation engine (`getPairCorrelation`). We mock both so we can
// exercise the live ("Live" badge) and sample ("Sample data" badge) paths.

vi.mock("@/hooks/useBrokerConnected", () => ({
  useBrokerConnected: vi.fn().mockReturnValue(false),
}));

vi.mock("@/hooks/useTrackBehavior", () => ({
  useTrackBehavior: () => vi.fn(),
}));

vi.mock("@/services/api", () => ({
  getHistory: vi.fn(),
}));

vi.mock("@/services/ftApi.analysis", () => ({
  getPairCorrelation: vi.fn(),
}));

import { useBrokerConnected } from "@/hooks/useBrokerConnected";
import { getHistory } from "@/services/api";
import { getPairCorrelation } from "@/services/ftApi.analysis";
import CorrelationPairsWidget from "../CorrelationPairsWidget";

const mockConnected = useBrokerConnected as ReturnType<typeof vi.fn>;
const mockGetHistory = getHistory as ReturnType<typeof vi.fn>;
const mockGetPairs = getPairCorrelation as ReturnType<typeof vi.fn>;

function liveSignals() {
  return {
    signals: [
      { pair: ["TCS", "INFY"] as [string, string], correlation: 0.91, current_spread: 1910, mean_spread: 1890, std_spread: 85, z_score: 0.24, signal: "neutral" as const },
      { pair: ["RELIANCE", "NIFTY"] as [string, string], correlation: 0.77, current_spread: 19480, mean_spread: 19560, std_spread: 210, z_score: -0.38, signal: "converging" as const },
    ],
  };
}

function renderWidget() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <CorrelationPairsWidget />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  mockConnected.mockReturnValue(false);
  mockGetHistory.mockResolvedValue([]);
  mockGetPairs.mockResolvedValue({ signals: [] });
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

describe("CorrelationPairsWidget", () => {
  it("renders widget title", () => {
    renderWidget();
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("shows the Sample data badge when disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(screen.getByText("Sample data")).toBeTruthy();
  });

  it("does not fetch when broker disconnected", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    expect(mockGetHistory).not.toHaveBeenCalled();
    expect(mockGetPairs).not.toHaveBeenCalled();
  });

  it("flips to a Live badge once the engine returns pair signals", async () => {
    mockConnected.mockReturnValue(true);
    mockGetHistory.mockResolvedValue(
      Array.from({ length: 60 }, (_, i) => ({
        timestamp: 1700000000 + i * 86400,
        open: 100, high: 101, low: 99, close: 100 + i, volume: 1000,
      })),
    );
    mockGetPairs.mockResolvedValue(liveSignals());
    renderWidget();

    await waitFor(() => expect(screen.getByText("Live")).toBeInTheDocument());
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
    // Live pair from the engine is rendered.
    expect(screen.getAllByText("TCS").length).toBeGreaterThanOrEqual(1);
    expect(mockGetPairs).toHaveBeenCalled();
  });

  it("falls back to Sample data when connected but the engine returns no pairs", async () => {
    mockConnected.mockReturnValue(true);
    mockGetPairs.mockResolvedValue({ signals: [] });
    renderWidget();

    await waitFor(() => expect(mockGetPairs).toHaveBeenCalled());
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText("Live")).not.toBeInTheDocument();
  });

  it("badge discloses no live source via its accessible name (sample mode)", () => {
    mockConnected.mockReturnValue(false);
    renderWidget();
    const badge = screen.getByText("Sample data");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute(
      "aria-label",
      "Showing sample data; no live correlation data source is wired yet",
    );
  });

  it("does not render a deceptive live-looking refresh control", () => {
    renderWidget();
    expect(screen.queryByRole("button", { name: /refresh correlation data/i })).toBeNull();
  });

  it("renders table column headers: Pair, Corr, Z-Score, Signal", () => {
    renderWidget();
    expect(screen.getByText("Pair")).toBeTruthy();
    expect(screen.getByText("Corr")).toBeTruthy();
    expect(screen.getByText("Z-Score")).toBeTruthy();
    expect(screen.getByText("Signal")).toBeTruthy();
  });

  it("renders NIFTY and BANKNIFTY in pair rows (sample mode)", () => {
    renderWidget();
    expect(screen.getAllByText("NIFTY").length).toBeGreaterThanOrEqual(1);
    expect(screen.getAllByText("BANKNIFTY").length).toBeGreaterThanOrEqual(1);
  });

  it("renders signal labels: Converging and Diverging (sample mode)", () => {
    renderWidget();
    const divergingCells = screen.getAllByText("Diverging");
    const convergingCells = screen.getAllByText("Converging");
    expect(divergingCells.length).toBeGreaterThan(0);
    expect(convergingCells.length).toBeGreaterThan(0);
  });

  it("sorts by correlation when Corr header is clicked", () => {
    renderWidget();
    const corrHeader = screen.getByRole("columnheader", { name: /corr/i });
    fireEvent.click(corrHeader);
    expect(screen.getByText("Correlation Pairs")).toBeTruthy();
  });

  it("renders footer note about z-score and correlation", () => {
    renderWidget();
    expect(screen.getAllByText(/Z-score/i).length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(/20-day rolling returns/i)).toBeTruthy();
  });
});
